import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.patterns import GENERALIZED, IDENTIFIERS, TOKEN
from pipeline.rules import Rules

KST = timezone(timedelta(hours=9))


def read_output(out_dir: Path, table: str) -> tuple[list[str], list[dict]]:
    with (Path(out_dir) / f"{table}.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def check_direct_identifier(rules: Rules, data: dict) -> dict:
    count, reason = 0, None

    def hit(n: int, message: str):
        nonlocal count, reason
        count += n
        reason = reason or message

    for table in rules.tables.values():
        header, rows = data[table.name]
        allowed = {c.name for c in table.output}
        for name in header:
            if name not in allowed:
                hit(1, f"{table.name}.{name} 컬럼이 삭제되지 않음")
        for col in table.token_columns:
            if col not in header:
                continue
            bad = sum(1 for r in rows if not TOKEN.match(r[col] or ""))
            if bad:
                hit(bad, f"{table.name}.{col}에 토큰화되지 않은 값 {bad}건")
        for name in header:
            for label, pattern in IDENTIFIERS.items():
                found = sum(1 for r in rows if pattern.search(r[name] or ""))
                if found:
                    hit(found, f"{table.name}.{name}에서 {label} 형식 {found}건")
    return {"item": "direct_identifier", "passed": count == 0, "value": count, "reason": reason}


def check_generalization(rules: Rules, data: dict) -> dict:
    applied, reason = [], None
    for table in rules.tables.values():
        header, rows = data[table.name]
        for col in table.output:
            if col.action != "generalize" or col.name not in header:
                continue
            pattern, label = GENERALIZED[col.method]
            applied.append(f"{col.source} {label}")
            bad = sum(1 for r in rows if r[col.name] and not pattern.match(r[col.name]))
            if bad:
                reason = reason or f"{table.name}.{col.name}에 {label} 단위가 아닌 값 {bad}건"
    return {
        "item": "generalization",
        "passed": reason is None,
        "value": ", ".join(applied) if applied else "대상 없음",
        "reason": reason,
    }


def check_k_anonymity(rules: Rules, data: dict) -> dict:
    lowest = None  # (k, table, group)
    for table in rules.tables.values():
        if not table.quasi_identifiers:
            continue
        header, rows = data[table.name]
        groups = defaultdict(set)
        for i, r in enumerate(rows):
            # count people, not rows, when the table has a token column
            person = r[table.token_column] if table.token_column in header else i
            groups[tuple(r[q] for q in table.quasi_identifiers)].add(person)
        for group, people in groups.items():
            if lowest is None or len(people) < lowest[0]:
                lowest = (len(people), table.name, group)

    if lowest is None:
        return {"item": "k_anonymity", "passed": False, "value": None,
                "reason": "quasi_identifiers가 지정된 테이블이 없음"}
    k, table, group = lowest
    passed = k >= rules.k_threshold
    reason = None if passed else f"최소 k={k}, 기준 {rules.k_threshold} 미만 ({table}: {' '.join(group)})"
    return {"item": "k_anonymity", "passed": passed, "value": k, "reason": reason}


def run(rules: Rules, out_dir: Path, run_id: str) -> dict:
    data = {name: read_output(out_dir, name) for name in rules.tables}
    checks = [check_direct_identifier(rules, data), check_generalization(rules, data), check_k_anonymity(rules, data)]
    return {
        "run_id": run_id,
        "reviewed_at": datetime.now(KST).replace(microsecond=0).isoformat(),
        "rules_version": rules.version,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
    }
