"""Saves result.csv when an analysis query ends (EventBridge "Athena Query State Change")."""

import csv
import io
import logging
import re

import boto3

from catalog import CATALOG
from common import env, get_json, now, put_json, s3

log = logging.getLogger()
log.setLevel(logging.INFO)

REQUEST_LINE = re.compile(r"^-- request_id=(req-\d{8}-\d{4})\n")
DONE = ("SUCCEEDED", "FAILED", "CANCELLED")

athena = boto3.client("athena")


def fetch(query_id: str) -> list[list[str]]:
    rows = []
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=query_id):
        rows += [[d.get("VarCharValue", "") for d in r["Data"]] for r in page["ResultSet"]["Rows"]]
    return rows


def publish(request: dict, query_id: str) -> dict:
    scenario = CATALOG[request["scenario"]]
    rows = fetch(query_id)
    header, body = rows[0], rows[1:]
    # small cells are already NULL in the query output
    hidden_cols = [header.index(c) for c in (*scenario.counts, *scenario.derived)]
    hidden = sum(1 for r in body for i in hidden_cols if r[i] == "")

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(body)
    s3.put_object(
        Bucket=env("CLEAN_BUCKET"),
        Key=f"results/requests/{request['request_id']}/result.csv",
        Body=out.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    return {"status": "succeeded", "rows": len(body), "suppressed_cells": hidden, "error": None}


def handler(event, context):
    detail = event.get("detail") or {}
    state = detail.get("currentState")
    if state not in DONE or detail.get("workgroupName") != env("ATHENA_WORKGROUP"):
        return None

    query_id = detail["queryExecutionId"]
    query = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Query"]
    m = REQUEST_LINE.match(query)
    if not m:
        return None  # run by hand in the console, not from the app
    request_id = m.group(1)

    bucket = env("CLEAN_BUCKET")
    base = f"results/requests/{request_id}/"
    request = get_json(bucket, base + "request.json")
    if request is None or get_json(bucket, base + "manifest.json"):
        return None

    result = {"status": "failed", "rows": 0, "suppressed_cells": 0, "error": f"query_failed: {state}"}
    if state == "SUCCEEDED":
        try:
            result = publish(request, query_id)
        except Exception as e:
            log.exception("could not publish %s", request_id)
            result["error"] = f"publish_failed: {type(e).__name__}"

    finished = {**result, "finished_at": now().isoformat()}
    record_key = f"reports/analysis_requests/{request_id}.json"
    record = get_json(bucket, record_key) or {**request, "status": "running"}
    put_json(bucket, record_key, {**record, **finished})
    # written last: the app treats the request as finished once this exists
    manifest = {k: request[k] for k in ("request_id", "run_id", "scenario", "params")}
    put_json(bucket, base + "manifest.json", {**manifest, **finished})
    log.info("request %s: %s", request_id, result["status"])
    return {"request_id": request_id, **result}
