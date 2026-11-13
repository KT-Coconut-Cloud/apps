import io
import json

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings
from app.local_lambda import LocalLambda
from app.main import create_app
from tests.conftest import login

BUCKET = "clean-bucket"
CRISIS = {"run_id": "20261112-01", "scenario": "crisis_link_rate", "from": "2026-05", "to": "2026-10", "purpose": "점검"}


class FakeLambda:
    """Answers invoke() like analysis-request, using the local implementation."""

    def __init__(self, lam: LocalLambda):
        self.lam = lam
        self.calls = []

    def invoke(self, FunctionName, Payload):
        payload = json.loads(Payload)
        self.calls.append((FunctionName, payload))
        return {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(self.lam.submit(payload)).encode())}


def upload(data_dir):
    s3 = boto3.client("s3", region_name="ap-northeast-2")
    for path in data_dir.rglob("*"):
        key = path.relative_to(data_dir).as_posix()
        if path.is_file() and not key.startswith("data/"):
            s3.put_object(Bucket=BUCKET, Key=key, Body=path.read_bytes())


@pytest.fixture
def s3_client(settings, data_dir, monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "ap-northeast-2"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3", region_name="ap-northeast-2").create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
        )
        upload(data_dir)
        s = settings.model_copy(update={"data_source": "s3", "s3_bucket": BUCKET, "analysis_backend": "lambda"})
        app = create_app(s)

        writes = []
        for store in (app.state.results, app.state.reports):
            store.client.meta.events.register("before-call.s3.PutObject", lambda **kw: writes.append(kw))
            store.client.meta.events.register("before-call.s3.DeleteObject", lambda **kw: writes.append(kw))

        fake = FakeLambda(LocalLambda(data_dir))
        app.state.analysis.client = fake
        yield TestClient(app), fake, writes


def test_s3_mode_needs_bucket():
    with pytest.raises(ValueError):
        Settings(data_source="s3", analysis_backend="lambda")
    with pytest.raises(ValueError):
        Settings(data_source="s3", s3_bucket="b", analysis_backend="local")


def test_security_pages_read_bucket(s3_client):
    client, _, writes = s3_client
    login(client, "security01", "pw-security")
    assert client.get("/security/runs").text.count("반출 완료") >= 2
    assert "k-익명성" in client.get("/security/runs/20261111-01").text
    assert writes == []


def test_request_goes_through_lambda_and_result_is_read_from_bucket(s3_client, data_dir):
    client, fake, writes = s3_client
    login(client, "policy01", "pw-policy")
    assert "20261112-01" in client.get("/policy/datasets").text

    url = client.post("/policy/analyses", data=CRISIS, follow_redirects=False).headers["location"]
    name, payload = fake.calls[0]
    assert name == "analysis-request"
    assert payload["requested_by"] == "policy01" and payload["params"]["sigungu"] is None

    # nothing in the bucket yet, the request is not visible
    assert client.get(url).status_code == 404

    upload(data_dir)
    text = client.get(url).text
    assert "시군구, 위기정보 유형별 연계 현황" in text
    assert url.rsplit("/", 1)[1] in client.get("/policy/analyses").text
    assert writes == []


def test_lambda_error_shows_message(s3_client):
    client, fake, _ = s3_client
    fake.lam.submit = lambda payload: {"error": "run_not_ready", "detail": "x"}
    login(client, "policy01", "pw-policy")
    res = client.post("/policy/analyses", data=CRISIS)
    assert res.status_code == 422 and "분석에 쓸 수 없습니다" in res.text
