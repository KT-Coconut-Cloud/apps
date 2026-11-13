from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app.analyses import list_analyses, load_analysis
from app.auth import User, require_role
from app.catalog import CATALOG, InvalidParams, clean_params
from app.config import Settings, get_settings
from app.results import VIEWS
from app.storage import InvalidId, Store, check_request_id
from app.templating import templates

router = APIRouter(prefix="/policy")

ERRORS = {
    "unknown_scenario": "지원하지 않는 분석 템플릿입니다.",
    "invalid_params": "조건 값이 올바르지 않습니다.",
    "run_not_ready": "선택한 데이터셋은 아직 분석에 쓸 수 없습니다.",
    "no_purpose": "분석 목적을 200자 이내로 입력하세요.",
}


def results_store(request: Request) -> Store:
    return request.app.state.results


def ready_runs(store: Store) -> list[dict]:
    runs = []
    for run_id in store.run_ids():
        manifest = store.read_json(f"run_id={run_id}/manifest.json")
        if manifest and manifest.get("adequacy_passed"):
            runs.append(manifest)
    return runs


def own_analysis(store: Store, request_id: str, user: User):
    try:
        check_request_id(request_id)
    except InvalidId:
        raise HTTPException(404)
    analysis = load_analysis(store, request_id)
    if analysis is None or analysis.request.requested_by != user.username:
        raise HTTPException(404)
    return analysis


@router.get("/datasets")
def datasets(request: Request, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    return templates.TemplateResponse(request, "policy/datasets.html", {"user": user, "runs": ready_runs(store)})


def form_page(request: Request, user: User, store: Store, values: dict, error: str | None = None, status_code: int = 200):
    context = {
        "user": user,
        "runs": ready_runs(store),
        "catalog": CATALOG,
        "scenario": CATALOG.get(values.get("scenario")) or next(iter(CATALOG.values())),
        "values": values,
        "error": error,
    }
    return templates.TemplateResponse(request, "policy/new.html", context, status_code=status_code)


@router.get("/analyses/new")
def new_analysis(request: Request, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    return form_page(request, user, store, dict(request.query_params))


@router.get("/analyses/new/params")
def scenario_params(request: Request, scenario: str = "", user: User = Depends(require_role("policy"))):
    if scenario not in CATALOG:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "policy/_params.html", {"scenario": CATALOG[scenario], "values": {}})


@router.post("/analyses")
async def create_analysis(request: Request, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    form = await request.form()
    values = {k: str(v) for k, v in form.items()}
    scenario = CATALOG.get(values.get("scenario"))
    run_ids = {r["run_id"] for r in ready_runs(store)}

    if scenario is None:
        return form_page(request, user, store, values, ERRORS["unknown_scenario"], 422)
    if values.get("run_id") not in run_ids:
        return form_page(request, user, store, values, ERRORS["run_not_ready"], 422)
    try:
        params = clean_params(scenario, values)
    except InvalidParams as e:
        return form_page(request, user, store, values, str(e), 422)
    purpose = values.get("purpose", "").strip()
    if not purpose or len(purpose) > 200:
        return form_page(request, user, store, values, ERRORS["no_purpose"], 422)

    result = request.app.state.analysis.submit({
        "run_id": values["run_id"],
        "scenario": scenario.key,
        "params": params,
        "purpose": purpose,
        "requested_by": user.username,
    })
    if "error" in result:
        message = ERRORS.get(result["error"], "분석 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.")
        return form_page(request, user, store, values, message, 422)
    return RedirectResponse(f"/policy/analyses/{result['request_id']}", status_code=303)


@router.get("/analyses")
def analyses(request: Request, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    items = list_analyses(store, user.username)
    context = {"user": user, "items": items, "catalog": CATALOG, "polling": any(a.status == "running" for a in items)}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "policy/_analysis_list.html", context)
    return templates.TemplateResponse(request, "policy/analyses.html", context)


@router.get("/results")
def results(request: Request, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    items = list_analyses(store, user.username, status="succeeded")
    return templates.TemplateResponse(request, "policy/results.html", {"user": user, "items": items, "catalog": CATALOG})


@router.get("/analyses/{request_id}")
def analysis(
    request: Request,
    request_id: str,
    user: User = Depends(require_role("policy")),
    store: Store = Depends(results_store),
    settings: Settings = Depends(get_settings),
):
    item = own_analysis(store, request_id, user)
    if request.headers.get("HX-Request"):
        if item.status == "running":
            return templates.TemplateResponse(request, "policy/_pending.html", {"item": item})
        return Response(headers={"HX-Refresh": "true"})

    view = None
    if item.status == "succeeded":
        df = store.read_csv(f"requests/{request_id}/result.csv")
        if df is None:
            raise HTTPException(404)
        view = VIEWS[item.request.scenario](df)
    context = {
        "user": user,
        "item": item,
        "scenario": CATALOG.get(item.request.scenario),
        "view": view,
        "min_cell": settings.min_cell_size,
    }
    return templates.TemplateResponse(request, "policy/analysis.html", context)


@router.get("/analyses/{request_id}/result.csv")
def download(request_id: str, user: User = Depends(require_role("policy")), store: Store = Depends(results_store)):
    item = own_analysis(store, request_id, user)
    text = store.read_text(f"requests/{request_id}/result.csv") if item.status == "succeeded" else None
    if text is None:
        raise HTTPException(404)
    return Response(
        "﻿" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{request_id}.csv"'},
    )
