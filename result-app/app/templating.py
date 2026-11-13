from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.catalog import describe_params
from app.config import get_settings
from app.reports import CHECK_LABELS, MACIE_TYPE_LABELS

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def fmt_dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def fmt_num(value) -> str:
    try:
        return f"{value:,.0f}"
    except (TypeError, ValueError):
        return str(value)


templates.env.filters["dt"] = fmt_dt
templates.env.filters["num"] = fmt_num
templates.env.globals["CHECK_LABELS"] = CHECK_LABELS
templates.env.globals["MACIE_TYPE_LABELS"] = MACIE_TYPE_LABELS
templates.env.globals["session_minutes"] = lambda: get_settings().session_idle_minutes
templates.env.globals["poll_seconds"] = lambda: get_settings().poll_seconds
templates.env.globals["min_cell_size"] = lambda: get_settings().min_cell_size
templates.env.globals["params_text"] = describe_params


STATIC = Path(__file__).parent / "static"


def asset(path: str) -> str:
    # mtime in the query string so browsers drop a stale copy after a deploy
    try:
        return f"/static/{path}?v={int((STATIC / path).stat().st_mtime)}"
    except OSError:
        return f"/static/{path}"


templates.env.globals["asset"] = asset


def run_day(run_id: str) -> str:
    """20261112-01 -> 2026-11-12, the date the data was exported."""
    return f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}" if len(run_id) >= 8 else run_id


templates.env.globals["run_day"] = run_day
