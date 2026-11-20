import hashlib
import json

import boto3
import pytest
from moto import mock_aws

from pipeline import export, review

BUCKET = "landing"


@pytest.fixture
def s3(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "ap-northeast-2"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield client


def keys(s3):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def test_passed_run_uploads_data_and_reports(rules, out_dir, s3):
    result = review.run(rules, out_dir, "20261117-01")
    record = export.run(rules, out_dir, result, BUCKET, s3)

    assert keys(s3) == [
        "run_id=20261117-01/adequacy_review.json",
        "run_id=20261117-01/export_record.json",
        "run_id=20261117-01/livelihood_payment.csv",
    ]
    [f] = record["files"]
    body = s3.get_object(Bucket=BUCKET, Key=f["key"])["Body"].read()
    assert f["rows"] == 6 and f["sha256"] == hashlib.sha256(body).hexdigest()
    stored = json.loads(s3.get_object(Bucket=BUCKET, Key="run_id=20261117-01/export_record.json")["Body"].read())
    assert stored["status"] == "exported"


def test_blocked_run_uploads_only_the_reports(rules, out_dir, s3):
    result = review.run(rules, out_dir, "20261117-02")
    result["passed"] = False
    record = export.run(rules, out_dir, result, BUCKET, s3)
    assert record["status"] == "aborted" and record["files"] == []
    assert keys(s3) == ["run_id=20261117-02/adequacy_review.json", "run_id=20261117-02/export_record.json"]
