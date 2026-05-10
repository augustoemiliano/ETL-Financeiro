"""Conversões fonte-específicas -> schema canônico do warehouse."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.etl.extract.protocols import ExtractionOutcome
from app.etl.transform.normalizers import (
    coerce_numeric_columns,
    drop_duplicates_stable,
    ensure_date,
    fill_numeric_nulls_with_median,
)
from app.etl.transform.schema import SCHEMA_PIPELINE_OUTPUT, assert_schema

FX_SOURCE = "frankfurter_api"
CSV_PATTERN_SOURCE = "local_csv_markets"
XLSX_PATTERN_SOURCE = "local_xlsx_portfolio"


def _pythonize_extras(raw: dict) -> dict:
    sanitized: dict = {}
    for key, val in raw.items():
        if isinstance(val, pd.Timestamp):
            sanitized[key] = val.isoformat()
        elif hasattr(val, "item"):
            try:
                sanitized[key] = val.item()
            except Exception:
                sanitized[key] = val
        else:
            sanitized[key] = val
    return sanitized


def build_from_fx(outcome: ExtractionOutcome, load_batch_id: str) -> pd.DataFrame:
    df = outcome.frame.copy()
    rows = []
    for _, row in df.iterrows():
        ts = pd.Timestamp(row["fx_date"]).normalize()
        rows.append(
            {
                "symbol": row["pair"],
                "metric_date": ts,
                "metric_type": "FX_SPOT",
                "currency": row["quote_currency"],
                "amount": float(row["rate"]),
                "source_system": FX_SOURCE,
                "load_batch_id": load_batch_id,
                "extras": {"base_currency": row["base_currency"], "provider": FX_SOURCE},
            },
        )
    normalized = pd.DataFrame(rows)
    normalized = normalized.dropna(subset=["metric_date", "amount"])
    normalized["metric_date"] = pd.to_datetime(normalized["metric_date"])
    assert_schema(normalized, SCHEMA_PIPELINE_OUTPUT)
    return normalized


def build_from_market_csv(outcome: ExtractionOutcome, load_batch_id: str) -> pd.DataFrame:
    df = outcome.frame.copy()
    required = {"symbol", "trade_date", "currency", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV de mercado incompleto, faltando {sorted(missing)}")

    working = coerce_numeric_columns(df, ["close", "volume"])
    numeric_cols = [c for c in ["close", "volume"] if c in working.columns]
    if numeric_cols:
        working = fill_numeric_nulls_with_median(working, numeric_cols)
    working["trade_date"] = pd.to_datetime(ensure_date(working, "trade_date"))
    working = working.dropna(subset=["symbol", "trade_date", "close"])
    extras_cols = {"open": "open", "high": "high", "low": "low", "volume": "volume"}
    rows = []
    for _, row in working.iterrows():
        extras_payload: dict = {}
        for key, alias in extras_cols.items():
            if alias in row.index and pd.notna(row[alias]):
                extras_payload[key] = float(row[alias]) if key != "volume" else int(row[alias])
        rows.append(
            {
                "symbol": str(row["symbol"]).upper(),
                "metric_date": pd.to_datetime(row["trade_date"]),
                "metric_type": "EQUITY_LAST",
                "currency": str(row["currency"]).upper(),
                "amount": float(row["close"]),
                "source_system": CSV_PATTERN_SOURCE,
                "load_batch_id": load_batch_id,
                "extras": extras_payload or None,
            },
        )
    normalized = pd.DataFrame(rows)
    normalized["metric_date"] = normalized["metric_date"].dt.normalize()
    normalized = drop_duplicates_stable(
        normalized,
        subset=["symbol", "metric_date", "metric_type", "source_system"],
    )
    assert_schema(normalized, SCHEMA_PIPELINE_OUTPUT)
    return normalized


def build_from_portfolio_xlsx(outcome: ExtractionOutcome, load_batch_id: str) -> pd.DataFrame:
    df = outcome.frame.copy()
    required = {"fund", "position_value", "base_currency"}
    aliases = {"fund_symbol": "fund", "value": "position_value"}
    working = df.rename(
        columns={alias: target for alias, target in aliases.items() if alias in df.columns},
    ).copy()

    missing = required - set(working.columns)
    if missing:
        raise ValueError(f"XLSX incompleto, faltando {sorted(missing)}")

    working = coerce_numeric_columns(working, ["position_value"])
    working = fill_numeric_nulls_with_median(working, ["position_value"])
    if "ref_date" in working.columns:
        working["_metric_date"] = ensure_date(working, "ref_date")
    elif "snapshot_date" in working.columns:
        working["_metric_date"] = ensure_date(working, "snapshot_date")
    else:
        working["_metric_date"] = pd.to_datetime(datetime.now(UTC).date())

    rows = []
    excluded = {
        "fund",
        "position_value",
        "base_currency",
        "_metric_date",
        "ref_date",
        "snapshot_date",
    }
    for _, row in working.iterrows():
        extras_candidates = {}
        for key in sorted(working.columns.difference(excluded)):
            val = row[key]
            if pd.notna(val):
                extras_candidates[key] = val
        rows.append(
            {
                "symbol": str(row["fund"]).strip().upper(),
                "metric_date": pd.to_datetime(row["_metric_date"]),
                "metric_type": "POSITION_MARK",
                "currency": str(row["base_currency"]).upper(),
                "amount": float(row["position_value"]),
                "source_system": XLSX_PATTERN_SOURCE,
                "load_batch_id": load_batch_id,
                "extras": _pythonize_extras(extras_candidates) if extras_candidates else None,
            },
        )
    normalized = pd.DataFrame(rows)
    normalized["metric_date"] = pd.to_datetime(normalized["metric_date"]).dt.normalize()
    normalized = drop_duplicates_stable(
        normalized,
        subset=["symbol", "metric_date", "metric_type", "source_system"],
    )
    assert_schema(normalized, SCHEMA_PIPELINE_OUTPUT)
    return normalized
