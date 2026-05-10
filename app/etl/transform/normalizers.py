"""Transformações declarativas reutilizáveis para DataFrames pandas."""

from __future__ import annotations

import pandas as pd


def drop_duplicates_stable(df: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    ordered = df.sort_values(by=subset).reset_index(drop=True)
    return ordered.drop_duplicates(subset=subset, keep="last")


def coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    copied = df.copy()
    for col in columns:
        if col not in copied.columns:
            continue
        copied[col] = pd.to_numeric(copied[col], errors="coerce")
    return copied


def fill_numeric_nulls_with_median(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    copied = df.copy()
    for col in columns:
        if col not in copied.columns:
            continue
        median_val = copied[col].median(skipna=True)
        if pd.isna(median_val):
            median_val = 0.0
        copied[col] = copied[col].fillna(median_val)
    return copied


def ensure_date(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(df[column], errors="coerce").dt.normalize()
