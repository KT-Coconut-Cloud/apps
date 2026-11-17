import hashlib

from tests.conftest import CLEAN, LANDING, QUARANTINE, Context, keys, put, read

RUN = "20261117-01"
TABLES = ["citizen", "crisis_signal", "benefit_payment"]
BODY = b"citizen_id\nt_0000000000000000\nt_0000000000000001\n"


class FakeMacie:
    def __init__(self, findings=()):
        self.jobs = []
        self.findings = list(findings)

    def create_classification_job(self, **kwargs):
        self.jobs.append(kwargs)
        return {"jobId": "job-1"}

    def list_findings(self, **kwargs):
        return {"findingIds": [str(i) for i in range(len(self.findings))]}

    def get_findings(self, findingIds):
        return {"findings": [self.findings[int(i)] for i in findingIds]}


class FakeSns:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)


def upload_run(s3, status="exported", body=BODY):
    files = []
    if status == "exported":
        for t in TABLES:
            key = f"run_id={RUN}/{t}.csv"
            put(s3, LANDING, key, body)
            files.append({"key": key, "rows": 2, "sha256": hashlib.sha256(BODY).hexdigest()})
    put(s3, LANDING, f"run_id={RUN}/adequacy_review.json", {"run_id": RUN, "passed": status == "exported"})
    put(s3, LANDING, f"run_id={RUN}/export_record.json", {"run_id": RUN, "status": status, "files": files})


def event():
    key = f"run_id={RUN}/export_record.json"
    return {"detail": {"bucket": {"name": LANDING}, "object": {"key": key}}}


def finding(table, managed=(), custom=()):
    return {
        "resourcesAffected": {"s3Object": {"key": f"run_id={RUN}/{table}.csv"}},
        "classificationDetails": {"result": {
            "sensitiveData": [{"detections": [{"type": t, "count": 1} for t in managed]}],
            "customDataIdentifiers": {"detections": [{"name": n, "count": 2} for n in custom]},
        }},
    }


def test_check_copies_reports_and_starts_macie(aws):
    s3, mods = aws
    mods["check"].macie = fake = FakeMacie()
    upload_run(s3)
    out = mods["check"].handler(event(), Context())

    assert out["action"] == "scan" and out["job_id"] == "job-1"
    assert all(f["version_id"] for f in out["files"])
    assert keys(s3, CLEAN) == [f"reports/run_id={RUN}/adequacy_review.json", f"reports/run_id={RUN}/export_record.json"]
    job = fake.jobs[0]
    assert job["name"] == f"pii-{RUN}" and job["clientToken"] == RUN
    assert job["customDataIdentifierIds"] == ["cdi-1", "cdi-2"] and job["allowListIds"] == ["al-1"]
    terms = [t["simpleScopeTerm"] for t in job["s3JobDefinition"]["scoping"]["includes"]["and"]]
    assert terms[0]["values"] == [f"run_id={RUN}/"] and terms[1]["values"] == ["csv"]


def test_blocked_run_only_copies_reports(aws):
    s3, mods = aws
    mods["check"].macie = fake = FakeMacie()
    upload_run(s3, status="aborted")
    assert mods["check"].handler(event(), Context()) == {"run_id": RUN, "action": "skip"}
    assert len(keys(s3, CLEAN)) == 2 and fake.jobs == []


def test_changed_file_is_an_error(aws):
    s3, mods = aws
    mods["check"].macie = fake = FakeMacie()
    upload_run(s3, body=BODY + b"t_0000000000000002\n")
    out = mods["check"].handler(event(), Context())
    assert out["action"] == "error" and "sha256 mismatch" in out["error"] and "3 rows" in out["error"]
    assert fake.jobs == []


def scan_state(s3, mods, status="COMPLETE"):
    mods["check"].macie = FakeMacie()
    upload_run(s3)
    state = mods["check"].handler(event(), Context())
    return {**state, "macie": {"status": status}}


