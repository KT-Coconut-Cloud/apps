import csv
from datetime import date

import pytest

from pipeline.patterns import TOKEN
from pipeline.pseudonymize import METHODS, TransformError, transform_table
from pipeline.tokenizer import LocalTokenizer


def read(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_output_has_only_columns_from_rules(out_dir):
    citizen = read(out_dir / "citizen.csv")
    assert list(citizen[0]) == ["citizen_id", "sigungu", "household_type"]
    assert citizen[0]["sigungu"] == "서울 강남구"
    assert all(TOKEN.match(r["citizen_id"]) for r in citizen)

    signal = read(out_dir / "crisis_signal.csv")
    assert signal[0] == {**signal[0], "crisis_type": "단전", "signal_month": "2025-03", "linked": "1"}
    assert signal[1]["linked"] == "0"

    payment = read(out_dir / "benefit_payment.csv")
    assert payment[2] == {**payment[2], "benefit_type": "생계급여", "year": "2024", "monthly_amount": "1023000"}


def test_same_person_gets_the_same_token_in_every_table(out_dir):
    citizen = read(out_dir / "citizen.csv")
    signal = read(out_dir / "crisis_signal.csv")
    payment = read(out_dir / "benefit_payment.csv")
    assert citizen[0]["citizen_id"] == signal[0]["citizen_id"] == payment[0]["citizen_id"]
    assert len({r["citizen_id"] for r in citizen}) == 4


def test_column_missing_from_rules_is_not_written(rules):
    rows = [{"signal_id": "1", "citizen_id": "1", "signal_type": "단전", "detected_date": "2025-01-01",
             "consult_result": "지원 연계", "linked_service": "없음", "memo": "010-1234-5678"}]
    out = transform_table(rules.tables["crisis_signal"], rows, LocalTokenizer(b"k"))
    assert "memo" not in out[0]


def test_error_message_has_no_values(rules):
    rows = [{"citizen_id": "1", "name": "홍길동", "rrn": "x", "birth_date": "x", "gender": "남", "phone": "x",
             "email": "x", "address": "주소없음", "household_type": "1인 가구", "income_level": "x"}]
    with pytest.raises(TransformError) as e:
        transform_table(rules.tables["citizen"], rows, LocalTokenizer(b"k"))
    assert "주소없음" not in str(e.value) and "citizen.address row 1" in str(e.value)


def test_age_band():
    today = date(2026, 11, 17)
    assert METHODS["age_band"]("1990-01-01", today) == "35~39세"
    assert METHODS["age_band"]("1990-12-31", today) == "35~39세"
    assert METHODS["age_band"]("1930-01-01", today) == "90세 이상"


def test_each_transit_key_gives_different_tokens():
    tok = LocalTokenizer(b"k")
    assert tok.tokens(["100"], "payment-id") != tok.tokens(["100"], "household-id")
    assert tok.tokens(["100"], "payment-id") == tok.tokens(["100"], "payment-id")
