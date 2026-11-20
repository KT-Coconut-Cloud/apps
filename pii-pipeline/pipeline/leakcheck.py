"""CI only: apply the rules to synthetic data and look for raw values in the output."""

from pathlib import Path

from pipeline import validate
from pipeline.pseudonymize import TransformError, generalize, read_csv_table
from pipeline.review import read_output
from pipeline.rules import Rules

SUBSTRING_MIN = 8


def _changed(col, value: str) -> bool:
    try:
        return generalize(col, value) != value
    except TransformError:
        return True


def run(rules: Rules, raw_dir: Path, out_dir: Path) -> list[str]:
    problems = []
    for table in rules.tables.values():
        raw = read_csv_table(raw_dir, table.name)
        header, rows = read_output(out_dir, table)
        cells = {r[c] for r in rows for c in header if r[c]}
        text = "\n".join(cells)

        # raw values that must not leave as-is: dropped, tokenized, and generalized ones the rule changes
        for col in table.columns:
            if col.action == "keep":
                continue
            if col.action == "drop" and col.source in header:
                problems.append(f"{table.name}.{col.source}: dropped column is in the output")
            values = {r[col.source] for r in raw if len(r[col.source]) >= 2}
            if col.action == "generalize":
                values = {v for v in values if _changed(col, v)}
            exact = values & cells
            partial = {v for v in values if len(v) >= SUBSTRING_MIN and v in text}
            if exact or partial:
                problems.append(f"{table.name}.{col.source}: {len(exact | partial)} raw value(s) found in the output")

        for item, found in validate.output_checks(table, header, rows).items():
            problems += [f"{item}: {p}" for p in found]
    return problems
