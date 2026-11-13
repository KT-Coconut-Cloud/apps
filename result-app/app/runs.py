from dataclasses import dataclass

from pydantic import ValidationError

from app.reports import AdequacyReview, ExportRecord, MacieResult
from app.storage import Store

STEPS = ["가명처리", "적정성 검토", "반출", "Macie 검사", "정제 버킷 적재"]


@dataclass
class RunSummary:
    run_id: str
    review: AdequacyReview | None
    export: ExportRecord | None
    macie: MacieResult | None
    broken: bool = False

    @property
    def reached(self) -> int:
        """Index of the last completed step (0-based), -1 if nothing is known."""
        if self.review is None:
            return -1
        if not self.review.passed:
            return 0
        if self.export is None or self.export.status != "exported":
            return 1
        if self.macie is None:
            return 2
        if any(f.classification == "quarantine" for f in self.macie.files):
            return 3
        return 4

    @property
    def status(self) -> str:
        if self.broken:
            return "기록 오류"
        if self.reached == 4:
            return "반출 완료"
        if self.reached == 3:
            return "격리"
        if self.reached in (0, 1):
            return "중단"
        return "진행 중"

    @property
    def failed_step(self) -> int | None:
        return self.reached + 1 if self.status in ("중단", "격리") else None

    @property
    def progress(self) -> str:
        if self.broken:
            return "보고서를 읽을 수 없음"
        if self.status == "격리":
            return "Macie 검사에서 탐지되어 격리"
        if self.failed_step is not None:
            return f"{STEPS[self.failed_step]}에서 중단"
        if self.reached == 4:
            return "정제 버킷 적재까지 완료"
        return f"{STEPS[self.reached + 1]} 대기"

    @property
    def rules_version(self) -> str | None:
        return self.review.rules_version if self.review else None

    @property
    def executed_at(self):
        if self.export:
            return self.export.executed_at
        return self.review.reviewed_at if self.review else None


def load_run(reports: Store, run_id: str) -> RunSummary:
    try:
        base = f"run_id={run_id}/"
        review = reports.read_json(base + "adequacy_review.json")
        export = reports.read_json(base + "export_record.json")
        macie = reports.read_json(base + "macie_result.json")
        return RunSummary(
            run_id=run_id,
            review=AdequacyReview(**review) if review else None,
            export=ExportRecord(**export) if export else None,
            macie=MacieResult(**macie) if macie else None,
        )
    except (ValidationError, ValueError):
        return RunSummary(run_id=run_id, review=None, export=None, macie=None, broken=True)


def load_runs(reports: Store) -> list[RunSummary]:
    return [load_run(reports, run_id) for run_id in reports.run_ids()]
