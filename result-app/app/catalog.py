"""Analysis templates the policy team can request.

The real list lives with the registered Athena queries; this copy must match it.
All templates read the single exported table livelihood_payment, one row per
livelihood benefit payment, and only the columns the pipeline exports.
"""

import re
from dataclasses import dataclass, field

TABLE = "livelihood_payment"

REGIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도",
]
AGE_GROUPS = ["20대", "30대", "40대", "50대", "60대", "70대", "80대 이상"]
HOUSEHOLD_SIZES = ["1", "2", "3", "4"]
GENDERS = ["남", "여"]

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
YEAR = re.compile(r"^20\d{2}$")


class InvalidParams(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    kind: str  # month | year | choice
    choices: tuple[str, ...] = ()
    required: bool = False
    default: str = ""


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    params: tuple[Param, ...]
    # columns of result.csv; count columns are the ones small-cell suppression applies to
    columns: tuple[str, ...]
    counts: tuple[str, ...] = field(default=())
    # blanked together with any suppressed count in the same row
    derived: tuple[str, ...] = field(default=())
    # how the result page reads the columns
    labels: dict = field(default_factory=dict)
    total: str = "payments"
    focus: str = ""
    basis: str = ""


PAY_MONTH = Param("pay_month", "지급월", "month", required=True, default="2025-12")
REGION = Param("region", "시도", "choice", tuple(REGIONS))
AGE_GROUP = Param("age_group", "연령대", "choice", tuple(AGE_GROUPS))
HOUSEHOLD_SIZE = Param("household_size", "가구원 수", "choice", tuple(HOUSEHOLD_SIZES))
GENDER = Param("gender", "성별", "choice", tuple(GENDERS))

# within: LE80, GT80_LE100 / recheck: GT100_LE120, GT120 / no_data: NO_DATA
CHECK_LABELS = {"payments": "지급 건", "within": "기준 이내", "recheck": "재확인 필요", "no_data": "자료 부족"}
CHECK_BASIS = "소득인정액이 그해 가구원 수별 생계급여 선정기준(기준 중위소득 32%)을 넘으면 재확인 필요, 해당 월 평가 자료가 없으면 자료 부족"

CATALOG = {
    "livelihood_recheck": Scenario(
        key="livelihood_recheck",
        title="시도별 생계급여 재확인 필요 지급 건",
        description="지급월의 소득인정액을 선정기준과 비교해, 기준을 넘은 지급 건을 시도별로 봅니다.",
        params=(PAY_MONTH, HOUSEHOLD_SIZE, AGE_GROUP),
        columns=("region", "payments", "within", "recheck", "no_data"),
        counts=("payments", "within", "recheck", "no_data"),
        labels={"region": "시도", **CHECK_LABELS},
        focus="recheck",
        basis=CHECK_BASIS,
    ),
    "recheck_by_household": Scenario(
        key="recheck_by_household",
        title="가구원 수별 재확인 필요 지급 건",
        description="같은 기준으로 가구원 수에 따라 재확인 필요 비율이 어떻게 다른지 봅니다.",
        params=(PAY_MONTH, REGION),
        columns=("household_size", "payments", "within", "recheck", "no_data"),
        counts=("payments", "within", "recheck", "no_data"),
        labels={"household_size": "가구원 수", **CHECK_LABELS},
        focus="recheck",
        basis=CHECK_BASIS,
    ),
    "recheck_by_age": Scenario(
        key="recheck_by_age",
        title="연령대별 재확인 필요 지급 건",
        description="같은 기준으로 수급 가구 대표자의 연령대에 따라 재확인 필요 비율을 봅니다.",
        params=(PAY_MONTH, REGION, GENDER),
        columns=("age_group", "payments", "within", "recheck", "no_data"),
        counts=("payments", "within", "recheck", "no_data"),
        labels={"age_group": "연령대", **CHECK_LABELS},
        focus="recheck",
        basis=CHECK_BASIS,
    ),
    "recheck_excess": Scenario(
        key="recheck_excess",
        title="재확인 필요 건의 기준 초과 정도",
        description="재확인 필요 건 중 선정기준을 20% 넘게 초과한 건을 시도별로 봅니다. 조사 우선순위를 정할 때 씁니다.",
        params=(PAY_MONTH, HOUSEHOLD_SIZE),
        columns=("region", "recheck", "over_100_120", "over_120"),
        counts=("recheck", "over_100_120", "over_120"),
        labels={"region": "시도", "recheck": "재확인 필요", "over_100_120": "100~120%", "over_120": "120% 초과"},
        total="recheck",
        focus="over_120",
        basis="소득인정액이 선정기준의 100% 초과 120% 이하면 100~120%, 120%를 넘으면 120% 초과",
    ),
}


def clean_params(scenario: Scenario, raw: dict) -> dict:
    out = {}
    for p in scenario.params:
        value = (raw.get(p.name) or "").strip() or None
        if value is None:
            if p.required:
                raise InvalidParams(f"{p.label}을(를) 입력하세요.")
        elif p.kind == "month" and not MONTH.match(value):
            raise InvalidParams(f"{p.label}은(는) YYYY-MM 형식이어야 합니다.")
        elif p.kind == "year" and not YEAR.match(value):
            raise InvalidParams(f"{p.label}은(는) 4자리 연도여야 합니다.")
        elif p.kind == "choice" and value not in p.choices:
            raise InvalidParams(f"{p.label} 값이 목록에 없습니다.")
        out[p.name] = value
    if out.get("from") and out.get("to") and out["from"] > out["to"]:
        raise InvalidParams("시작이 종료보다 늦습니다.")
    return out


def describe_params(scenario: Scenario | None, params: dict) -> str:
    if scenario is None:
        return ", ".join(f"{k}={v}" for k, v in params.items() if v)
    parts = []
    if params.get("from") or params.get("to"):
        parts.append(f"{params.get('from') or '처음'} ~ {params.get('to') or '마지막'}")
    for p in scenario.params:
        if p.kind == "choice":
            parts.append(params.get(p.name) or f"{p.label} 전체")
        elif p.name not in ("from", "to") and params.get(p.name):
            parts.append(f"{p.label} {params[p.name]}")
    return ", ".join(parts)
