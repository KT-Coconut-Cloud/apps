from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.analyses import KST, list_records
from app.auth import User, require_role
from app.catalog import CATALOG
from app.reports import CHECK_LABELS, MACIE_TYPE_LABELS
from app.runs import STEPS, load_run, load_runs
from app.storage import InvalidId, Store, check_run_id
from app.templating import templates

router = APIRouter(prefix="/security")


def reports_store(request: Request) -> Store:
    return request.app.state.reports


@router.get("/runs")
def runs(request: Request, user: User = Depends(require_role("security")), store: Store = Depends(reports_store)):
    items = load_runs(store)
    counts = Counter(r.status for r in items)
    return templates.TemplateResponse(
        request, "security/runs.html", {"user": user, "runs": items, "counts": counts, "steps": STEPS}
    )


@router.get("/runs/{run_id}")
def run_detail(
    request: Request, run_id: str, user: User = Depends(require_role("security")), store: Store = Depends(reports_store)
):
    try:
        check_run_id(run_id)
    except InvalidId:
        raise HTTPException(404)
    run = load_run(store, run_id)
    if run.review is None and not run.broken:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "security/run_detail.html", {"user": user, "run": run, "steps": STEPS})


def in_period(items, start: date | None, end: date | None):
    out = []
    for run in items:
        at = run.executed_at
        if at is None:
            continue
        day = at.astimezone(KST).date()
        if (start and day < start) or (end and day > end):
            continue
        out.append(run)
    return out


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.get("/failures")
def failures(
    request: Request,
    user: User = Depends(require_role("security")),
    store: Store = Depends(reports_store),
    start: str = Query(""),
    end: str = Query(""),
):
    today = datetime.now(KST).date()
    if not request.query_params:
        start = (today - timedelta(days=29)).isoformat()
        end = today.isoformat()
    start_day, end_day = parse_day(start), parse_day(end)
    items = in_period(load_runs(store), start_day, end_day)

    reasons: Counter = Counter()
    detected: Counter = Counter()
    by_rules: dict[str, dict] = {}
    for run in items:
        row = by_rules.setdefault(run.rules_version or "기록 없음", {"runs": 0, "aborted": 0, "quarantined": 0, "detected": 0})
        row["runs"] += 1
        row["aborted"] += run.status == "중단"
        row["quarantined"] += run.status == "격리"
        if run.review and not run.review.passed:
            for check in run.review.checks:
                if not check.passed:
                    reasons[CHECK_LABELS.get(check.item, check.item)] += 1
        if run.macie:
            for f in run.macie.files:
                for t in f.types:
                    detected[MACIE_TYPE_LABELS.get(t, t)] += 1
                    row["detected"] += 1

    context = {
        "user": user,
        "start": start_day.isoformat() if start_day else "",
        "end": end_day.isoformat() if end_day else "",
        "total": len(items),
        "aborted": sum(1 for r in items if r.status == "중단"),
        "quarantined": sum(1 for r in items if r.status == "격리"),
        "reasons": reasons.most_common(),
        "detected": detected.most_common(),
        "by_rules": sorted(by_rules.items(), reverse=True),
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "security/_failures_body.html", context)
    return templates.TemplateResponse(request, "security/failures.html", context)


@router.get("/analyses")
def analyses(request: Request, user: User = Depends(require_role("security")), store: Store = Depends(reports_store)):
    records = list_records(store)
    context = {
        "user": user,
        "records": records,
        "catalog": CATALOG,
        "total": len(records),
        "suppressed": sum(r.suppressed_cells or 0 for r in records),
        "with_suppression": sum(1 for r in records if r.suppressed_cells),
        "failed": sum(1 for r in records if r.status == "failed"),
    }
    return templates.TemplateResponse(request, "security/analyses.html", context)
