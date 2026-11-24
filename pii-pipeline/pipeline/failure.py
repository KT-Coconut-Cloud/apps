"""Failure record for runs that stopped before the review was written.

The pseudonymize step has the source DB and Vault but no AWS key, so it only
leaves a note in the work volume. The workflow's exit handler, which has the
export key, uploads export_record.json from it. Reasons carry row numbers and
column names only, never values.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from pipeline.review import KST

log = logging.getLogger("failure")

NOTE = "pseudonymize_failure.json"
MAX_LINES = 6
MAX_CHARS = 200


def write_note(work: Path, reasons: list[str]) -> None:
    lines = [r[:MAX_CHARS] for r in reasons if r.strip()][:MAX_LINES]
    (Path(work) / NOTE).write_text(json.dumps({"stage": "pseudonymize", "reasons": lines}, ensure_ascii=False),
                                   encoding="utf-8")


def build_record(work: Path, run_id: str, rules_version: str) -> dict | None:
    """None when the review was written, since the export step already uploaded the reports."""
    work = Path(work)
    if (work / "adequacy_review.json").exists():
        return None
    note = work / NOTE
    if note.exists():
        data = json.loads(note.read_text(encoding="utf-8"))
        stage, reasons = data["stage"], data["reasons"]
    elif any((work / "out").glob("*.csv")):
        stage, reasons = "review", ["적정성 검토 단계가 결과를 남기지 못하고 종료됨"]
    else:
        stage, reasons = "pseudonymize", ["가명처리 단계가 비정상 종료됨"]
    return {
        "run_id": run_id,
        "executed_at": datetime.now(KST).replace(microsecond=0).isoformat(),
        "status": "aborted",
        "failed_stage": stage,
        "rules_version": rules_version,
        "reasons": reasons,
        "files": [],
    }


def run(work: Path, run_id: str, rules_version: str, bucket: str, s3) -> dict | None:
    record = build_record(work, run_id, rules_version)
    if record is None:
        log.info("run %s reached the review, nothing to report", run_id)
        return None
    body = json.dumps(record, ensure_ascii=False, indent=2).encode()
    s3.put_object(Bucket=bucket, Key=f"run_id={run_id}/export_record.json", Body=body,
                  ContentType="application/json")
    log.warning("run %s stopped at %s, failure record uploaded", run_id, record["failed_stage"])
    return record
