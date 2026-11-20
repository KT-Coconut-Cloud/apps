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
    # k_anonymity is only in runs reviewed before rules v3.1
    item: Literal["direct_identifier", "tokenization", "generalization", "completeness", "k_anonymity"]
    passed: bool
    value: float | int | str | None = None
    reason: str | None = None


class AdequacyReview(BaseModel):
    run_id: str
    reviewed_at: datetime
    passed: bool
    rules_version: str | None = None
    rows: int | None = None
    checks: list[AdequacyCheck]


class MacieFile(BaseModel):
    key: str
    detected: bool
    types: list[str] = []
    classification: Literal["clean", "quarantine"]


class MacieResult(BaseModel):
    run_id: str
    scanned_at: datetime
    # ERROR: scan never finished (hash mismatch, failed job), files were held back unchecked
    verdict: Literal["PASS", "FAIL", "ERROR"] | None = None
    error: str | None = None
    files: list[MacieFile]

    @property
    def failed(self) -> bool:
        return self.verdict == "ERROR"


CHECK_LABELS = {
    "direct_identifier": "직접식별자 잔존",
    "tokenization": "토큰 형식",
    "generalization": "준식별자 일반화",
    "completeness": "빈 값",
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
