"""CI only: apply the rules to synthetic data and look for raw values in the output."""

from pathlib import Path

from pipeline.patterns import IDENTIFIERS, TOKEN
from pipeline.pseudonymize import read_csv_table
from pipeline.review import read_output
from pipeline.rules import Rules

SUBSTRING_MIN = 8


def run(rules: Rules, raw_dir: Path, out_dir: Path) -> list[str]:
    problems = []
    outputs = {name: read_output(out_dir, name) for name in rules.tables}
    cells = {(t, c): {r[c] for r in rows if r[c]} for t, (header, rows) in outputs.items() for c in header}
    all_cells = set().union(*cells.values()) if cells else set()
    text = "\n".join(all_cells)

    for table in rules.tables.values():
        raw = read_csv_table(raw_dir, table.name)
        header, rows = outputs[table.name]

        for col in table.columns:
            if col.action == "drop":
                if col.source in header:
                    problems.append(f"{table.name}.{col.source}: dropped column is in the output")
                values = {r[col.source] for r in raw if len(r[col.source]) >= 2}
                exact = values & all_cells
                partial = {v for v in values if len(v) >= SUBSTRING_MIN and v in text}
                if exact or partial:
                    problems.append(f"{table.name}.{col.source}: {len(exact | partial)} raw value(s) found in the output")
            elif col.action == "tokenize":
                bad = [v for v in cells.get((table.name, col.name), ()) if not TOKEN.match(v)]
                if bad:
                    problems.append(f"{table.name}.{col.name}: {len(bad)} value(s) are not tokens")

    for (table, col), values in cells.items():
        for label, pattern in IDENTIFIERS.items():
            n = sum(1 for v in values if pattern.search(v))
            if n:
                problems.append(f"{table}.{col}: {n} value(s) look like {label}")
    return problems
