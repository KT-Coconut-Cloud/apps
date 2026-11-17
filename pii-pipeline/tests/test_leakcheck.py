from pipeline import leakcheck
from pipeline.__main__ import main
from tests.conftest import FIXTURES, RAW, SCHEMA


def test_clean_output_has_no_problems(rules, out_dir):
    assert leakcheck.run(rules, RAW, out_dir) == []


def test_raw_value_in_another_column_is_found(rules, out_dir):
    path = out_dir / "crisis_signal.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("단전", "홍길동"), encoding="utf-8")
    problems = leakcheck.run(rules, RAW, out_dir)
    assert any(p.startswith("citizen.name") for p in problems)


def test_phone_inside_a_kept_value_is_found(rules, out_dir):
    path = out_dir / "citizen.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("1인 가구", "1인 가구 010-0000-0001", 1), encoding="utf-8")
    problems = leakcheck.run(rules, RAW, out_dir)
    assert any(p.startswith("citizen.phone") for p in problems)
    assert any("휴대전화" in p for p in problems)


def test_cli(tmp_path, capsys):
    common = ["--rules", str(FIXTURES / "rules.yaml"), "--schema", str(SCHEMA), "--work", str(tmp_path)]
    assert main(common + ["validate-rules"]) == 0
    assert main(common + ["leakcheck", "--raw-dir", str(RAW)]) == 0
    assert main(common + ["review", "--run-id", "20261117-01"]) == 0
    assert (tmp_path / "adequacy_review.json").exists()
    assert main(common + ["review", "--run-id", "bad"]) == 1
