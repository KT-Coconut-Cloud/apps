from pathlib import Path

import pytest

from pipeline import pseudonymize
from pipeline.rules import load_rules
from pipeline.tokenizer import LocalTokenizer

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = Path(__file__).resolve().parents[2] / "rules" / "pii-rules.schema.json"
RAW = FIXTURES / "raw"


@pytest.fixture
def rules():
    return load_rules(FIXTURES / "rules.yaml", SCHEMA)


@pytest.fixture
def out_dir(tmp_path, rules):
    out = tmp_path / "out"
    pseudonymize.run(rules, out, LocalTokenizer(b"test"), RAW)
    return out
