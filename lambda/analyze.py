"""Validates an analysis request from the result app and starts the Athena query."""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from catalog import CATALOG, TABLE, InvalidParams, build_query, clean_params, supports
from common import RUN_ID, env, get_json, now, put_json, s3

log = logging.getLogger()
log.setLevel(logging.INFO)

athena = boto3.client("athena")


def export_header(bucket: str, run_id: str) -> list[str] | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"data/{TABLE}/run_id={run_id}/{TABLE}.csv", Range="bytes=0-4095")
    except s3.exceptions.NoSuchKey:
        return None
    first = obj["Body"].read().decode("utf-8", errors="ignore").splitlines()[:1]
    return [c.strip().lstrip("\ufeff") for c in first[0].split(",")] if first else None


def claim_request_id(bucket: str, request: dict) -> str:
    """Write request.json under the next free id for today."""
    day = now().strftime("%Y%m%d")
    prefix = f"results/requests/req-{day}-"
    used = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        used += [int(p["Prefix"].rstrip("/")[-4:]) for p in page.get("CommonPrefixes", [])]
    number = max(used, default=0)
    for _ in range(10):
        number += 1
        request_id = f"req-{day}-{number:04d}"
        try:
            # fails if another invocation took the same id first
            put_json(bucket, f"results/requests/{request_id}/request.json",
                     {"request_id": request_id, **request}, IfNoneMatch="*")
            return request_id
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise
    raise RuntimeError("could not allocate a request id")


def handler(event, context):
    bucket = env("CLEAN_BUCKET")
    scenario = CATALOG.get(event.get("scenario"))
    if scenario is None:
        return {"error": "unknown_scenario", "detail": str(event.get("scenario"))}
    try:
        params = clean_params(scenario, event.get("params") or {})
    except InvalidParams as e:
        return {"error": "invalid_params", "detail": str(e)}

    run_id = event.get("run_id") or ""
    manifest = get_json(bucket, f"results/run_id={run_id}/manifest.json") if RUN_ID.match(run_id) else None
    if not manifest or not manifest.get("adequacy_passed"):
        return {"error": "run_not_ready", "detail": run_id}
    if not supports(scenario, export_header(bucket, run_id)):
        return {"error": "template_unavailable", "detail": scenario.key}

    purpose = (event.get("purpose") or "").strip()
    requested_by = event.get("requested_by")
    if not requested_by or not purpose or len(purpose) > 200:
        return {"error": "invalid_params", "detail": "requested_by, purpose"}

    request = {
        "run_id": run_id,
        "scenario": scenario.key,
        "params": params,
        "purpose": purpose,
        "requested_by": requested_by,
        "requested_at": now().isoformat(),
    }
    request_id = claim_request_id(bucket, request)
    request = {"request_id": request_id, **request}
    record_key = f"reports/analysis_requests/{request_id}.json"
    put_json(bucket, record_key, {**request, "status": "running"})

    sql, args = build_query(scenario, run_id, params, int(os.environ.get("MIN_CELL_SIZE", "5")))
    try:
        athena.start_query_execution(
            # analysis-finalize reads the request id back from this line
            QueryString=f"-- request_id={request_id}\n{sql}",
            ExecutionParameters=args,
            QueryExecutionContext={"Database": env("ATHENA_DATABASE")},
            WorkGroup=env("ATHENA_WORKGROUP"),
        )
    except ClientError as e:
        log.exception("athena did not accept %s", request_id)
        failed = {"status": "failed", "rows": 0, "suppressed_cells": 0,
                  "error": f"query_failed: {e.response['Error']['Code']}", "finished_at": now().isoformat()}
        put_json(bucket, record_key, {**request, **failed})
        manifest = {k: request[k] for k in ("request_id", "run_id", "scenario", "params")}
        put_json(bucket, f"results/requests/{request_id}/manifest.json", {**manifest, **failed})
        return {"request_id": request_id, "status": "failed"}

    log.info("request %s started", request_id)
    return {"request_id": request_id, "status": "running"}
