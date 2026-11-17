import pytest
from botocore.exceptions import ClientError

from tests.conftest import CLEAN, Context, keys, put, read

RUN = "20261117-01"
REQUEST = {
    "run_id": RUN,
    "scenario": "crisis_link_rate",
    "params": {"from": "2026-05", "to": "2026-10", "crisis_type": None, "sigungu": "서울 강서구"},
    "purpose": "점검",
    "requested_by": "policy01",
}


def rows(*lines):
    return [{"Data": [{"VarCharValue": v} if v is not None else {} for v in line]} for line in lines]


class FakeAthena:
    def __init__(self, result=(), state="SUCCEEDED", fail=False):
        self.started = []
        self.result = list(result)
        self.state = state
        self.fail = fail

    def start_query_execution(self, **kwargs):
        if self.fail:
            raise ClientError({"Error": {"Code": "InvalidRequestException", "Message": "x"}}, "StartQueryExecution")
        self.started.append(kwargs)
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": self.state}}}

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


def test_request_runs_query_and_publishes_result(ready):
    s3, mods = ready
    mods["analyze"].athena = fake = FakeAthena(rows(
        ("sigungu", "crisis_type", "households", "linked"),
        ("서울 강서구", "단전", "40", "12"),
        ("서울 강서구", "단수", "9", None),
        ("서울 강서구", "금융 연체", None, "0"),
    ))
    out = mods["analyze"].handler(REQUEST, Context())
    rid = out["request_id"]
    assert out["status"] == "succeeded" and rid.endswith("-0001")

    q = fake.started[0]
    assert q["ExecutionParameters"] == ["'2026-05'", "'2026-10'", "'서울 강서구'"]
    assert "서울" not in q["QueryString"] and "BETWEEN 1 AND 4 THEN NULL" in q["QueryString"]

    text = s3.get_object(Bucket=CLEAN, Key=f"results/requests/{rid}/result.csv")["Body"].read().decode()
    assert text.splitlines()[2:] == ["서울 강서구,단수,9,", "서울 강서구,금융 연체,,0"]
    manifest = read(s3, CLEAN, f"results/requests/{rid}/manifest.json")
    assert manifest["status"] == "succeeded" and manifest["rows"] == 3 and manifest["suppressed_cells"] == 2
    record = read(s3, CLEAN, f"reports/analysis_requests/{rid}.json")
    assert record["status"] == "succeeded" and record["purpose"] == "점검"


def test_request_ids_count_up(ready):
    _, mods = ready
    mods["analyze"].athena = FakeAthena(rows(("sigungu", "crisis_type", "households", "linked")))
    first = mods["analyze"].handler(REQUEST, Context())["request_id"]
    second = mods["analyze"].handler(REQUEST, Context())["request_id"]
    assert int(second[-4:]) == int(first[-4:]) + 1


@pytest.mark.parametrize("change, error", [
    ({"scenario": "drop_table"}, "unknown_scenario"),
    ({"params": {"from": "2026-05"}}, "invalid_params"),
    ({"params": {"from": "2026-05", "to": "2026-10", "sigungu": "' OR 1=1 --"}}, "invalid_params"),
    ({"run_id": "20261101-01"}, "run_not_ready"),
    ({"run_id": "x' OR '1'='1"}, "run_not_ready"),
    ({"purpose": ""}, "invalid_params"),
])
def test_bad_requests_start_nothing(ready, change, error):
    s3, mods = ready
    mods["analyze"].athena = fake = FakeAthena()
    assert mods["analyze"].handler({**REQUEST, **change}, Context())["error"] == error
    assert fake.started == [] and not any(k.startswith("results/requests/") for k in keys(s3, CLEAN))


@pytest.mark.parametrize("athena, error", [
    (FakeAthena(state="FAILED"), "query_failed: FAILED"),
    (FakeAthena(fail=True), "query_failed: InvalidRequestException"),
])
def test_failed_query_is_recorded(ready, athena, error):
    s3, mods = ready
    mods["analyze"].athena = athena
    out = mods["analyze"].handler(REQUEST, Context())
    assert out["status"] == "failed"
    rid = out["request_id"]
    assert read(s3, CLEAN, f"results/requests/{rid}/manifest.json")["error"] == error
    assert read(s3, CLEAN, f"reports/analysis_requests/{rid}.json")["status"] == "failed"
    assert f"results/requests/{rid}/result.csv" not in keys(s3, CLEAN)
