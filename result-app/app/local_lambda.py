"""Local stand-in for the analysis-request and analysis-finalize Lambdas.

Reads data/run_id=<id>/ under data_dir with pandas instead of Athena and writes
the same files the real functions write, so the app can't tell the difference.
"""

import json
import threading
from pathlib import Path

import pandas as pd

from app.analyses import now
from app.catalog import CATALOG, InvalidParams, Scenario, clean_params
from app.storage import RUN_ID


def crisis_link_rate(t: dict[str, pd.DataFrame], p: dict) -> pd.DataFrame:
    df = t["crisis_signal"].merge(t["citizen"], on="citizen_id")
    df = df[(df["signal_month"] >= p["from"]) & (df["signal_month"] <= p["to"])]
    if p["crisis_type"]:
        df = df[df["crisis_type"] == p["crisis_type"]]
    if p["sigungu"]:
        df = df[df["sigungu"] == p["sigungu"]]

    keys = ["sigungu", "crisis_type"]
    households = df.groupby(keys)["citizen_id"].nunique().rename("households")
    linked = df[df["linked"] == 1].groupby(keys)["citizen_id"].nunique().rename("linked")
    out = pd.concat([households, linked], axis=1).fillna(0).astype(int)
    return out.reset_index().sort_values(keys)


def basic_living_status(t: dict[str, pd.DataFrame], p: dict) -> pd.DataFrame:
    df = t["benefit_payment"].merge(t["citizen"], on="citizen_id")
    df = df[(df["year"] >= int(p["from"])) & (df["year"] <= int(p["to"]))]
    if p["household_type"]:
        df = df[df["household_type"] == p["household_type"]]
    if p["benefit_type"]:
        df = df[df["benefit_type"] == p["benefit_type"]]

    keys = ["year", "household_type", "benefit_type"]
    out = df.groupby(keys).agg(recipients=("citizen_id", "nunique"), avg_payment=("monthly_amount", "mean"))
    out["avg_payment"] = out["avg_payment"].round(-2).astype(int)
    return out.reset_index().sort_values(keys)


QUERIES = {"crisis_link_rate": crisis_link_rate, "basic_living_status": basic_living_status}


def suppress(df: pd.DataFrame, scenario: Scenario, min_cell: int) -> tuple[pd.DataFrame, int]:
    """Blank counts from 1 to min_cell-1, plus derived columns on those rows."""
    df = df.copy()
    small = pd.DataFrame({c: (df[c] > 0) & (df[c] < min_cell) for c in scenario.counts})
    row_hit = small.any(axis=1)
    for c in scenario.counts:
        df[c] = df[c].astype("Int64").mask(small[c])
    for c in scenario.derived:
        df[c] = df[c].astype("Int64").mask(row_hit)
    hidden = int(small.to_numpy().sum()) + int(row_hit.sum()) * len(scenario.derived)
    return df, hidden


class LocalLambda:
    def __init__(self, root: Path, delay: float = 0, min_cell: int = 5):
        self.root = Path(root)
        self.delay = delay
        self.min_cell = min_cell
        self._lock = threading.Lock()

    def _request_dir(self, request_id: str) -> Path:
        return self.root / "results" / "requests" / request_id

    def _record_path(self, request_id: str) -> Path:
        return self.root / "reports" / "analysis_requests" / f"{request_id}.json"

    def _write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _next_id(self) -> str:
        day = now().strftime("%Y%m%d")
        base = self.root / "results" / "requests"
        used = [int(p.name[-4:]) for p in base.glob(f"req-{day}-*")] if base.exists() else []
        return f"req-{day}-{max(used, default=0) + 1:04d}"

    def submit(self, payload: dict) -> dict:
        scenario = CATALOG.get(payload.get("scenario"))
        if scenario is None:
            return {"error": "unknown_scenario", "detail": str(payload.get("scenario"))}
        try:
            params = clean_params(scenario, payload.get("params") or {})
        except InvalidParams as e:
            return {"error": "invalid_params", "detail": str(e)}
        run_id = payload.get("run_id") or ""
        if not RUN_ID.match(run_id) or not (self.root / "data" / f"run_id={run_id}").is_dir():
            return {"error": "run_not_ready", "detail": run_id}
        purpose = (payload.get("purpose") or "").strip()
        if not payload.get("requested_by") or not purpose or len(purpose) > 200:
            return {"error": "invalid_params", "detail": "requested_by, purpose"}

        with self._lock:
            request_id = self._next_id()
            request = {
                "request_id": request_id,
                "run_id": run_id,
                "scenario": scenario.key,
                "params": params,
                "purpose": purpose,
                "requested_by": payload["requested_by"],
                "requested_at": now().isoformat(),
            }
            self._write(self._request_dir(request_id) / "request.json", request)
        self._write(self._record_path(request_id), {**request, "status": "running"})

        if self.delay > 0:
            timer = threading.Timer(self.delay, self.finalize, [request])
            timer.daemon = True
            timer.start()
        else:
            self.finalize(request)
        return {"request_id": request_id, "status": "running"}

    def finalize(self, request: dict) -> None:
        scenario = CATALOG[request["scenario"]]
        out = self._request_dir(request["request_id"])
        result = {"status": "succeeded", "rows": 0, "suppressed_cells": 0, "error": None}
        try:
            tables = {
                name: pd.read_csv(self.root / "data" / f"run_id={request['run_id']}" / f"{name}.csv")
                for name in ("citizen", "crisis_signal", "benefit_payment")
            }
            df = QUERIES[scenario.key](tables, request["params"])
            df, hidden = suppress(df, scenario, self.min_cell)
            df[list(scenario.columns)].to_csv(out / "result.csv", index=False)
            result.update(rows=len(df), suppressed_cells=hidden)
        except Exception as e:
            result.update(status="failed", error=f"query_failed: {type(e).__name__}")

        finished = {**result, "finished_at": now().isoformat()}
        record_path = self._record_path(request["request_id"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self._write(record_path, {**record, **finished})
        manifest = {k: request[k] for k in ("request_id", "run_id", "scenario", "params")}
        self._write(out / "manifest.json", {**manifest, **finished})
