"""Local stand-in for the analysis-request and analysis-finalize Lambdas.

Reads data/<table>/run_id=<id>/ under data_dir with pandas instead of Athena and writes
the same files the real functions write, so the app can't tell the difference.
"""

import json
import threading
from pathlib import Path

import pandas as pd

from app.analyses import now
from app.catalog import CATALOG, TABLE, InvalidParams, Scenario, available, clean_params
from app.storage import RUN_ID


def _filter(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    df = df[df["pay_month"] == p["pay_month"]]
    for col in ("region", "age_group", "household_size", "gender"):
        if p.get(col):
            df = df[df[col] == p[col]]
    return df


def _count(df: pd.DataFrame, key: str, flags: dict, total: bool = True) -> pd.DataFrame:
    cols = (["payments"] if total else []) + list(flags)
    out = df.assign(payments=1, **{name: rule(df).astype(int) for name, rule in flags.items()})
    out = out.groupby(key)[cols].sum().astype(int)
    return out.reset_index().sort_values(key)


WITHIN = ("LE80", "GT80_LE100")
RECHECK = ("GT100_LE120", "GT120")
CHECK = {
    "within": lambda d: d["income_ratio_band"].isin(WITHIN),
    "recheck": lambda d: d["income_ratio_band"].isin(RECHECK),
    "no_data": lambda d: d["income_ratio_band"] == "NO_DATA",
}


def recheck_excess(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    df = _filter(df, p)
    df = df[df["income_ratio_band"].isin(RECHECK)]
    return _count(df, "region", {
        "recheck": lambda d: d["income_ratio_band"].isin(RECHECK),
        "over_100_120": lambda d: d["income_ratio_band"] == "GT100_LE120",
        "over_120": lambda d: d["income_ratio_band"] == "GT120",
    }, total=False)


def paid_after_death(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    return _count(_filter(df, p), "age_group", {
        "after_death": lambda d: (d["death_month"] != "") & (d["death_month"] < d["pay_month"]),
        "same_month": lambda d: d["death_month"] == d["pay_month"],
    })


QUERIES = {
    "livelihood_recheck": lambda df, p: _count(_filter(df, p), "region", CHECK),
    "recheck_by_household": lambda df, p: _count(_filter(df, p), "household_size", CHECK),
    "recheck_by_age": lambda df, p: _count(_filter(df, p), "age_group", CHECK),
    "recheck_excess": recheck_excess,
    "obligor_asset_check": lambda df, p: _count(_filter(df, p), "household_size", {
        "no_obligor": lambda d: d["obligor_asset_band"] == "NONE",
        "within": lambda d: d["obligor_asset_band"] == "WITHIN",
        "over": lambda d: d["obligor_asset_band"] == "OVER",
        "no_data": lambda d: d["obligor_asset_band"] == "NO_DATA",
    }),
    "paid_after_death": paid_after_death,
    "long_stay_abroad": lambda df, p: _count(_filter(df, p), "region", {
        "abroad": lambda d: d["abroad_days_band"].isin(["LE60", "GT60"]),
        "over_60": lambda d: d["abroad_days_band"] == "GT60",
    }),
}


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

    def _ready(self, run_id: str) -> bool:
        path = self.root / "results" / f"run_id={run_id}" / "manifest.json"
        return path.is_file() and json.loads(path.read_text(encoding="utf-8")).get("adequacy_passed") is True

    def _next_id(self) -> str:
        day = now().strftime("%Y%m%d")
        base = self.root / "results" / "requests"
        used = [int(p.name[-4:]) for p in base.glob(f"req-{day}-*")] if base.exists() else []
        return f"req-{day}-{max(used, default=0) + 1:04d}"

    def _data_path(self, run_id: str) -> Path:
        return self.root / "data" / TABLE / f"run_id={run_id}" / f"{TABLE}.csv"

    def _columns(self, run_id: str) -> set[str] | None:
        path = self._data_path(run_id)
        if not path.is_file():
            return None
        with path.open(encoding="utf-8") as f:
            return set(f.readline().strip().split(","))

    def submit(self, payload: dict) -> dict:
        scenario = CATALOG.get(payload.get("scenario"))
        if scenario is None:
            return {"error": "unknown_scenario", "detail": str(payload.get("scenario"))}
        try:
            params = clean_params(scenario, payload.get("params") or {})
        except InvalidParams as e:
            return {"error": "invalid_params", "detail": str(e)}
        run_id = payload.get("run_id") or ""
        if not RUN_ID.match(run_id) or not self._ready(run_id):
            return {"error": "run_not_ready", "detail": run_id}
        if scenario.key not in available(self._columns(run_id)):
            return {"error": "template_unavailable", "detail": scenario.key}
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
            data = pd.read_csv(self._data_path(request["run_id"]), dtype=str, keep_default_na=False)
            df = QUERIES[scenario.key](data, request["params"])
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
