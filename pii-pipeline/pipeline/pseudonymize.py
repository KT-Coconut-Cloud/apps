import csv
import logging
import os
import re
from datetime import date
from pathlib import Path

from pipeline.rules import Column, Rules, Table

log = logging.getLogger("pseudonymize")

SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
}


class TransformError(ValueError):
    pass


def _sigungu(value: str, today: date) -> str:
    parts = value.split()
    if len(parts) < 2:
        raise TransformError(f"address without sigungu: {len(parts)} part(s)")
    return f"{SIDO_SHORT.get(parts[0], parts[0])} {parts[1]}"


def _month(value: str, today: date) -> str:
    if not re.match(r"^\d{4}-\d{2}", value):
        raise TransformError("not a date")
    return value[:7]


def _year(value: str, today: date) -> str:
    if not re.match(r"^\d{4}", value):
        raise TransformError("not a date")
    return value[:4]


def _age_band(value: str, today: date) -> str:
    born = date.fromisoformat(value[:10])
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if age >= 90:
        return "90세 이상"
    low = age // 5 * 5
    return f"{low}~{low + 4}세"


METHODS = {"sigungu": _sigungu, "month": _month, "year": _year, "age_band": _age_band}


def read_csv_table(source_dir: Path, table: str) -> list[dict]:
    with (Path(source_dir) / f"{table}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_mysql_table(table: str) -> list[dict]:
    import pymysql

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
            # table names come from the reviewed rules file, not from user input
            cur.execute(f"SELECT * FROM `{table}`")
            return [{k: "" if v is None else str(v) for k, v in row.items()} for row in cur.fetchall()]
    finally:
        conn.close()


def _apply(col: Column, value: str, today: date):
    if col.action == "keep":
        return value
    if col.action == "generalize":
        return METHODS[col.method](value, today) if value else ""
    if col.action == "map":
        if value in col.values:
            return col.values[value]
        if col.default is not None:
            return col.default
        raise TransformError("value not in map")
    raise AssertionError(col.action)


def transform_table(table: Table, rows: list[dict], tokenizer, today: date | None = None) -> list[dict]:
    today = today or date.today()
    if rows:
        known = {c.source for c in table.columns}
        # columns the rules don't mention are never written out
        for extra in sorted(set(rows[0]) - known):
            log.warning("%s.%s is not in the rules, dropped", table.name, extra)
        missing = sorted(known - set(rows[0]))
        if missing:
            raise TransformError(f"{table.name}: source has no column {missing}")

    out = [{} for _ in rows]
    for col in table.output:
        if col.action == "tokenize":
            values = [r[col.source] for r in rows]
            unique = sorted(set(values))
            lookup = dict(zip(unique, tokenizer.tokens(unique, col.key)))
            for o, v in zip(out, values):
                o[col.name] = lookup[v]
            continue
        for i, (o, r) in enumerate(zip(out, rows)):
            try:
                o[col.name] = _apply(col, r[col.source], today)
            except (TransformError, ValueError) as e:
                # no values in the message, logs leave the cluster
                raise TransformError(f"{table.name}.{col.source} row {i + 1}: {e}") from None
    return out


def write_table(out_dir: Path, table: Table, rows: list[dict]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{table.name}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[c.name for c in table.output], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


def run(rules: Rules, out_dir: Path, tokenizer, source_dir: Path | None = None) -> dict[str, int]:
    counts = {}
    for table in rules.tables.values():
        rows = read_csv_table(source_dir, table.name) if source_dir else read_mysql_table(table.name)
        write_table(out_dir, table, transform_table(table, rows, tokenizer))
        counts[table.name] = len(rows)
        log.info("%s: %d rows", table.name, len(rows))
    return counts
