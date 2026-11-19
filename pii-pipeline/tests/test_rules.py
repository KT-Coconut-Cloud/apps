import pytest
import yaml

from pipeline.rules import InvalidRules, load_rules
from tests.conftest import FIXTURES, SCHEMA


def write(tmp_path, change):
    data = yaml.safe_load((FIXTURES / "rules.yaml").read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_fixture_rules_load(rules):
    assert rules.version == "rules-v0.1"
    assert [c.name for c in rules.tables["citizen"].output] == ["citizen_id", "sigungu", "household_type"]
    assert rules.tables["crisis_signal"].token_column == "citizen_id"


@pytest.mark.parametrize("change", [
    lambda d: d.pop("version"),
    lambda d: d.update(version="v1"),
    lambda d: d["tables"]["citizen"]["columns"]["name"].update(action="mask"),
    lambda d: d["tables"]["citizen"]["columns"]["address"].pop("method"),
    lambda d: d["tables"]["citizen"]["columns"]["name"].update({"as": "nm"}),
    lambda d: d["tables"]["citizen"].update(quasi_identifiers=["address"]),
    lambda d: d["tables"]["crisis_signal"]["columns"]["signal_type"].update({"as": "citizen_id"}),
    lambda d: d["k_anonymity"].update(threshold=1),
    lambda d: d["tables"]["citizen"]["columns"]["citizen_id"].pop("key"),
    lambda d: d["tables"]["citizen"]["columns"]["household_type"].update(key="citizen-id"),
])
def test_bad_rules_are_rejected(tmp_path, change):
    with pytest.raises(InvalidRules):
        load_rules(write(tmp_path, change), SCHEMA)


def test_broken_yaml_is_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("version: [", encoding="utf-8")
    with pytest.raises(InvalidRules):
        load_rules(path, SCHEMA)
