"""Write synthetic data/, results/ and reports/ under sample-data/ for local development.

data/ stands in for the pseudonymized livelihood_payment table Athena queries, in
the layout the classifier writes to the clean bucket. Only the local fake Lambda
reads it; the app itself never does.

Rows follow the export columns of the pipeline.
"""

import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample-data"
TABLE = "livelihood_payment"
ROWS = 2000
PAY_MONTH = "2025-12"

# livelihood benefit (general) payments per region, Dec 2025, Korea Social Security Information Service
REGIONS = {
    "서울특별시": 245_582, "부산광역시": 137_750, "대구광역시": 86_550, "인천광역시": 91_934,
    "광주광역시": 47_852, "대전광역시": 42_451, "울산광역시": 21_884, "세종특별자치시": 3_615,
    "경기도": 238_002, "충청북도": 41_457, "충청남도": 52_414, "전라남도": 58_769,
    "경상북도": 85_739, "경상남도": 94_937, "제주특별자치도": 18_535, "강원특별자치도": 45_757,
    "전북특별자치도": 68_305,
}
AGE = {"20대": 5, "30대": 7, "40대": 11, "50대": 18, "60대": 23, "70대": 21, "80대 이상": 15}
HOUSEHOLD = {"1": 70, "2": 17, "3": 9, "4": 4}
# LE80 and GT80_LE100 are within the threshold, the GT100 bands need a recheck
INCOME = {"LE80": 60, "GT80_LE100": 20, "GT100_LE120": 10, "GT120": 5}
COLUMNS = [
    "payment_token", "household_token", "region", "age_group", "gender", "pay_month", "benefit_type",
    "household_size", "income_ratio_band",
]


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


def pick(rng: random.Random, weights: dict) -> str:
    return rng.choices(list(weights), weights=weights.values())[0]


def make_table(rng: random.Random, run_id: str, out: Path) -> None:
    # tokens mimic the HMAC values the pipeline puts in place of the real ids
    rows = []
    for i in range(ROWS):
        age = pick(rng, AGE)
        reviewed = rng.random() >= 0.05
        rows.append((
            "p_" + sha(f"{run_id}:p:{i}")[:16],
            "h_" + sha(f"{run_id}:h:{i}")[:16],
            pick(rng, REGIONS),
            age,
            rng.choices(["남", "여"], weights=[45, 55])[0],
            PAY_MONTH,
            "생계급여(일반)",
            pick(rng, HOUSEHOLD) if reviewed else "unknown",
            pick(rng, INCOME) if reviewed else "NO_DATA",
        ))
    write_csv(out / f"{TABLE}.csv", COLUMNS, rows)


def export_record(run_id: str, at: str, status: str) -> dict:
    files = []
    if status == "exported":
        files = [{"key": f"run_id={run_id}/{TABLE}.csv", "rows": ROWS, "sha256": sha(run_id + TABLE)}]
    return {"run_id": run_id, "executed_at": at, "status": status, "files": files}


def review(run_id: str, at: str, rules: str, k: int = 7, direct_ok: bool = True) -> dict:
    checks = [
        {"item": "direct_identifier", "passed": direct_ok, "value": 0 if direct_ok else 1,
         "reason": None if direct_ok else f"{TABLE}.phone 컬럼이 삭제되지 않음"},
        {"item": "generalization", "passed": True, "value": "주소 시도, 연령 10세 구간", "reason": None},
        {"item": "k_anonymity", "passed": k >= 5, "value": k,
         "reason": None if k >= 5 else f"최소 k={k}, 기준 5 미만 (세종특별자치시 80대 이상 4인 가구)"},
    ]
    return {"run_id": run_id, "reviewed_at": at, "rules_version": rules,
            "passed": all(c["passed"] for c in checks), "checks": checks}


def macie(run_id: str, at: str, hit: bool = False, error: str | None = None) -> dict:
    files = [{
        "key": f"run_id={run_id}/{TABLE}.csv",
        "detected": hit,
        "types": ["KR_MOBILE_PHONE", "KR_RRN"] if hit else [],
        "classification": "quarantine" if hit or error else "clean",
    }]
    verdict = "ERROR" if error else "FAIL" if hit else "PASS"
    return {"run_id": run_id, "scanned_at": at, "verdict": verdict, "error": error, "files": files}


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
        ("20261113-01", "2026-11-13T14:00:00+09:00", "error", "rules-v1.2"),
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
        hit = case == "macie"
        error = f"run_id={run_id}/{TABLE}.csv: sha256 mismatch" if case == "error" else None
        write_json(rep / "macie_result.json", macie(run_id, later, hit, error))

        if case == "ok":
            make_table(rng, run_id, ROOT / "data" / TABLE / f"run_id={run_id}")
            # marker the classifier writes once every file of the run is clean
            write_json(ROOT / "results" / f"run_id={run_id}" / "manifest.json", {
                "run_id": run_id,
                "generated_at": at.replace("T14:00", "T14:25"),
                "adequacy_passed": True,
                "tables": [TABLE],
            })


if __name__ == "__main__":
    main()
