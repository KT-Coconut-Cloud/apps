import json

import boto3
import pytest
from moto import mock_aws

from pipeline.__main__ import main
from tests.conftest import RAW, RULES, SCHEMA


def events(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


@pytest.fixture
def common(tmp_path):
    return ["--rules", str(RULES), "--schema", str(SCHEMA), "--work", str(tmp_path)]


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "ap-northeast-2"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="landing",
                                         CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield


def test_each_stage_logs_one_event(common, capsys, monkeypatch, aws):
    monkeypatch.setenv("RUN_ID", "20261120-01")
    monkeypatch.setenv("PII_HMAC_KEY", "local")
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert main(common + ["pseudonymize", "--source-dir", str(RAW)]) == 0
    assert main(common + ["review"]) == 0
    assert main(common + ["export", "--bucket", "landing"]) == 0
    got = [{k: e[k] for k in ("run_id", "stage", "status", "count")} for e in events(capsys)]
    assert got == [
        {"run_id": "20261120-01", "stage": "pseudonymize", "status": "success", "count": 6},
        {"run_id": "20261120-01", "stage": "review", "status": "success", "count": 6},
        {"run_id": "20261120-01", "stage": "export", "status": "success", "count": 6},
    ]


def test_failures_are_logged(common, capsys, monkeypatch, aws, tmp_path):
    monkeypatch.setenv("RUN_ID", "20261120-02")
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("PII_HMAC_KEY", raising=False)
    assert main(common + ["pseudonymize", "--source-dir", str(RAW)]) == 1

    monkeypatch.setenv("PII_HMAC_KEY", "local")
    assert main(common + ["pseudonymize", "--source-dir", str(RAW)]) == 0
    out = tmp_path / "out" / "livelihood_payment.csv"
    out.write_text(out.read_text(encoding="utf-8-sig").replace("서울특별시", "010-1234-5678"), encoding="utf-8-sig")
    assert main(common + ["review"]) == 0
    assert main(common + ["export", "--bucket", "landing"]) == 2
    got = [(e["stage"], e["status"]) for e in events(capsys)]
    assert got == [("pseudonymize", "failed"), ("pseudonymize", "success"), ("review", "failed"), ("export", "failed")]


def test_event_has_no_row_values(common, capsys, monkeypatch):
    monkeypatch.setenv("RUN_ID", "20261120-03")
    monkeypatch.setenv("PII_HMAC_KEY", "local")
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    main(common + ["pseudonymize", "--source-dir", str(RAW)])
    out = capsys.readouterr().out
    assert "홍길동" not in out and "010-0000" not in out and "vault:v1:" not in out
