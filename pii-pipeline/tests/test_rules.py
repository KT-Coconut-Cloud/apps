import pytest
import yaml

from pipeline.rules import InvalidRules, load_rules
from tests.conftest import RULES, SCHEMA, TABLE


def write(tmp_path, change):
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    change(data["table"][TABLE], data)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    # keep the repo-relative paths in the rules working
    for name in ("vault-client.example.yaml",):
        (rules_dir / name).write_text((RULES.parent / name).read_text(encoding="utf-8"), encoding="utf-8")
    (rules_dir / "mysql").mkdir()
    (rules_dir / "mysql" / "benefit_review.sql").write_text("SELECT 1", encoding="utf-8")
    path = rules_dir / "pii-rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_real_rules_load(rules):
    t = rules.tables[TABLE]
    assert rules.scenario == "benefit_review" and rules.version == "3.1"
    assert t.filename == "livelihood_payment.csv"
    assert t.output_columns[:2] == ("payment_token", "household_token")
    assert [c.get("key") for c in t.token_columns] == ["payment-id", "household-id"]
    assert t.source_sql.name == "benefit_review.sql"
    assert rules.vault_profile["auth"]["expected_namespace"] == "pii-job"


def test_unchanged_copy_loads(tmp_path):
    load_rules(write(tmp_path, lambda t, d: None), SCHEMA)


@pytest.mark.parametrize("change", [
    lambda t, d: d.pop("version"),
    lambda t, d: d.update(version="rules-v1"),
    lambda t, d: d.update(tables=d.pop("table")),
    lambda t, d: t["columns"]["name"].update(action="mask"),
    lambda t, d: t["columns"]["name"].update({"as": "nm"}),
    lambda t, d: t["columns"]["payment_id"].pop("key"),
    lambda t, d: t["columns"]["payment_id"].update(algorithm="md5"),
    lambda t, d: t["columns"]["age"].pop("interval"),
    lambda t, d: t["columns"]["age"].update(method="sigungu"),
    lambda t, d: t["columns"]["gender"].update(key="x"),
    lambda t, d: t.update(processing_order=["derive", "validate_input"]),
    # output problems the schema can't see
    lambda t, d: t["output"]["columns"].append("phone"),
    lambda t, d: t["output"]["columns"].remove("region"),
    lambda t, d: t["columns"]["gender"].update({"as": "region"}),
    lambda t, d: t["validation"]["forbidden_columns"].append("gender"),
    lambda t, d: t["validation"].update(consistent_token_source="gender"),
    lambda t, d: t["derived"]["income_ratio_band"].update(numerator="salary"),
    lambda t, d: t["validation"].update(age_group_pattern="(["),
    lambda t, d: t.update(source_sql="rules/mysql/missing.sql"),
])
def test_bad_rules_are_rejected(tmp_path, change):
    with pytest.raises(InvalidRules):
        load_rules(write(tmp_path, change), SCHEMA)


def test_broken_yaml_is_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("version: [", encoding="utf-8")
    with pytest.raises(InvalidRules):
        load_rules(path, SCHEMA)
