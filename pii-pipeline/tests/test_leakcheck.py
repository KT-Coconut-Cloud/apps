from pipeline import leakcheck
from pipeline.__main__ import main
from tests.conftest import RAW, RULES, SCHEMA, read_out, write_out


def test_clean_output_has_no_problems(rules, out_dir):
    assert leakcheck.run(rules, RAW, out_dir) == []


def test_raw_name_in_another_column_is_found(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["gender"] = "홍길동"
    write_out(out_dir, table, rows)
    problems = leakcheck.run(rules, RAW, out_dir)
    assert any(p.startswith("benefit_review_joined.name") for p in problems)


def test_raw_address_inside_a_value_is_found(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["region"] = "서울특별시 강남구 테스트로 1"
    write_out(out_dir, table, rows)
    problems = leakcheck.run(rules, RAW, out_dir)
    assert any(p.startswith("benefit_review_joined.address") for p in problems)


def test_cli(tmp_path, capsys):
    common = ["--rules", str(RULES), "--schema", str(SCHEMA), "--work", str(tmp_path)]
    assert main(common + ["validate-rules"]) == 0
    assert main(common + ["leakcheck", "--raw-dir", str(RAW)]) == 0
    assert main(common + ["review", "--run-id", "20261120-01"]) == 0
    assert (tmp_path / "adequacy_review.json").exists()
    assert main(common + ["review", "--run-id", "bad"]) == 1


def test_cli_pseudonymize_without_a_key_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("PII_HMAC_KEY", raising=False)
    common = ["--rules", str(RULES), "--schema", str(SCHEMA), "--work", str(tmp_path)]
    assert main(common + ["pseudonymize", "--source-dir", str(RAW)]) == 1
    assert not (tmp_path / "out").exists()
