"""Analysis templates and their Athena queries. Keep in sync with result-app/app/catalog.py."""

import re
from dataclasses import dataclass

TABLE = "livelihood_payment"

REGIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도",
]
AGE_GROUPS = ["20대", "30대", "40대", "50대", "60대", "70대", "80대 이상"]
HOUSEHOLD_SIZES = ["1", "2", "3", "4", "5+"]

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
    # first column is the grouping key; each flag is a condition counted per group
    flags: tuple[tuple[str, str], ...] = ()


PAY_MONTH = Param("pay_month", "month", required=True)
REGION = Param("region", "choice", tuple(REGIONS))
AGE_GROUP = Param("age_group", "choice", tuple(AGE_GROUPS))
HOUSEHOLD_SIZE = Param("household_size", "choice", tuple(HOUSEHOLD_SIZES))


def _scenario(key: str, params: tuple, group: str, flags: tuple) -> Scenario:
    names = tuple(name for name, _ in flags)
    return Scenario(key=key, params=params, columns=(group, "payments", *names),
                    counts=("payments", *names), flags=flags)


CATALOG = {s.key: s for s in (
    _scenario("livelihood_recheck", (PAY_MONTH, HOUSEHOLD_SIZE, AGE_GROUP), "region", (
        ("within", "income_ratio_band IN ('LE80', 'GT80_LE100')"),
        ("recheck", "income_ratio_band IN ('GT100_LE120', 'GT120')"),
        ("no_data", "income_ratio_band = 'NO_DATA'"),
    )),
    _scenario("obligor_asset_check", (PAY_MONTH, REGION, AGE_GROUP), "household_size", (
        ("no_obligor", "obligor_asset_band = 'NONE'"),
        ("within", "obligor_asset_band = 'WITHIN'"),
        ("over", "obligor_asset_band = 'OVER'"),
        ("no_data", "obligor_asset_band = 'NO_DATA'"),
    )),
    _scenario("paid_after_death", (PAY_MONTH, REGION), "age_group", (
        ("after_death", "death_month <> '' AND death_month < pay_month"),
        ("same_month", "death_month = pay_month"),
    )),
    _scenario("long_stay_abroad", (PAY_MONTH, AGE_GROUP), "region", (
        ("abroad", "abroad_days_band IN ('LE60', 'GT60')"),
        ("over_60", "abroad_days_band = 'GT60'"),
    )),
)}


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
    group = scenario.columns[0]
    where, args = ["pay_month = ?"], [_text(p["pay_month"])]
    for param in scenario.params:
        if param.kind == "choice" and p.get(param.name):
            where.append(f"{param.name} = ?")
            args.append(_text(p[param.name]))
    counts = ",\n         ".join(f"COUNT_IF({rule}) AS {name}" for name, rule in scenario.flags)
    return f"""
  SELECT {group},
         COUNT(*) AS payments,
         {counts}
  FROM {TABLE}
  WHERE run_id = '{run_id}'
    AND {" AND ".join(where)}
  GROUP BY {group}""", args


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
