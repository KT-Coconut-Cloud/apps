"""Checks from the rules' validation section. Messages carry counts, never row values (report_row_values: false)."""

import re

from pipeline.rules import Table

# item names the result app shows on the security page
ITEMS = ("direct_identifier", "tokenization", "generalization", "completeness")


def _count(rows, pred) -> int:
    return sum(1 for r in rows if pred(r))


def check_direct_identifier(table: Table, header: list[str], rows: list[dict]) -> list[str]:
    v, problems = table.validation, []
    if v.get("exact_output_columns") and header != list(table.output_columns):
        problems.append(f"{table.name}: 출력 컬럼이 규칙과 다름")
    forbidden = [c for c in header if c in v.get("forbidden_columns", [])]
    if forbidden:
        problems.append(f"{table.name}: 반출 금지 컬럼 {forbidden}")
    scan = header if v.get("pii_scan_columns", "all") == "all" else [c for c in v["pii_scan_columns"] if c in header]
    for label, pattern in v.get("pii_patterns", {}).items():
        p = re.compile(pattern)
        for col in scan:
            n = _count(rows, lambda r: p.search(r[col] or ""))
            if n:
                problems.append(f"{table.name}.{col}: {label} 형식 {n}건")
    return problems


def check_tokenization(table: Table, header: list[str], rows: list[dict]) -> list[str]:
    v, problems = table.validation, []
    if v.get("token_pattern"):
        p = re.compile(v["token_pattern"])
        for col in table.token_columns:
            if col.name in header:
                n = _count(rows, lambda r: not p.fullmatch(r[col.name] or ""))
                if n:
                    problems.append(f"{table.name}.{col.name}: 토큰 형식이 아닌 값 {n}건")
    for col in v.get("unique_columns", []):
        if col in header:
            values = [r[col] for r in rows]
            dup = len(values) - len(set(values))
            if dup:
                problems.append(f"{table.name}.{col}: 중복 값 {dup}건")
    return problems


def check_generalization(table: Table, header: list[str], rows: list[dict]) -> list[str]:
    v, problems = table.validation, []
    allowed = {}
    for col in table.columns:
        if col.action == "keep" and col.get("allowed_values"):
            allowed[col.name] = set(col.get("allowed_values"))
        if col.action == "generalize" and col.get("method") == "leading_sido_name":
            allowed[col.name] = set(col.get("allowed_values"))
        if col.action == "generalize" and col.get("allowed_output_values"):
            allowed[col.name] = set(col.get("allowed_output_values"))
    if v.get("income_band_values"):
        for d in table.derived:
            allowed[d.name] = set(v["income_band_values"])
    for name, values in allowed.items():
        if name in header:
            n = _count(rows, lambda r: r[name] not in values)
            if n:
                problems.append(f"{table.name}.{name}: 허용되지 않은 값 {n}건")

    patterns = {k.removesuffix("_pattern"): p for k, p in v.items() if k.endswith("_pattern") and k != "token_pattern"}
    for col in table.columns:
        if col.action == "keep" and col.get("pattern"):
            patterns.setdefault(col.name, col.get("pattern"))
    for name, pattern in patterns.items():
        if name in header:
            p = re.compile(pattern)
            n = _count(rows, lambda r: not p.fullmatch(r[name] or ""))
            if n:
                problems.append(f"{table.name}.{name}: 일반화 형식이 아닌 값 {n}건")
    return problems


def check_completeness(table: Table, header: list[str], rows: list[dict]) -> list[str]:
    if not table.validation.get("no_empty_output_values"):
        return []
    problems = []
    for col in header:
        n = _count(rows, lambda r: (r[col] or "") == "")
        if n:
            problems.append(f"{table.name}.{col}: 빈 값 {n}건")
    return problems


OUTPUT_CHECKS = {
    "direct_identifier": check_direct_identifier,
    "tokenization": check_tokenization,
    "generalization": check_generalization,
    "completeness": check_completeness,
}


def output_checks(table: Table, header: list[str], rows: list[dict]) -> dict[str, list[str]]:
    """Checks that need only the output file. The review step runs these again on what was written."""
    return {item: fn(table, header, rows) for item, fn in OUTPUT_CHECKS.items()}


def input_checks(table: Table, out: list[dict], rows: list[dict]) -> list[str]:
    """Checks that compare the output with the input. Only the pseudonymize step has the input."""
    v, problems = table.validation, []
    if v.get("preserve_row_count") and len(out) != len(rows):
        problems.append(f"{table.name}: 행 수가 다름 (입력 {len(rows)}, 출력 {len(out)})")
        return problems

    src = v.get("consistent_token_source")
    if src:
        col = table.column(src)
        forward, backward = {}, {}
        for o, r in zip(out, rows):
            forward.setdefault(r[src], set()).add(o[col.name])
            backward.setdefault(o[col.name], set()).add(r[src])
        split = sum(1 for t in forward.values() if len(t) > 1)
        merged = sum(1 for s in backward.values() if len(s) > 1)
        if split or merged:
            problems.append(f"{table.name}.{col.name}: 같은 {src}에 다른 토큰 {split}건, 다른 {src}에 같은 토큰 {merged}건")

    if v.get("check_transformation_against_input"):
        for col in table.columns:
            if col.action == "keep":
                n = sum(1 for o, r in zip(out, rows) if o[col.name] != r[col.source])
                if n:
                    problems.append(f"{table.name}.{col.name}: 입력과 다른 값 {n}건")
            elif col.action == "tokenize":
                n = sum(1 for o, r in zip(out, rows) if o[col.name] == r[col.source])
                if n:
                    problems.append(f"{table.name}.{col.name}: 원본 값이 그대로 남은 행 {n}건")
    return problems


def all_checks(table: Table, out: list[dict], rows: list[dict]) -> list[str]:
    header = list(out[0]) if out else list(table.output_columns)
    problems = [p for ps in output_checks(table, header, out).values() for p in ps]
    return problems + input_checks(table, out, rows)
