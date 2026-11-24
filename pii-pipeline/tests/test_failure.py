import json

import boto3
import pytest
from moto import mock_aws

from pipeline import failure
from pipeline.__main__ import main
from tests.conftest import RAW, RULES, SCHEMA

BUCKET = "landing"
RUN = "20261124-91"


@pytest.fixture
def s3(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "ap-northeast-2"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield client


def stored(s3):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=f"run_id={RUN}/export_record.json")["Body"].read())


def test_pseudonymize_error_is_uploaded_without_values(tmp_path, s3):
    raw = tmp_path / "raw"
    raw.mkdir()
    src = (RAW / "benefit_review_joined.csv").read_text(encoding="utf-8-sig")
    lines = src.splitlines()
    lines[0] += ",memo"
    lines[1:] = [line + ",010-9999-0000" for line in lines[1:]]
    (raw / "benefit_review_joined.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()

    assert main(["--rules", str(RULES), "--schema", str(SCHEMA), "--work", str(work), "pseudonymize", "--source-dir", str(raw)]) == 1
    record = failure.run(work, RUN, "benefit_review v3.1", BUCKET, s3)

    saved = stored(s3)
    assert saved == record
    assert saved["status"] == "aborted" and saved["failed_stage"] == "pseudonymize" and saved["files"] == []
    assert "memo" in saved["reasons"][0]
    assert "010-9999-0000" not in json.dumps(saved, ensure_ascii=False)


def test_nothing_uploaded_once_review_exists(tmp_path, s3):
    (tmp_path / "adequacy_review.json").write_text("{}", encoding="utf-8")
    assert failure.run(tmp_path, RUN, "benefit_review v3.1", BUCKET, s3) is None
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)


def test_crash_without_note(tmp_path, s3):
    failure.run(tmp_path, RUN, "benefit_review v3.1", BUCKET, s3)
    assert stored(s3)["failed_stage"] == "pseudonymize"
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "livelihood_payment.csv").write_text("a\n", encoding="utf-8")
    failure.run(tmp_path, RUN, "benefit_review v3.1", BUCKET, s3)
    assert stored(s3)["failed_stage"] == "review"


def test_long_reasons_are_cut(tmp_path):
    failure.write_note(tmp_path, ["x" * 500] * 10)
    record = failure.build_record(tmp_path, RUN, "v")
    assert len(record["reasons"]) == failure.MAX_LINES
    assert all(len(r) == failure.MAX_CHARS for r in record["reasons"])
