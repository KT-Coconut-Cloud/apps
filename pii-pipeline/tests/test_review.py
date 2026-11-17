import csv

from pipeline import review


def checks(result):
    return {c["item"]: c for c in result["checks"]}


def rewrite(path, change):
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows = change(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_clean_output_passes(rules, out_dir):
    result = review.run(rules, out_dir, "20261117-01")
    assert result["passed"] and result["rules_version"] == "rules-v0.1"
    c = checks(result)
    assert c["direct_identifier"]["value"] == 0
    assert c["k_anonymity"]["value"] == 2
    assert c["generalization"]["value"] == "address 시군구, detected_date 월, pay_month 연도"


def test_leftover_column_fails(rules, out_dir):
    rewrite(out_dir / "crisis_signal.csv", lambda rows: [{**r, "contact_phone": "010-1111-2222"} for r in rows])
    c = checks(review.run(rules, out_dir, "20261117-01"))["direct_identifier"]
    assert not c["passed"] and c["value"] == 4
    assert c["reason"] == "crisis_signal.contact_phone 컬럼이 삭제되지 않음"


def test_raw_id_fails(rules, out_dir):
    rewrite(out_dir / "citizen.csv", lambda rows: [{**rows[0], "citizen_id": "1"}] + rows[1:])
    c = checks(review.run(rules, out_dir, "20261117-01"))["direct_identifier"]
    assert not c["passed"] and "토큰화되지 않은 값 1건" in c["reason"]


def test_small_group_fails(rules, out_dir):
    rewrite(out_dir / "citizen.csv", lambda rows: rows[:3])
    result = review.run(rules, out_dir, "20261117-01")
    c = checks(result)["k_anonymity"]
    assert not result["passed"] and c["value"] == 1
    assert c["reason"] == "최소 k=1, 기준 2 미만 (citizen: 서울 노원구 노인 가구)"


def test_ungeneralized_value_fails(rules, out_dir):
    rewrite(out_dir / "crisis_signal.csv", lambda rows: [{**rows[0], "signal_month": "2025-03-02"}] + rows[1:])
    c = checks(review.run(rules, out_dir, "20261117-01"))["generalization"]
    assert not c["passed"] and "signal_month" in c["reason"]
