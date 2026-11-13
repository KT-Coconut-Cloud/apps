"""Turn result.csv into what the result templates draw.

Suppressed cells arrive empty. Totals and rates use only the cells that are shown.
"""

import pandas as pd


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _rate(part, whole):
    if part is None or whole is None or pd.isna(part) or pd.isna(whole) or not whole:
        return None
    return round(part / whole * 100, 1)


def crisis_link_rate(df: pd.DataFrame) -> dict:
    df = df.assign(rate=[_rate(l, h) for l, h in zip(df["linked"], df["households"])])
    shown = df.dropna(subset=["households", "linked"])

    by_type = shown.groupby("crisis_type")[["households", "linked"]].sum()
    by_type["rate"] = (by_type["linked"] / by_type["households"] * 100).round(1)
    by_type = by_type.sort_values("rate")

    households = int(shown["households"].sum())
    linked = int(shown["linked"].sum())
    return {
        "summary": {"households": households, "linked": linked, "rate": _rate(linked, households)},
        "chart": {"labels": by_type.index.tolist(), "data": by_type["rate"].tolist()},
        "rows": _records(df.sort_values(["sigungu", "crisis_type"])),
    }


def basic_living_status(df: pd.DataFrame) -> dict:
    shown = df.dropna(subset=["recipients"])
    years = sorted(int(y) for y in df["year"].unique())
    pivot = shown.groupby(["benefit_type", "year"])["recipients"].sum()
    series = [
        {"name": b, "data": [int(pivot.get((b, y), 0)) for y in years]}
        for b in sorted(shown["benefit_type"].unique())
    ]
    latest = shown[shown["year"] == years[-1]] if years else shown
    return {
        "summary": {"latest_year": years[-1] if years else None, "recipients": int(latest["recipients"].sum())},
        "chart": {"years": [str(y) for y in years], "series": series},
        "rows": _records(df.sort_values(["year", "household_type", "benefit_type"], ascending=[False, True, True])),
    }


VIEWS = {"crisis_link_rate": crisis_link_rate, "basic_living_status": basic_living_status}