def test_pass_publishes_run(aws):
    s3, mods = aws
    state = scan_state(s3, mods)
    mods["classify"].macie = FakeMacie()
    mods["classify"].sns = sns = FakeSns()
    assert mods["classify"].handler(state, None) == {"run_id": RUN, "verdict": "PASS"}

    assert [k for k in keys(s3, LANDING) if k.endswith(".csv")] == []
    assert f"data/citizen/run_id={RUN}/citizen.csv" in keys(s3, CLEAN)
    result = read(s3, CLEAN, f"reports/run_id={RUN}/macie_result.json")
    assert result["verdict"] == "PASS" and {f["classification"] for f in result["files"]} == {"clean"}
    assert read(s3, CLEAN, f"results/run_id={RUN}/manifest.json")["tables"] == TABLES
    assert sns.messages == []


def test_scanned_version_is_moved_even_if_file_changes_later(aws):
    s3, mods = aws
    state = scan_state(s3, mods)
    put(s3, LANDING, f"run_id={RUN}/citizen.csv", b"rrn\n900101-1234567\n")
    mods["classify"].macie = FakeMacie()
    mods["classify"].handler(state, None)
    moved = s3.get_object(Bucket=CLEAN, Key=f"data/citizen/run_id={RUN}/citizen.csv")["Body"].read()
    assert moved == BODY


def test_fail_quarantines_whole_run_and_alerts(aws, monkeypatch):
    s3, mods = aws
    monkeypatch.setenv("ALERT_TOPIC_ARN", "arn:aws:sns:ap-northeast-2:123456789012:alerts")
    state = scan_state(s3, mods)
    mods["classify"].macie = FakeMacie([finding("crisis_signal", managed=["PHONE_NUMBER"], custom=["KR_RRN"])])
    mods["classify"].sns = sns = FakeSns()
    assert mods["classify"].handler(state, None)["verdict"] == "FAIL"

    assert sorted(keys(s3, QUARANTINE)) == sorted(f"run_id={RUN}/{t}.csv" for t in TABLES)
    assert not any(k.startswith(("data/", "results/")) for k in keys(s3, CLEAN))
    files = {f["key"]: f for f in read(s3, CLEAN, f"reports/run_id={RUN}/macie_result.json")["files"]}
    assert files[f"run_id={RUN}/crisis_signal.csv"]["types"] == ["KR_RRN", "PHONE_NUMBER"]
    assert files[f"run_id={RUN}/citizen.csv"] == {**files[f"run_id={RUN}/citizen.csv"], "detected": False,
                                                    "classification": "quarantine"}
    message = sns.messages[0]["Message"]
    assert "FAIL" in message and "KR_RRN (1 file)" in message


def test_hash_error_quarantines_with_reason(aws):
    s3, mods = aws
    mods["check"].macie = FakeMacie()
    upload_run(s3, body=b"changed\n")
    state = mods["check"].handler(event(), Context())
    mods["classify"].sns = FakeSns()
    assert mods["classify"].handler(state, None)["verdict"] == "ERROR"
    result = read(s3, CLEAN, f"reports/run_id={RUN}/macie_result.json")
    assert "sha256 mismatch" in result["error"] and len(keys(s3, QUARANTINE)) == 3


def test_cancelled_macie_job_is_an_error(aws):
    s3, mods = aws
    state = scan_state(s3, mods, status="CANCELLED")
    mods["classify"].sns = FakeSns()
    assert mods["classify"].handler(state, None)["verdict"] == "ERROR"
    assert read(s3, CLEAN, f"reports/run_id={RUN}/macie_result.json")["error"] == "macie job CANCELLED"


def test_second_run_of_classify_does_nothing(aws):
    s3, mods = aws
    state = scan_state(s3, mods)
    mods["classify"].macie = FakeMacie()
    mods["classify"].handler(state, None)
    assert mods["classify"].handler(state, None)["verdict"] == "SKIPPED"
