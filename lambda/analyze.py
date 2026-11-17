"""Runs a template query on Athena for the result app and saves result.csv."""

import csv
import io
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

from catalog import CATALOG, InvalidParams, build_query, clean_params
from common import RUN_ID, env, get_json, now, put_json, s3

log = logging.getLogger()
log.setLevel(logging.INFO)

athena = boto3.client("athena")
POLL_SECONDS = 1
DONE = ("SUCCEEDED", "FAILED", "CANCELLED")


def min_cell() -> int:
    return int(os.environ.get("MIN_CELL_SIZE", "5"))


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


def wait(query_id: str, context) -> str:
    while True:
        state = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]["State"]
        if state in DONE:
            return state
        if context.get_remaining_time_in_millis() < 10_000:
            athena.stop_query_execution(QueryExecutionId=query_id)
            return "TIMEOUT"
        time.sleep(POLL_SECONDS)


def fetch(query_id: str) -> list[list[str]]:
    rows = []
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=query_id):
        rows += [[d.get("VarCharValue", "") for d in r["Data"]] for r in page["ResultSet"]["Rows"]]
    return rows


def run_query(scenario, request: dict, context) -> tuple[dict, str | None]:
    sql, args = build_query(scenario, request["run_id"], request["params"], min_cell())
    try:
        query_id = athena.start_query_execution(
            QueryString=sql,
            ExecutionParameters=args,
            QueryExecutionContext={"Database": env("ATHENA_DATABASE")},
            WorkGroup=env("ATHENA_WORKGROUP"),
        )["QueryExecutionId"]
        state = wait(query_id, context)
        if state != "SUCCEEDED":
            return {"status": "failed", "rows": 0, "suppressed_cells": 0, "error": f"query_failed: {state}"}, None
        rows = fetch(query_id)
    except ClientError as e:
        log.exception("athena error for %s", request["request_id"])
        return {"status": "failed", "rows": 0, "suppressed_cells": 0,
                "error": f"query_failed: {e.response['Error']['Code']}"}, None

    header, body = rows[0], rows[1:]
    hidden_cols = [header.index(c) for c in (*scenario.counts, *scenario.derived)]
    hidden = sum(1 for r in body for i in hidden_cols if r[i] == "")
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(body)
    return {"status": "succeeded", "rows": len(body), "suppressed_cells": hidden, "error": None}, out.getvalue()


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

    result, text = run_query(scenario, request, context)
    base = f"results/requests/{request_id}/"
    if text is not None:
        s3.put_object(Bucket=bucket, Key=base + "result.csv", Body=text.encode("utf-8"), ContentType="text/csv")

    finished = {**result, "finished_at": now().isoformat()}
    put_json(bucket, record_key, {**request, **finished})
    # written last: the app treats the request as finished once this exists
    manifest = {k: request[k] for k in ("request_id", "run_id", "scenario", "params")}
    put_json(bucket, base + "manifest.json", {**manifest, **finished})
    log.info("request %s: %s", request_id, result["status"])
    return {"request_id": request_id, "status": result["status"]}
