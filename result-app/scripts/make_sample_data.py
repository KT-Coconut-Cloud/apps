"""Write synthetic data/, results/ and reports/ under sample-data/ for local development.

data/ stands in for the pseudonymized tables Athena queries. Only the local
fake Lambda reads it; the app itself never does.
"""

import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample-data"

SIGUNGU = ["서울 강서구", "서울 노원구", "서울 중랑구", "부산 사하구", "대구 달서구", "인천 남동구", "광주 북구", "대전 서구"]
CRISIS = {"단전": 0.62, "단수": 0.58, "건강보험료 체납": 0.41, "통신비 체납": 0.35, "임대료 체납": 0.47, "금융 연체": 0.29}
CRISIS_WEIGHT = [18, 10, 30, 22, 14, 6]
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
HOUSEHOLD = {"일반 가구": 40, "1인 가구": 25, "노인 가구": 18, "한부모 가구": 9, "장애인 가구": 8}
BENEFIT = {"생계급여": (640_000, 35), "의료급여": (210_000, 30), "주거급여": (320_000, 28), "교육급여": (45_000, 7)}
YEARS = [2023, 2024, 2025, 2026]
TABLES = {"citizen.csv": 3000, "crisis_signal.csv": 1500, "benefit_payment.csv": 5000}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def make_tables(rng: random.Random, run_id: str, out: Path) -> None:
    # citizen_id mimics the HMAC token the pipeline puts in place of the real id
    citizens = []
    for i in range(TABLES["citizen.csv"]):
        token = "t_" + sha(f"{run_id}:{i}")[:16]
        sigungu = rng.choice(SIGUNGU)
        household = rng.choices(list(HOUSEHOLD), weights=HOUSEHOLD.values())[0]
        citizens.append((token, sigungu, household))
    write_csv(out / "citizen.csv", ["citizen_id", "sigungu", "household_type"], citizens)

    signals = []
    for _ in range(TABLES["crisis_signal.csv"]):
        token = rng.choice(citizens)[0]
        crisis = rng.choices(list(CRISIS), weights=CRISIS_WEIGHT)[0]
        rate = min(0.95, max(0.05, CRISIS[crisis] + rng.uniform(-0.15, 0.15)))
        signals.append((token, rng.choice(MONTHS), crisis, int(rng.random() < rate)))
    write_csv(out / "crisis_signal.csv", ["citizen_id", "signal_month", "crisis_type", "linked"], signals)

    payments = []
    for _ in range(TABLES["benefit_payment.csv"]):
        token = rng.choice(citizens)[0]
        year = rng.choice(YEARS)
        benefit = rng.choices(list(BENEFIT), weights=[w for _, w in BENEFIT.values()])[0]
        base = BENEFIT[benefit][0] * (1 + 0.03 * (year - YEARS[0]))
        payments.append((token, year, benefit, int(round(base * rng.uniform(0.85, 1.15), -2))))
    write_csv(out / "benefit_payment.csv", ["citizen_id", "year", "benefit_type", "monthly_amount"], payments)


def export_record(run_id: str, at: str, status: str) -> dict:
    files = []
    if status == "exported":
        files = [
            {"key": f"data/run_id={run_id}/{name}", "rows": rows, "sha256": sha(run_id + name)}
            for name, rows in TABLES.items()
        ]
    return {"run_id": run_id, "executed_at": at, "status": status, "files": files}


def review(run_id: str, at: str, rules: str, k: int = 7, direct_ok: bool = True) -> dict:
    checks = [
        {"item": "direct_identifier", "passed": direct_ok, "value": 0 if direct_ok else 1,
         "reason": None if direct_ok else "crisis_signal.contact_phone 컬럼이 삭제되지 않음"},
        {"item": "generalization", "passed": True, "value": "주소 시군구, 생년 5세 구간", "reason": None},
        {"item": "k_anonymity", "passed": k >= 5, "value": k,
         "reason": None if k >= 5 else f"최소 k={k}, 기준 5 미만 (노원구 90세 이상 1인 가구)"},
    ]
    return {"run_id": run_id, "reviewed_at": at, "rules_version": rules,
            "passed": all(c["passed"] for c in checks), "checks": checks}


def macie(run_id: str, at: str, hit: str | None = None) -> dict:
    files = []
    for name in TABLES:
        detected = name == hit
        files.append({
            "key": f"data/run_id={run_id}/{name}",
            "detected": detected,
            "types": ["KR_MOBILE_PHONE", "KR_RRN"] if detected else [],
            "classification": "quarantine" if detected else "clean",
        })
    return {"run_id": run_id, "scanned_at": at, "files": files}


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    rng = random.Random(42)

    runs = [
        ("20261109-01", "2026-11-09T14:00:00+09:00", "ok", "rules-v1.0"),
        ("20261110-01", "2026-11-10T14:00:00+09:00", "macie", "rules-v1.0"),
        ("20261111-01", "2026-11-11T14:00:00+09:00", "k_anon", "rules-v1.1"),
        ("20261111-02", "2026-11-11T16:30:00+09:00", "direct", "rules-v1.1"),
        ("20261112-01", "2026-11-12T14:00:00+09:00", "ok", "rules-v1.2"),
    ]

    for run_id, at, case, rules in runs:
        rep = ROOT / "reports" / f"run_id={run_id}"
        if case == "k_anon":
            write_json(rep / "adequacy_review.json", review(run_id, at, rules, k=2))
            continue
        if case == "direct":
            write_json(rep / "adequacy_review.json", review(run_id, at, rules, direct_ok=False))
            continue

        write_json(rep / "adequacy_review.json", review(run_id, at, rules))
        write_json(rep / "export_record.json", export_record(run_id, at, "exported"))
        later = at.replace("T14:00", "T14:20")
        write_json(rep / "macie_result.json", macie(run_id, later, "crisis_signal.csv" if case == "macie" else None))

        if case == "ok":
            make_tables(rng, run_id, ROOT / "data" / f"run_id={run_id}")
            # marker the classifier writes once every file of the run is clean
            write_json(ROOT / "results" / f"run_id={run_id}" / "manifest.json", {
                "run_id": run_id,
                "generated_at": at.replace("T14:00", "T14:25"),
                "adequacy_passed": True,
                "tables": [name.removesuffix(".csv") for name in TABLES],
            })


if __name__ == "__main__":
    main()
