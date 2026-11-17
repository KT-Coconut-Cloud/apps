"""Analysis templates and their Athena queries. Keep in sync with result-app/app/catalog.py."""

import re
from dataclasses import dataclass

SIGUNGU = ["서울 강서구", "서울 노원구", "서울 중랑구", "부산 사하구", "대구 달서구", "인천 남동구", "광주 북구", "대전 서구"]
CRISIS_TYPES = ["단전", "단수", "건강보험료 체납", "통신비 체납", "임대료 체납", "금융 연체"]
HOUSEHOLD_TYPES = ["일반 가구", "1인 가구", "노인 가구", "한부모 가구", "장애인 가구"]
BENEFIT_TYPES = ["생계급여", "의료급여", "주거급여", "교육급여"]

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
YEAR = re.compile(r"^20\d{2}$")


class InvalidParams(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # month | year | choice
    choices: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class Scenario:
    key: str
    params: tuple[Param, ...]
    columns: tuple[str, ...]
    counts: tuple[str, ...]
    derived: tuple[str, ...] = ()


CATALOG = {
    "crisis_link_rate": Scenario(
        key="crisis_link_rate",
        params=(
            Param("from", "month", required=True),
            Param("to", "month", required=True),
            Param("crisis_type", "choice", tuple(CRISIS_TYPES)),
            Param("sigungu", "choice", tuple(SIGUNGU)),
        ),
        columns=("sigungu", "crisis_type", "households", "linked"),
        counts=("households", "linked"),
    ),
    "basic_living_status": Scenario(
        key="basic_living_status",
        params=(
            Param("from", "year", required=True),
            Param("to", "year", required=True),
            Param("household_type", "choice", tuple(HOUSEHOLD_TYPES)),
            Param("benefit_type", "choice", tuple(BENEFIT_TYPES)),
        ),
        columns=("year", "household_type", "benefit_type", "recipients", "avg_payment"),
        counts=("recipients",),
        derived=("avg_payment",),
    ),
}


def clean_params(scenario: Scenario, raw: dict) -> dict:
    out = {}
    for p in scenario.params:
        value = str(raw.get(p.name) or "").strip() or None
        if value is None:
            if p.required:
                raise InvalidParams(f"{p.name} is required")
        elif p.kind == "month" and not MONTH.match(value):
            raise InvalidParams(f"{p.name} must be YYYY-MM")
        elif p.kind == "year" and not YEAR.match(value):
            raise InvalidParams(f"{p.name} must be a 4-digit year")
        elif p.kind == "choice" and value not in p.choices:
            raise InvalidParams(f"{p.name} is not in the list")
        out[p.name] = value
    if out.get("from") and out.get("to") and out["from"] > out["to"]:
        raise InvalidParams("from is later than to")
    return out


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _inner_query(scenario: Scenario, run_id: str, p: dict) -> tuple[str, list[str]]:
    if scenario.key == "crisis_link_rate":
        where, args = ["s.signal_month BETWEEN ? AND ?"], [_text(p["from"]), _text(p["to"])]
        if p.get("crisis_type"):
            where.append("s.crisis_type = ?")
            args.append(_text(p["crisis_type"]))
        if p.get("sigungu"):
            where.append("c.sigungu = ?")
            args.append(_text(p["sigungu"]))
        return f"""
  SELECT c.sigungu,
         s.crisis_type,
         COUNT(DISTINCT s.citizen_id) AS households,
         COUNT(DISTINCT CASE WHEN s.linked = '1' THEN s.citizen_id END) AS linked
  FROM crisis_signal s
  JOIN citizen c ON c.citizen_id = s.citizen_id
  WHERE s.run_id = '{run_id}' AND c.run_id = '{run_id}'
    AND {" AND ".join(where)}
  GROUP BY c.sigungu, s.crisis_type""", args

    if scenario.key == "basic_living_status":
        where, args = ["CAST(p.year AS integer) BETWEEN ? AND ?"], [p["from"], p["to"]]
        if p.get("household_type"):
            where.append("c.household_type = ?")
            args.append(_text(p["household_type"]))
        if p.get("benefit_type"):
            where.append("p.benefit_type = ?")
            args.append(_text(p["benefit_type"]))
        return f"""
  SELECT CAST(p.year AS integer) AS year,
         c.household_type,
         p.benefit_type,
         COUNT(DISTINCT p.citizen_id) AS recipients,
         CAST(ROUND(AVG(CAST(p.monthly_amount AS double)), -2) AS bigint) AS avg_payment
  FROM benefit_payment p
  JOIN citizen c ON c.citizen_id = p.citizen_id
  WHERE p.run_id = '{run_id}' AND c.run_id = '{run_id}'
    AND {" AND ".join(where)}
  GROUP BY CAST(p.year AS integer), c.household_type, p.benefit_type""", args

    raise KeyError(scenario.key)


def build_query(scenario: Scenario, run_id: str, p: dict, min_cell: int) -> tuple[str, list[str]]:
    """Return SQL with ? placeholders and its parameters. Counts below min_cell come back NULL."""
    inner, args = _inner_query(scenario, run_id, p)
    small = {c: f"{c} BETWEEN 1 AND {int(min_cell) - 1}" for c in scenario.counts}
    any_small = " OR ".join(small.values())
    cols = []
    for c in scenario.columns:
        if c in small:
            cols.append(f"CASE WHEN {small[c]} THEN NULL ELSE {c} END AS {c}")
        elif c in scenario.derived:
            cols.append(f"CASE WHEN {any_small} THEN NULL ELSE {c} END AS {c}")
        else:
            cols.append(c)
    keys = [c for c in scenario.columns if c not in scenario.counts and c not in scenario.derived]
    sql = f"WITH g AS ({inner}\n)\nSELECT {', '.join(cols)}\nFROM g\nORDER BY {', '.join(keys)}"
    return sql, args
