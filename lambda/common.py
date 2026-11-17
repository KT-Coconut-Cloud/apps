import json
import os
import re
from datetime import datetime, timedelta, timezone

import boto3

KST = timezone(timedelta(hours=9))
RUN_ID = re.compile(r"^\d{8}-\d{2}$")

s3 = boto3.client("s3")


def env(name: str) -> str:
    return os.environ[name]


def now() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


def get_json(bucket: str, key: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def put_json(bucket: str, key: str, data: dict, **extra) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json", **extra)
