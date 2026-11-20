"""Apply the rules to the joined input, in the table's processing_order."""

import csv
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pipeline import validate
from pipeline.rules import Column, Derived, Rules, Table
from pipeline.tokenizer import TokenizerError

log = logging.getLogger("pseudonymize")

CANONICAL_POSITIVE_INT = re.compile(r"^[1-9][0-9]*$")


class TransformError(ValueError):
    pass


# --- input -----------------------------------------------------------------

def read_csv_table(source_dir: Path, table: str) -> list[dict]:
    with (Path(source_dir) / f"{table}.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_mysql(table: Table) -> list[dict]:
    import pymysql

    if table.source_sql is None:
        raise TransformError(f"{table.name}: no source_sql in the rules")
    conn = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            # the query comes from the reviewed rules folder baked into the image, not from user input
            cur.execute(table.source_sql.read_text(encoding="utf-8"))
            return [{k: "" if v is None else str(v) for k, v in row.items()} for row in cur.fetchall()]
    finally:
        conn.close()


def _number(value: str) -> Decimal:
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise TransformError("not a number") from None
    if not n.is_finite():
        raise TransformError("not a number")
    return n


# --- steps -----------------------------------------------------------------

def validate_input(table: Table, rows: list[dict]) -> None:
    header = set(rows[0]) if rows else set()
    known = {c.source for c in table.columns}
    missing = sorted(known - header)
    if rows and missing:
        raise TransformError(f"{table.name}: input has no column {missing}")
    extra = sorted(header - known)
    if extra:
        if table.unknown_input_column == "error":
            raise TransformError(f"{table.name}: input column not in the rules {extra}")
        log.warning("%s: input columns not in the rules are dropped %s", table.name, extra)

    for col in table.columns:
        for i, r in enumerate(rows, 1):
            try:
                _check_input_value(col, r[col.source])
            except TransformError as e:
                # row number only, logs leave the cluster
                raise TransformError(f"{table.name}.{col.source} row {i}: {e}") from None


def _check_input_value(col: Column, value: str) -> None:
    if value == "":
        if col.get("nullable") is False:
            raise TransformError("empty value")
        return
    if col.action == "tokenize" and col.get("input_format") == "canonical_positive_integer_utf8":
        if not CANONICAL_POSITIVE_INT.match(value):
            raise TransformError("not a canonical positive integer")
    if col.action == "keep":
        allowed = col.get("allowed_values")
        if allowed is not None and value not in allowed:
            raise TransformError("value not in allowed_values")
        if col.get("pattern") and not re.fullmatch(col.get("pattern"), value):
            raise TransformError("value does not match pattern")
    if col.get("input_min") is not None or col.get("input_max") is not None:
        n = _number(value)
        if col.get("input_min") is not None and n < Decimal(str(col.get("input_min"))):
            raise TransformError("below input_min")
        if col.get("input_max") is not None and n > Decimal(str(col.get("input_max"))):
            raise TransformError("above input_max")


def ratio_band(d: Derived, numerator: str, denominator: str) -> str:
    if numerator == "" or denominator == "":
        return d.get("on_missing")
    num, den = _number(numerator), _number(denominator)
    if den <= 0 or num < 0:
        raise TransformError("invalid ratio input")
    for band in d.get("bands"):
        if band.get("otherwise"):
            return band["output"]
        # num / den * 100 <= upper, without dividing
        if num * 100 <= Decimal(str(band["upper_percent_inclusive"])) * den:
            return band["output"]
    raise TransformError("no band matched")


def derive(table: Table, rows: list[dict]) -> list[dict]:
    out = [{} for _ in rows]
    for d in table.derived:
        for i, (o, r) in enumerate(zip(out, rows), 1):
            try:
                o[d.name] = ratio_band(d, r[d.get("numerator")], r[d.get("denominator")])
            except TransformError as e:
                raise TransformError(f"{table.name}.{d.name} row {i}: {e}") from None
    return out


def age_band(col: Column, value: str) -> str:
    n = _number(value)
    if n != n.to_integral_value():
        raise TransformError("age is not an integer")
    age, step = int(n), col.get("interval")
    lower = age // step * step
    return col.get("output_template").format(lower=lower, upper=lower + step - 1)


def leading_sido_name(col: Column, value: str) -> str:
    # longest first, so a name that starts with another name still matches whole
    for name in sorted(col.get("allowed_values"), key=len, reverse=True):
        if value == name or (value.startswith(name) and value[len(name)].isspace()):
            return name
    raise TransformError("unknown sido")


def top_code(col: Column, value: str) -> str:
    if value == "":
        if col.get("null_value") is None:
            raise TransformError("empty value")
        return col.get("null_value")
    n = _number(value)
    if n != n.to_integral_value():
        raise TransformError("not an integer")
    if col.get("input_min") is not None and n < col.get("input_min"):
        raise TransformError("below input_min")
    out = col.get("top_code_value") if n >= col.get("top_code_from") else str(int(n))
    allowed = col.get("allowed_output_values")
    if allowed is not None and out not in allowed:
        raise TransformError("output not in allowed_output_values")
    return out


METHODS = {"age_band": age_band, "leading_sido_name": leading_sido_name, "top_code": top_code}


def generalize(col: Column, value: str) -> str:
    if value == "" and col.get("method") != "top_code":
        if col.get("nullable") is False:
            raise TransformError("empty value")
        return ""
    return METHODS[col.get("method")](col, value)


def token_input(col: Column, value: str) -> str:
    return col.get("input_prefix", "") + value


def transform_columns(table: Table, rows: list[dict], out: list[dict], tokenizer) -> None:
    for col in table.columns:
        if col.action == "drop":
            continue
        if col.action == "tokenize":
            values = [r[col.source] for r in rows]
            unique = sorted(set(values))
            try:
                tokens = tokenizer.tokens([token_input(col, v) for v in unique], col.get("key"), col.get("key_version"))
            except TokenizerError as e:
                # on_vault_failure: error. nothing is written when Vault is unavailable
                raise TransformError(f"{table.name}.{col.source}: {e}") from None
            lookup = dict(zip(unique, tokens))
            for o, v in zip(out, values):
                o[col.name] = lookup[v]
            continue
        for i, (o, r) in enumerate(zip(out, rows), 1):
            try:
                o[col.name] = r[col.source] if col.action == "keep" else generalize(col, r[col.source])
            except TransformError as e:
                raise TransformError(f"{table.name}.{col.source} row {i}: {e}") from None


def select_output(table: Table, out: list[dict]) -> list[dict]:
    return [{name: o[name] for name in table.output_columns} for o in out]


def transform_table(table: Table, rows: list[dict], tokenizer) -> list[dict]:
    validate_input(table, rows)
    out = derive(table, rows)
    transform_columns(table, rows, out, tokenizer)
    out = select_output(table, out)
    problems = validate.all_checks(table, out, rows)
    if problems:
        # on_failure: block_export. the run stops here and nothing is written
        raise TransformError(f"{table.name}: output validation failed\n" + "\n".join(problems))
    return out


# --- output ----------------------------------------------------------------

QUOTING = {"minimal": csv.QUOTE_MINIMAL, "all": csv.QUOTE_ALL, "nonnumeric": csv.QUOTE_NONNUMERIC,
           "none": csv.QUOTE_NONE}


def write_table(out_dir: Path, table: Table, rows: list[dict]) -> Path:
    o = table.output
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / table.filename
    with path.open("w", encoding=o.get("encoding", "utf-8"), newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=list(table.output_columns),
            delimiter=o.get("delimiter", ","),
            quotechar=o.get("quotechar", '"'),
            quoting=QUOTING[o.get("quoting", "minimal")],
            doublequote=o.get("doublequote", True),
            lineterminator=o.get("lineterminator", "\n"),
        )
        w.writeheader()
        w.writerows(rows)
    return path


def run(rules: Rules, out_dir: Path, tokenizer, source_dir: Path | None = None) -> dict[str, int]:
    counts = {}
    for table in rules.tables.values():
        rows = read_csv_table(source_dir, table.name) if source_dir else read_mysql(table)
        write_table(out_dir, table, transform_table(table, rows, tokenizer))
        counts[table.name] = len(rows)
        log.info("%s: %d rows -> %s", table.name, len(rows), table.filename)
    return counts
