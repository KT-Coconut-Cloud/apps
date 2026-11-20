import csv
from pathlib import Path

import pytest

from pipeline import pseudonymize
from pipeline.rules import load_rules
from pipeline.tokenizer import LocalTokenizer

REPO = Path(__file__).resolve().parents[2]
# tests run against the real rules file, so a rules change that breaks the pipeline fails CI
RULES = REPO / "rules" / "pii-rules.yaml"
SCHEMA = REPO / "rules" / "pii-rules.schema.json"
RAW = Path(__file__).parent / "fixtures" / "raw"
TABLE = "benefit_review_joined"


@pytest.fixture
def rules():
    return load_rules(RULES, SCHEMA)


@pytest.fixture
def table(rules):
    return rules.tables[TABLE]


@pytest.fixture
def raw_rows():
    return pseudonymize.read_csv_table(RAW, TABLE)


@pytest.fixture
def out_dir(tmp_path, rules):
    out = tmp_path / "out"
    pseudonymize.run(rules, out, LocalTokenizer(b"test"), RAW)
    return out


def read_out(out_dir, table):
    with (out_dir / table.filename).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_out(out_dir, table, rows):
    with (out_dir / table.filename).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
