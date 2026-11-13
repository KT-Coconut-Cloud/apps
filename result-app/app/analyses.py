import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.storage import REQUEST_ID, Store

KST = timezone(timedelta(hours=9))

STATUS_LABELS = {"running": "분석 중", "succeeded": "완료", "failed": "실패"}


def now() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


class AnalysisRequest(BaseModel):
    request_id: str
    run_id: str
    scenario: str
    params: dict
    purpose: str = ""
    requested_by: str
    requested_at: datetime


class Manifest(BaseModel):
    request_id: str
    run_id: str
    scenario: str
    params: dict
    status: Literal["succeeded", "failed"]
    finished_at: datetime
    rows: int = 0
    suppressed_cells: int = 0
    error: str | None = None


class AnalysisRecord(AnalysisRequest):
    """reports/analysis_requests/<id>.json, the audit copy for the security team."""

    status: Literal["running", "succeeded", "failed"] = "running"
    finished_at: datetime | None = None
    rows: int | None = None
    suppressed_cells: int | None = None
    error: str | None = None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


class Analysis:
    def __init__(self, request: AnalysisRequest, manifest: Manifest | None):
        self.request = request
        self.manifest = manifest

    @property
    def status(self) -> str:
        return self.manifest.status if self.manifest else "running"

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


def load_analysis(results: Store, request_id: str) -> Analysis | None:
    base = f"requests/{request_id}/"
    try:
        req = results.read_json(base + "request.json")
        if req is None:
            return None
        man = results.read_json(base + "manifest.json")
        return Analysis(AnalysisRequest(**req), Manifest(**man) if man else None)
    except (ValidationError, ValueError):
        return None


def list_analyses(results: Store, username: str, status: str | None = None) -> list[Analysis]:
    ids = sorted((i for i in results.list_dirs("requests") if REQUEST_ID.match(i)), reverse=True)
    items = (load_analysis(results, i) for i in ids)
    mine = [a for a in items if a and a.request.requested_by == username]
    return [a for a in mine if a.status == status] if status else mine


def list_records(reports: Store) -> list[AnalysisRecord]:
    records = []
    for name in reports.list_files("analysis_requests"):
        if not REQUEST_ID.match(name.removesuffix(".json")):
            continue
        try:
            data = reports.read_json(f"analysis_requests/{name}")
            records.append(AnalysisRecord(**data))
        except (ValidationError, ValueError, TypeError):
            continue
    return sorted(records, key=lambda r: r.request_id, reverse=True)


class LambdaBackend:
    def __init__(self, client, function_name: str):
        self.client = client
        self.function_name = function_name

    def submit(self, payload: dict) -> dict:
        resp = self.client.invoke(FunctionName=self.function_name, Payload=json.dumps(payload).encode())
        body = json.loads(resp["Payload"].read() or b"{}")
        if resp.get("FunctionError"):
            return {"error": "lambda_error", "detail": body.get("errorMessage", "")}
        return body
