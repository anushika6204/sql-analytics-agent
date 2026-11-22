"""Pick and build a Plotly chart for a query result, when one makes sense."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

CHART_TYPES = ("bar", "line", "pie")


def to_dataframe(db_result: dict) -> pd.DataFrame:
    return pd.DataFrame(db_result["rows"], columns=db_result["columns"])


def _is_id(col: str) -> bool:
    c = col.lower()
    return c == "id" or c.endswith("_id")


def _measure_columns(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        if _is_id(c) or not pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]):
            continue
        out.append(c)
    return out


def _date_like(df: pd.DataFrame, col: str) -> bool:
    name = col.lower()
    if any(k in name for k in ("date", "month", "year", "day", "week", "time")):
        return True
    if df[col].dtype == object:
        parsed = pd.to_datetime(df[col].head(20), errors="coerce", format="mixed")
        return bool(len(parsed) and parsed.notna().all())
    return False


def _dimension_column(df: pd.DataFrame, measures: list[str]) -> Optional[str]:
    candidates = [c for c in df.columns if c not in measures and not _is_id(c)]
    for c in candidates:
        if _date_like(df, c):
            return c
    for c in candidates:
        if df[c].dtype == object:
            return c
    return candidates[0] if candidates else None


def suggest_chart(df: pd.DataFrame) -> Optional[dict]:
    """Return {'type', 'x', 'y'} for chartable numeric data, else None."""
    if df.empty or len(df) < 2:
        return None
    measures = _measure_columns(df)
    if not measures:
        return None
    x = _dimension_column(df, measures)
    if x is None:
        return None
    if _date_like(df, x):
        kind = "line"
    elif df[x].nunique() <= 6:
        kind = "pie"
    else:
        kind = "bar"
    return {"type": kind, "x": x, "y": measures[0]}


def build_figure(df: pd.DataFrame, spec: dict) -> Figure:
    x, y, kind = spec["x"], spec["y"], spec["type"]
    data = df.copy()
    if _date_like(data, x):
        parsed = pd.to_datetime(data[x], errors="coerce", format="mixed")
        if parsed.notna().all():
            data[x] = parsed
    if kind == "line":
        # A raw date column with many rows per day is noisy: aggregate per x.
        if data[x].duplicated().any():
            data = data.groupby(x, as_index=False)[y].sum()
        fig = px.line(data.sort_values(x), x=x, y=y, markers=len(data) <= 60)
    elif kind == "pie":
        fig = px.pie(data.groupby(x, as_index=False)[y].sum(), names=x, values=y)
    else:
        fig = px.bar(data.groupby(x, as_index=False)[y].sum(), x=x, y=y)
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), title=f"{y} by {x}")
    return fig
