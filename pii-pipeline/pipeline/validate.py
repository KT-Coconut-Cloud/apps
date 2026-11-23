"""Checks from the rules' validation section. Messages carry counts, never row values (report_row_values: false)."""

import re

from pipeline.rules import Table

# item names the result app shows on the security page
ITEMS = ("direct_identifier", "tokenization", "generalization", "completeness")


def _record(problems, findings, message, code, column=None, indices=None, pattern=None):
    problems.append(message)
    if findings is not None:
        # Indices stay in memory only; never serialize them or source values.
        findings.append({"code": code, "column": column, "pattern": pattern,
                         "indices": None if indices is None else set(indices)})


def check_direct_identifier(table: Table, header: list[str], rows: list[dict], findings=None) -> list[str]:
    v, problems = table.validation, []
    if v.get("exact_output_columns") and header != list(table.output_columns):
        _record(problems, findings, f"{table.name}: 출력 컬럼이 규칙과 다름", "output_columns_mismatch")
    forbidden = [c for c in header if c in v.get("forbidden_columns", [])]
    if forbidden:
        _record(problems, findings, f"{table.name}: 반출 금지 컬럼 {forbidden}", "forbidden_columns")
    scan = header if v.get("pii_scan_columns", "all") == "all" else [c for c in v["pii_scan_columns"] if c in header]
    for label, pattern in v.get("pii_patterns", {}).items():
        p = re.compile(pattern)
        for col in scan:
            indices = {i for i, r in enumerate(rows) if p.search(r[col] or "")}
            n = len(indices)
            if n:
                _record(problems, findings, f"{table.name}.{col}: {label} 형식 {n}건",
                        "pii_pattern", col, indices, label)
    return problems


def check_tokenization(table: Table, header: list[str], rows: list[dict], findings=None) -> list[str]:
    v, problems = table.validation, []
    if v.get("token_pattern"):
        p = re.compile(v["token_pattern"])
        for col in table.token_columns:
            if col.name in header:
                indices = {i for i, r in enumerate(rows) if not p.fullmatch(r[col.name] or "")}
                n = len(indices)
                if n:
                    _record(problems, findings, f"{table.name}.{col.name}: 토큰 형식이 아닌 값 {n}건",
                            "invalid_token_format", col.name, indices)
    for col in v.get("unique_columns", []):
        if col in header:
            values = [r[col] for r in rows]
            dup = len(values) - len(set(values))
            if dup:
                groups = {}
                for i, value in enumerate(values):
                    groups.setdefault(value, []).append(i)
                indices = {i for group in groups.values() if len(group) > 1 for i in group}
                # Statistics count every row in a duplicate group, not just excess copies.
                _record(problems, findings, f"{table.name}.{col}: 중복 값 {dup}건",
                        "duplicate_value", col, indices)
    return problems


def check_generalization(table: Table, header: list[str], rows: list[dict], findings=None) -> list[str]:
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
            indices = {i for i, r in enumerate(rows) if r[name] not in values}
            n = len(indices)
            if n:
                _record(problems, findings, f"{table.name}.{name}: 허용되지 않은 값 {n}건",
                        "value_not_allowed", name, indices)

    patterns = {k.removesuffix("_pattern"): p for k, p in v.items() if k.endswith("_pattern") and k != "token_pattern"}
    for col in table.columns:
        if col.action == "keep" and col.get("pattern"):
            patterns.setdefault(col.name, col.get("pattern"))
    for name, pattern in patterns.items():
        if name in header:
            p = re.compile(pattern)
            indices = {i for i, r in enumerate(rows) if not p.fullmatch(r[name] or "")}
            n = len(indices)
            if n:
                _record(problems, findings, f"{table.name}.{name}: 일반화 형식이 아닌 값 {n}건",
                        "invalid_generalized_format", name, indices)
    return problems


def check_completeness(table: Table, header: list[str], rows: list[dict], findings=None) -> list[str]:
    if not table.validation.get("no_empty_output_values"):
        return []
    problems = []
    for col in header:
        indices = {i for i, r in enumerate(rows) if (r[col] or "") == ""}
        n = len(indices)
        if n:
            _record(problems, findings, f"{table.name}.{col}: 빈 값 {n}건", "empty_value", col, indices)
    return problems


OUTPUT_CHECKS = {
    "direct_identifier": check_direct_identifier,
    "tokenization": check_tokenization,
    "generalization": check_generalization,
    "completeness": check_completeness,
}


def output_checks(table: Table, header: list[str], rows: list[dict]) -> dict[str, list[str]]:
    """Checks that need only the output file. The review step runs these again on what was written."""
    return output_findings(table, header, rows)[0]


def output_findings(table: Table, header: list[str], rows: list[dict]):
    """One evaluation supplies both legacy messages and structured statistics."""
    checks, findings = {}, []
    for item, fn in OUTPUT_CHECKS.items():
        details = []
        checks[item] = fn(table, header, rows, details)
        findings.extend({**detail, "check": item} for detail in details)
    return checks, findings


def summarize_findings(total_rows, files):
    """Output-review statistics, not input-processing or transport failures.

    A row means (table name, zero-based index); indices never leave this function.
    Row counts are unions across checks/columns. File-level issues do not imply
    every row is invalid, so a failed file may have zero failed rows. Empty input
    has an undefined (null) percentage. Duplicate groups mark all member rows.
    affected_cells counts failing cells per reason; issue_count counts messages.
    Neither count is the number of regex occurrences inside an individual cell.
    """
    failed_rows, failed_files, reasons = set(), set(), {}
    file_issues = 0
    for table_name, details in files:
        for detail in details:
            failed_files.add(table_name)
            scope = "file" if detail["indices"] is None else "row"
            key = (detail["check"], detail["code"], detail.get("pattern"), scope)
            reason = reasons.setdefault(key, {"rows": set(), "files": set(),
                                              "affected_cells": 0, "issue_count": 0})
            reason["files"].add(table_name)
            reason["issue_count"] += 1
            if scope == "file":
                file_issues += 1
            else:
                affected = {(table_name, i) for i in detail["indices"]}
                failed_rows.update(affected)
                reason["rows"].update(affected)
                reason["affected_cells"] += len(affected)
    by_reason = []
    for (check, code, pattern, scope), reason in sorted(
            reasons.items(), key=lambda entry: tuple(str(v or "") for v in entry[0])):
        entry = {"check": check, "code": code, "scope": scope,
                 "failed_rows": len(reason["rows"]), "failed_files": len(reason["files"]),
                 "affected_cells": reason["affected_cells"], "issue_count": reason["issue_count"]}
        if pattern is not None:
            entry["pattern"] = pattern
        by_reason.append(entry)
    return {
        "total_rows": total_rows,
        "failed_rows": len(failed_rows),
        "failed_row_rate_percent": round(len(failed_rows) / total_rows * 100, 6) if total_rows else None,
        "total_files": len(files),
        "failed_files": len(failed_files),
        "file_issue_count": file_issues,
        "by_reason": by_reason,
    }


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
