"""Adequacy review: read the written export file again and run the output checks on it."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline import validate
from pipeline.rules import Rules, Table

KST = timezone(timedelta(hours=9))


def read_output(out_dir: Path, table: Table) -> tuple[list[str], list[dict]]:
    o = table.output
    with (Path(out_dir) / table.filename).open(encoding=o.get("encoding", "utf-8"), newline="") as f:
        reader = csv.DictReader(f, delimiter=o.get("delimiter", ","), quotechar=o.get("quotechar", '"'))
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def run(rules: Rules, out_dir: Path, run_id: str) -> dict:
    found = {item: [] for item in validate.ITEMS}
    rows_total = 0
    for table in rules.tables.values():
        header, rows = read_output(out_dir, table)
        rows_total += len(rows)
        if table.validation.get("preserve_row_count") and not rows:
            found["completeness"].append(f"{table.name}: 출력 행 없음")
        for item, problems in validate.output_checks(table, header, rows).items():
            found[item] += problems

    checks = [
        {
            "item": item,
            "passed": not problems,
            "value": len(problems),
            # first problem only; the rest are in the job log
            "reason": problems[0] if problems else None,
        }
        for item, problems in found.items()
    ]
    return {
        "run_id": run_id,
        "reviewed_at": datetime.now(KST).replace(microsecond=0).isoformat(),
        "rules_version": f"{rules.scenario} v{rules.version}",
        "rows": rows_total,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "problems": [p for ps in found.values() for p in ps],
    }
