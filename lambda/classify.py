"""Moves a scanned run to the clean or quarantine bucket and writes macie_result.json."""

import logging
import os

import boto3

from common import env, get_json, now, put_json, s3

log = logging.getLogger()
log.setLevel(logging.INFO)

macie = boto3.client("macie2")
sns = boto3.client("sns")


def detected_types(job_id: str) -> dict[str, set[str]]:
    """Object key -> identifier types Macie found in it."""
    ids, token = [], None
    criteria = {"criterion": {"classificationDetails.jobId": {"eq": [job_id]}}}
    while True:
        page = macie.list_findings(findingCriteria=criteria, maxResults=50, **({"nextToken": token} if token else {}))
        ids += page.get("findingIds", [])
        token = page.get("nextToken")
        if not token:
            break

    found: dict[str, set[str]] = {}
    for i in range(0, len(ids), 50):
        for finding in macie.get_findings(findingIds=ids[i:i + 50])["findings"]:
            key = finding["resourcesAffected"]["s3Object"]["key"]
            result = (finding.get("classificationDetails") or {}).get("result") or {}
            types = found.setdefault(key, set())
            for group in result.get("sensitiveData") or []:
                types.update(d["type"] for d in group.get("detections") or [])
            for d in (result.get("customDataIdentifiers") or {}).get("detections") or []:
                types.add(d["name"])
    return found


def clean_key(run_id: str, key: str) -> str:
    # one folder per table so each Athena table has its own location
    name = key.rsplit("/", 1)[1]
    return f"data/{name.removesuffix('.csv')}/run_id={run_id}/{name}"


def move(run_id: str, item: dict, passed: bool) -> None:
    source = {"Bucket": env("LANDING_BUCKET"), "Key": item["key"]}
    if item.get("version_id"):
        # the version that was hashed and scanned, not whatever is there now
        source["VersionId"] = item["version_id"]
    if passed:
        target = (env("CLEAN_BUCKET"), clean_key(run_id, item["key"]))
    else:
        target = (env("QUARANTINE_BUCKET"), item["key"])
    try:
        s3.copy_object(Bucket=target[0], Key=target[1], CopySource=source)
    except s3.exceptions.NoSuchKey:
        log.warning("missing %s", item["key"])
        return
    s3.delete_object(Bucket=env("LANDING_BUCKET"), Key=item["key"])


def alert(result: dict) -> None:
    topic = os.environ.get("ALERT_TOPIC_ARN")
    if not topic:
        return
    counts = {}
    for f in result["files"]:
        for t in f["types"]:
            counts[t] = counts.get(t, 0) + 1
    lines = [f"run_id: {result['run_id']}", f"verdict: {result['verdict']}"]
    if counts:
        lines.append("detected: " + ", ".join(f"{t} ({n} file)" for t, n in sorted(counts.items())))
    if result.get("error"):
        lines.append(f"error: {result['error']}")
    sns.publish(TopicArn=topic, Subject=f"[pii] {result['verdict']} {result['run_id']}", Message="\n".join(lines))


def handler(event, context):
    run_id, files = event["run_id"], event["files"]
    clean = env("CLEAN_BUCKET")
    reports = f"reports/run_id={run_id}/"
    if get_json(clean, reports + "macie_result.json"):
        log.info("run %s already classified", run_id)
        return {"run_id": run_id, "verdict": "SKIPPED"}

    found, error = {}, event.get("error")
    macie_status = (event.get("macie") or {}).get("status")
    if event["action"] == "scan":
        if macie_status == "COMPLETE":
            found = detected_types(event["job_id"])
        else:
            error = f"macie job {macie_status}"

    if error:
        verdict = "ERROR"
    else:
        verdict = "FAIL" if any(found.values()) else "PASS"

    result_files = []
    for item in files:
        types = sorted(found.get(item["key"], ()))
        result_files.append({
            "key": item["key"],
            "detected": bool(types),
            "types": types,
            "classification": "clean" if verdict == "PASS" else "quarantine",
        })
        # one bad file holds back the whole run
        move(run_id, item, verdict == "PASS")

    at = now().isoformat()
    result = {
        "run_id": run_id,
        "scanned_at": at,
        "verdict": verdict,
        "job_id": event.get("job_id"),
        "error": error,
        "files": result_files,
    }
    put_json(clean, reports + "macie_result.json", result)
    if verdict == "PASS":
        put_json(clean, f"results/run_id={run_id}/manifest.json", {
            "run_id": run_id,
            "generated_at": at,
            "adequacy_passed": True,
            "tables": [f["key"].rsplit("/", 1)[1].removesuffix(".csv") for f in files],
        })
    else:
        alert(result)
    log.info("run %s: %s", run_id, verdict)
    return {"run_id": run_id, "verdict": verdict}
