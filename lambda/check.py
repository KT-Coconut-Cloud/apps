"""Checks an exported run against export_record.json and starts the Macie job."""

import hashlib
import logging
import os
import re

import boto3

from common import env, get_json, s3

log = logging.getLogger()
log.setLevel(logging.INFO)

EXPORT_KEY = re.compile(r"^run_id=(\d{8}-\d{2})/export_record\.json$")
REPORTS = ("adequacy_review.json", "export_record.json")
JOB_PREFIX = "pii-"

macie = boto3.client("macie2")


def inspect(bucket: str, key: str) -> tuple[str | None, str, int]:
    """VersionId, sha256 and data row count of one object."""
    obj = s3.get_object(Bucket=bucket, Key=key)
    digest, lines = hashlib.sha256(), 0
    for chunk in obj["Body"].iter_chunks():
        digest.update(chunk)
        lines += chunk.count(b"\n")
    return obj.get("VersionId"), digest.hexdigest(), max(lines - 1, 0)


def start_macie_job(run_id: str, account_id: str) -> str:
    identifiers = [i for i in env("MACIE_CUSTOM_IDENTIFIER_IDS").split(",") if i]
    # tokens are hex, so some of them look like phone numbers to the regex
    allow_lists = [i for i in os.environ.get("MACIE_ALLOW_LIST_IDS", "").split(",") if i]
    terms = [
        {"simpleScopeTerm": {"comparator": "STARTS_WITH", "key": "OBJECT_KEY", "values": [f"run_id={run_id}/"]}},
        {"simpleScopeTerm": {"comparator": "EQ", "key": "OBJECT_EXTENSION", "values": ["csv"]}},
    ]
    resp = macie.create_classification_job(
        name=f"{JOB_PREFIX}{run_id}",
        jobType="ONE_TIME",
        clientToken=run_id,  # a retried execution must not start a second job
        customDataIdentifierIds=identifiers,
        allowListIds=allow_lists,
        managedDataIdentifierSelector="RECOMMENDED",
        s3JobDefinition={
            "bucketDefinitions": [{"accountId": account_id, "buckets": [env("LANDING_BUCKET")]}],
            "scoping": {"includes": {"and": terms}},
        },
    )
    return resp["jobId"]


def handler(event, context):
    detail = event["detail"]
    bucket, key = detail["bucket"]["name"], detail["object"]["key"]
    m = EXPORT_KEY.match(key)
    if bucket != env("LANDING_BUCKET") or not m:
        raise ValueError(f"unexpected object {bucket}/{key}")
    run_id = m.group(1)

    for name in REPORTS:
        src = f"run_id={run_id}/{name}"
        try:
            s3.copy_object(Bucket=env("CLEAN_BUCKET"), Key=f"reports/{src}", CopySource={"Bucket": bucket, "Key": src})
        except s3.exceptions.NoSuchKey:
            log.warning("missing %s", src)

    export = get_json(bucket, key) or {}
    if export.get("status") != "exported" or not export.get("files"):
        log.info("run %s was not exported, nothing to scan", run_id)
        return {"run_id": run_id, "action": "skip"}

    files, problems = [], []
    for item in export["files"]:
        entry = {"key": item["key"], "version_id": None}
        files.append(entry)
        if not item["key"].startswith(f"run_id={run_id}/"):
            problems.append(f"{item['key']}: outside the run folder")
            continue
        try:
            entry["version_id"], sha, rows = inspect(bucket, item["key"])
        except s3.exceptions.NoSuchKey:
            problems.append(f"{item['key']}: missing")
            continue
        if sha != item["sha256"]:
            problems.append(f"{item['key']}: sha256 mismatch")
        if rows != item["rows"]:
            problems.append(f"{item['key']}: {rows} rows, expected {item['rows']}")

    if problems:
        log.warning("run %s: %s", run_id, "; ".join(problems))
        return {"run_id": run_id, "action": "error", "files": files, "error": "; ".join(problems)}

    account_id = context.invoked_function_arn.split(":")[4]
    job_id = start_macie_job(run_id, account_id)
    log.info("run %s: macie job %s", run_id, job_id)
    return {"run_id": run_id, "action": "scan", "job_id": job_id, "files": files}
