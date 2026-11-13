"""Analysis templates the policy team can request.

The real list lives with the registered Athena queries; this copy must match it.
"""

import re
from dataclasses import dataclass, field

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


CATALOG = {
    "crisis_link_rate": Scenario(
        key="crisis_link_rate",
        title="위기가구 지원 연계율",
        description="기간 안에 위기정보가 들어온 가구 중 복지 서비스로 연계된 비율을 시군구, 위기정보 유형별로 봅니다.",
        params=(
            Param("from", "시작 월", "month", required=True),
            Param("to", "종료 월", "month", required=True),
            Param("crisis_type", "위기정보 유형", "choice", tuple(CRISIS_TYPES)),
            Param("sigungu", "시군구", "choice", tuple(SIGUNGU)),
        ),
        columns=("sigungu", "crisis_type", "households", "linked"),
        counts=("households", "linked"),
    ),
    "basic_living_status": Scenario(
        key="basic_living_status",
        title="기초생활보장 수급 현황",
        description="연도, 가구 유형, 급여 종류별 수급자 수와 1인당 월평균 지급액을 봅니다.",
        params=(
            Param("from", "시작 연도", "year", required=True, default="2023"),
            Param("to", "종료 연도", "year", required=True, default="2025"),
            Param("household_type", "가구 유형", "choice", tuple(HOUSEHOLD_TYPES)),
            Param("benefit_type", "급여 종류", "choice", tuple(BENEFIT_TYPES)),
        ),
        columns=("year", "household_type", "benefit_type", "recipients", "avg_payment"),
        counts=("recipients",),
        derived=("avg_payment",),
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
    return ", ".join(parts)
