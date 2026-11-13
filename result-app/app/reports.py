from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ExportFile(BaseModel):
    key: str
    rows: int
    sha256: str


class ExportRecord(BaseModel):
    run_id: str
    executed_at: datetime
    status: Literal["exported", "aborted"]
    files: list[ExportFile] = []


class AdequacyCheck(BaseModel):
    item: Literal["direct_identifier", "generalization", "k_anonymity"]
    passed: bool
    value: float | int | str | None = None
    reason: str | None = None


class AdequacyReview(BaseModel):
    run_id: str
    reviewed_at: datetime
    passed: bool
    rules_version: str | None = None
    checks: list[AdequacyCheck]


class MacieFile(BaseModel):
    key: str
    detected: bool
    types: list[str] = []
    classification: Literal["clean", "quarantine"]


class MacieResult(BaseModel):
    run_id: str
    scanned_at: datetime
    files: list[MacieFile]


CHECK_LABELS = {
    "direct_identifier": "직접식별자 잔존",
    "generalization": "준식별자 일반화",
    "k_anonymity": "k-익명성",
}

# managed identifiers have no Korean formats, so the custom ones carry most of the load
MACIE_TYPE_LABELS = {
    "KR_RRN": "주민등록번호",
    "KR_MOBILE_PHONE": "휴대전화 번호",
    "KR_ROAD_ADDRESS": "도로명 주소",
    "PHONE_NUMBER": "전화번호",
    "KOREA_RESIDENT_REGISTRATION_NUMBER": "주민등록번호",
    "EMAIL_ADDRESS": "이메일",
    "NAME": "이름",
    "ADDRESS": "주소",
}
