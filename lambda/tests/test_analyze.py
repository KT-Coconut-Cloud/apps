import pytest
from botocore.exceptions import ClientError

from tests.conftest import CLEAN, Context, keys, put, read

RUN = "20261117-01"
REQUEST = {
    "run_id": RUN,
    "scenario": "recheck_by_household",
    "params": {"pay_month": "2025-12", "region": "서울특별시"},
    "purpose": "점검",
    "requested_by": "policy01",
}


def rows(*lines):
    return [{"Data": [{"VarCharValue": v} if v is not None else {} for v in line]} for line in lines]


class FakeAthena:
    def __init__(self, result=(), fail=False):
        self.started = []
        self.result = list(result)
        self.fail = fail

    def start_query_execution(self, **kwargs):
        if self.fail:
            raise ClientError({"Error": {"Code": "InvalidRequestException", "Message": "x"}}, "StartQueryExecution")
        self.started.append(kwargs)
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Query": self.started[0]["QueryString"]}}

    def get_paginator(self, name):
        fake = self

        class Pages:
            def paginate(self, QueryExecutionId):
                return [{"ResultSet": {"Rows": fake.result}}]

        return Pages()


@pytest.fixture
def ready(aws):
    s3, mods = aws
    put(s3, CLEAN, f"results/run_id={RUN}/manifest.json", {"run_id": RUN, "adequacy_passed": True})
    return s3, mods


def use(mods, athena):
    mods["analyze"].athena = mods["finalize"].athena = athena


def ended(state, workgroup="analysis"):
    return {"detail": {"queryExecutionId": "q-1", "currentState": state, "workgroupName": workgroup}}


def test_request_is_recorded_and_query_started(ready):
    s3, mods = ready
    use(mods, fake := FakeAthena())
    out = mods["analyze"].handler(REQUEST, Context())
    rid = out["request_id"]
    assert out["status"] == "running" and rid.endswith("-0001")

    q = fake.started[0]
    assert q["QueryString"].startswith(f"-- request_id={rid}\n")
    assert q["ExecutionParameters"] == ["'2025-12'", "'서울특별시'"]
    assert "서울" not in q["QueryString"] and "BETWEEN 1 AND 4 THEN NULL" in q["QueryString"]
    assert read(s3, CLEAN, f"reports/analysis_requests/{rid}.json")["status"] == "running"
    assert f"results/requests/{rid}/manifest.json" not in keys(s3, CLEAN)


def test_request_ids_count_up(ready):
    _, mods = ready
    use(mods, FakeAthena())
    first = mods["analyze"].handler(REQUEST, Context())["request_id"]
    second = mods["analyze"].handler(REQUEST, Context())["request_id"]
    assert int(second[-4:]) == int(first[-4:]) + 1


@pytest.mark.parametrize("change, error", [
    ({"scenario": "drop_table"}, "unknown_scenario"),
    ({"params": {"region": "서울특별시"}}, "invalid_params"),
    ({"params": {"pay_month": "2025-12", "region": "' OR 1=1 --"}}, "invalid_params"),
    ({"run_id": "20261101-01"}, "run_not_ready"),
    ({"run_id": "x' OR '1'='1"}, "run_not_ready"),
    ({"purpose": ""}, "invalid_params"),
])
def test_bad_requests_start_nothing(ready, change, error):
    s3, mods = ready
    use(mods, fake := FakeAthena())
    assert mods["analyze"].handler({**REQUEST, **change}, Context())["error"] == error
    assert fake.started == [] and not any(k.startswith("results/requests/") for k in keys(s3, CLEAN))


def test_rejected_query_is_recorded_as_failed(ready):
    s3, mods = ready
    use(mods, FakeAthena(fail=True))
    out = mods["analyze"].handler(REQUEST, Context())
    assert out["status"] == "failed"
    manifest = read(s3, CLEAN, f"results/requests/{out['request_id']}/manifest.json")
    assert manifest["error"] == "query_failed: InvalidRequestException"


def test_finished_query_is_published(ready):
    s3, mods = ready
    use(mods, FakeAthena(rows(
        ("household_size", "payments", "within", "recheck", "no_data"),
        ("1", "320", "250", "66", None),
        ("2", "75", "60", None, None),
        ("3", None, None, "0", "0"),
    )))
    rid = mods["analyze"].handler(REQUEST, Context())["request_id"]
    out = mods["finalize"].handler(ended("SUCCEEDED"), None)
    assert out["status"] == "succeeded" and out["rows"] == 3 and out["suppressed_cells"] == 5

    text = s3.get_object(Bucket=CLEAN, Key=f"results/requests/{rid}/result.csv")["Body"].read().decode()
    assert text.splitlines()[2:] == ["2,75,60,,", "3,,,0,0"]
    assert read(s3, CLEAN, f"results/requests/{rid}/manifest.json")["status"] == "succeeded"
    record = read(s3, CLEAN, f"reports/analysis_requests/{rid}.json")
    assert record["status"] == "succeeded" and record["purpose"] == "점검"

    # a repeated event leaves the published result alone
    assert mods["finalize"].handler(ended("SUCCEEDED"), None) is None


def test_failed_query_is_recorded(ready):
    s3, mods = ready
    use(mods, FakeAthena())
    rid = mods["analyze"].handler(REQUEST, Context())["request_id"]
    out = mods["finalize"].handler(ended("FAILED"), None)
    assert out["status"] == "failed" and out["error"] == "query_failed: FAILED"
    assert read(s3, CLEAN, f"reports/analysis_requests/{rid}.json")["status"] == "failed"
    assert f"results/requests/{rid}/result.csv" not in keys(s3, CLEAN)


@pytest.mark.parametrize("event", [ended("RUNNING"), ended("SUCCEEDED", workgroup="primary")])
def test_other_events_are_ignored(ready, event):
    _, mods = ready
    use(mods, FakeAthena())
    mods["analyze"].handler(REQUEST, Context())
    assert mods["finalize"].handler(event, None) is None

def test_template_needs_its_columns(ready):
    s3, mods = ready
    use(mods, fake := FakeAthena())
    s3.put_object(Bucket=CLEAN, Key=f"data/livelihood_payment/run_id={RUN}/livelihood_payment.csv",
                  Body=",".join(mods["catalog"].BASE_COLUMNS).encode() + b"\n")
    out = mods["analyze"].handler({**REQUEST, "scenario": "paid_after_death"}, Context())
    assert out["error"] == "template_unavailable" and not fake.started
    assert mods["analyze"].handler(REQUEST, Context())["status"] == "running"

