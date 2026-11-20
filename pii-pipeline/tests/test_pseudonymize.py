import re

import pytest

from pipeline.pseudonymize import TransformError, ratio_band, transform_table, write_table
from pipeline.tokenizer import LocalTokenizer, TokenizerError
from tests.conftest import read_out

TOKEN = re.compile(r"^vault:v1:[A-Za-z0-9+/]{43}=$")


def run(table, rows, tokenizer=None):
    return transform_table(table, rows, tokenizer or LocalTokenizer(b"test"))


def test_output_matches_the_rules(table, out_dir):
    out = read_out(out_dir, table)
    assert list(out[0]) == list(table.output_columns)
    assert out[0] == {**out[0], "region": "서울특별시", "age_group": "30대", "gender": "남", "pay_month": "2025-12",
                      "benefit_type": "생계급여(일반)", "household_size": "1", "income_ratio_band": "LE80"}
    assert all(TOKEN.match(r["payment_token"]) and TOKEN.match(r["household_token"]) for r in out)


def test_file_format(table, out_dir):
    body = (out_dir / table.filename).read_bytes()
    assert body.startswith("﻿".encode()) and b"\r\n" in body


def test_generalization(table, out_dir):
    out = read_out(out_dir, table)
    assert [r["age_group"] for r in out] == ["30대", "60대", "70대", "0대", "80대", "120대"]
    # address with nothing after the sido name, household of 6, missing review row
    assert out[3]["region"] == "세종특별자치시" and out[3]["household_size"] == "5+"
    assert out[4]["household_size"] == "unknown" and out[4]["income_ratio_band"] == "NO_DATA"


def test_same_household_gets_the_same_token(table, out_dir):
    out = read_out(out_dir, table)
    assert out[1]["household_token"] == out[2]["household_token"]
    assert len({r["household_token"] for r in out}) == 5
    assert len({r["payment_token"] for r in out}) == 6


def test_token_input_uses_prefix_and_key(table, raw_rows):
    seen = []

    class Spy(LocalTokenizer):
        def tokens(self, values, key_name, key_version):
            seen.append((key_name, key_version, values[0]))
            return super().tokens(values, key_name, key_version)

    run(table, raw_rows, Spy(b"x"))
    assert seen == [("payment-id", 1, "payment:v1:900001"), ("household-id", 1, "household:v1:7001")]


@pytest.mark.parametrize("num,den,band", [
    ("80", "100", "LE80"), ("81", "100", "GT80_LE100"), ("100", "100", "GT80_LE100"),
    ("120", "100", "GT100_LE120"), ("121", "100", "GT120"), ("0", "100", "LE80"),
    ("", "100", "NO_DATA"), ("50", "", "NO_DATA"),
])
def test_ratio_band_edges(table, num, den, band):
    assert ratio_band(table.derived[0], num, den) == band


def test_zero_limit_is_an_error(table):
    with pytest.raises(TransformError):
        ratio_band(table.derived[0], "10", "0")


@pytest.mark.parametrize("column,value", [
    ("payment_id", "0900007"),        # not canonical
    ("payment_id", ""),               # not nullable
    ("address", "서울 강남구"),        # short sido name is not in allowed_values
    ("address", "서울특별시강남구"),    # no space after the sido name
    ("age", "121"),
    ("age", "-1"),
    ("gender", "M"),
    ("pay_month", "2025-13"),
    ("benefit_type", "주거급여"),
    ("household_size", "0"),
    ("recognized_income", "-5"),
])
def test_bad_input_value_stops_the_run(table, raw_rows, column, value):
    raw_rows[0][column] = value
    with pytest.raises(TransformError) as e:
        run(table, raw_rows)
    # row number and column only, never the value
    assert f".{column} row 1" in str(e.value) and (value == "" or value not in str(e.value))


def test_unknown_input_column_stops_the_run(table, raw_rows):
    for r in raw_rows:
        r["rrn"] = "900101-1XXXXXX"
    with pytest.raises(TransformError, match="not in the rules"):
        run(table, raw_rows)


def test_missing_input_column_stops_the_run(table, raw_rows):
    for r in raw_rows:
        del r["phone"]
    with pytest.raises(TransformError, match="no column"):
        run(table, raw_rows)


def test_vault_failure_stops_the_run(table, raw_rows):
    class Down:
        def tokens(self, values, key_name, key_version):
            raise TokenizerError("vault transit/hmac/payment-id/sha2-256: connection refused")

    with pytest.raises(TransformError, match="connection refused"):
        run(table, raw_rows, Down())


def test_bad_tokens_are_caught_by_output_validation(table, raw_rows):
    class Broken:
        def tokens(self, values, key_name, key_version):
            return ["same" for _ in values]

    with pytest.raises(TransformError) as e:
        run(table, raw_rows, Broken())
    msg = str(e.value)
    assert "토큰 형식이 아닌 값" in msg and "중복 값" in msg and "다른 household_id에 같은 토큰" in msg


def test_nothing_is_written_when_the_run_fails(table, raw_rows, tmp_path):
    raw_rows[0]["age"] = "999"
    with pytest.raises(TransformError):
        write_table(tmp_path, table, run(table, raw_rows))
    assert not (tmp_path / table.filename).exists()
