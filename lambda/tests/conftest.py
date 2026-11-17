import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LANDING, CLEAN, QUARANTINE = "landing", "clean", "quarantine"
MODULES = ["common", "catalog", "check", "classify", "analyze", "finalize"]


class Context:
    invoked_function_arn = "arn:aws:lambda:ap-northeast-2:123456789012:function:test"

    def get_remaining_time_in_millis(self):
        return 60_000


@pytest.fixture
def aws(monkeypatch):
    env = {
        "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "ap-northeast-2",
        "LANDING_BUCKET": LANDING, "CLEAN_BUCKET": CLEAN, "QUARANTINE_BUCKET": QUARANTINE,
        "MACIE_CUSTOM_IDENTIFIER_IDS": "cdi-1,cdi-2",
        "ATHENA_DATABASE": "pii", "ATHENA_WORKGROUP": "analysis",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        s3 = boto3.client("s3")
        for bucket in (LANDING, CLEAN, QUARANTINE):
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        s3.put_bucket_versioning(Bucket=LANDING, VersioningConfiguration={"Status": "Enabled"})
        # the handlers create their clients at import time
        mods = {name: importlib.reload(importlib.import_module(name)) for name in MODULES}
        yield s3, mods


def put(s3, bucket, key, data):
    body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body)


def read(s3, bucket, key):
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def keys(s3, bucket):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", []))
