from pipeline import review
from tests.conftest import read_out, write_out


def checks(result):
    return {c["item"]: c for c in result["checks"]}


def test_clean_output_passes(rules, out_dir):
    result = review.run(rules, out_dir, "20261120-01")
    assert result["passed"] and result["rows"] == 6
    assert result["rules_version"] == "benefit_review v3.1"
    assert list(checks(result)) == ["direct_identifier", "tokenization", "generalization", "completeness"]


def test_phone_left_in_a_cell_fails(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["region"] = "서울특별시 010-1234-5678"
    write_out(out_dir, table, rows)
    c = checks(review.run(rules, out_dir, "20261120-01"))
    assert not c["direct_identifier"]["passed"] and "region: phone 형식 1건" in c["direct_identifier"]["reason"]
    assert "010-1234-5678" not in str(c)


def test_extra_column_fails(rules, table, out_dir):
    write_out(out_dir, table, [{**r, "name": "x"} for r in read_out(out_dir, table)])
    c = checks(review.run(rules, out_dir, "20261120-01"))["direct_identifier"]
    assert not c["passed"] and c["value"] == 2  # column list differs + forbidden column


def test_raw_id_fails(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["payment_token"] = "900001"
    write_out(out_dir, table, rows)
    c = checks(review.run(rules, out_dir, "20261120-01"))["tokenization"]
    assert not c["passed"] and "토큰 형식이 아닌 값 1건" in c["reason"]


def test_ungeneralized_value_fails(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["age_group"] = "34"
    rows[1]["income_ratio_band"] = "85%"
    write_out(out_dir, table, rows)
    c = checks(review.run(rules, out_dir, "20261120-01"))["generalization"]
    assert not c["passed"] and c["value"] == 2


def test_empty_value_fails(rules, table, out_dir):
    rows = read_out(out_dir, table)
    rows[0]["gender"] = ""
    write_out(out_dir, table, rows)
    result = review.run(rules, out_dir, "20261120-01")
    assert not result["passed"] and not checks(result)["completeness"]["passed"]
