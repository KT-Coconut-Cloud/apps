import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from pipeline.review import KST
from pipeline.rules import Rules

log = logging.getLogger("export")


def _put_json(s3, bucket: str, key: str, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def run(rules: Rules, out_dir: Path, review: dict, bucket: str, s3) -> dict:
    """Upload a run to the landing bucket. export_record.json goes last since it starts the AWS side."""
    run_id = review["run_id"]
    base = f"run_id={run_id}/"
    files = []

    if review["passed"]:
        for table in rules.tables.values():
            body = (Path(out_dir) / table.filename).read_bytes()
            key = base + table.filename
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="text/csv")
            #CSV 전체 개행 수에서 헤더 1행을 제외해 데이터 행 수 계산. 마지막 개행이 없는 CSV의 행 수는 별도 확인 필
            files.append({"key": key, "rows": max(body.count(b"\n") - 1, 0), "sha256": hashlib.sha256(body).hexdigest()})
            log.info("uploaded %s", key)
    else:
        log.warning("run %s blocked by adequacy review, no data uploaded", run_id)

    record = {
        "run_id": run_id,
        "executed_at": datetime.now(KST).replace(microsecond=0).isoformat(),
        "status": "exported" if review["passed"] else "aborted",
        "files": files,
    }
    _put_json(s3, bucket, base + "adequacy_review.json", review)
    _put_json(s3, bucket, base + "export_record.json", record)
    return record
