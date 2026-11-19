"""Turn result.csv into what the result template draws.

Suppressed cells arrive empty. Totals and rates use only the cells that are shown.
"""

from functools import partial

import pandas as pd

from app.catalog import CATALOG, Scenario

# grouping values that need a readable name on screen
VALUE_LABELS = {"unknown": "자료 없음"}


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _rate(part, whole):
    if part is None or whole is None or pd.isna(part) or pd.isna(whole) or not whole:
        return None
    return round(part / whole * 100, 1)


def _label(value) -> str:
    value = str(value)
    if value.isdigit():
        return f"{value}인"
    return VALUE_LABELS.get(value, value)


def check_view(scenario: Scenario, df: pd.DataFrame) -> dict:
    key, total, focus = scenario.columns[0], scenario.total, scenario.focus
    df = df.assign(**{key: [_label(v) for v in df[key]]})
    df = df.assign(rate=[_rate(f, t) for f, t in zip(df[focus], df[total])])

    # the rate only uses rows where both numbers are shown
    shown = df.dropna(subset=[total, focus])
    rate = _rate(shown[focus].sum(), shown[total].sum())
    chart = shown[shown[total] > 0].sort_values("rate")
    return {
        "key": key,
        "summary": {"payments": int(df[total].sum()), "flagged": int(df[focus].sum()), "rate": rate},
        "chart": {"labels": chart[key].tolist(), "data": chart["rate"].tolist()},
        "rows": _records(df),
    }


VIEWS = {key: partial(check_view, s) for key, s in CATALOG.items()}
