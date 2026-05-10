"""Métricas derivadas utilizadas nos relatórios."""

from __future__ import annotations

import pandas as pd


def summarize_portfolio_performance(
    df: pd.DataFrame,
    value_col: str,
    group_col: str,
) -> pd.DataFrame:
    """Agregações de ranking quando existem valores absolutos repetíveis."""

    if df.empty:
        return pd.DataFrame(columns=["group", "total", "share_pct", "rank"])
    totals = df.groupby(group_col)[value_col].sum().rename("total")
    grand = totals.sum() or 1.0
    ranked = totals.sort_values(ascending=False).reset_index().rename(columns={group_col: "group"})
    ranked["share_pct"] = ranked["total"] / grand * 100
    ranked["rank"] = ranked["total"].rank(ascending=False, method="dense").astype(int)
    return ranked
