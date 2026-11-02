"""Conversões fonte-específicas -> schema canônico do warehouse."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.etl.extract.protocols import ExtractionOutcome
from app.etl.transform.normalizers import (
    coerce_numeric_columns,
    drop_duplicates_stable,
    ensure_date,
)
from app.etl.transform.schema import SCHEMA_PIPELINE_OUTPUT

FX_SOURCE = "frankfurter_api"
CSV_PATTERN_SOURCE = "local_csv_markets"
XLSX_PATTERN_SOURCE = "local_xlsx_portfolio"

NATURAL_KEY = ["symbol", "metric_date", "metric_type", "source_system"]


def _empty_canonical_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[c.name for c in SCHEMA_PIPELINE_OUTPUT])


def _clean_symbol(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text or None


def _clean_currency(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value).strip().upper() or None


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
    if not rows:
        return _empty_canonical_frame()
    normalized = pd.DataFrame(rows)
    normalized["metric_date"] = pd.to_datetime(normalized["metric_date"], errors="coerce")
    return normalized


def build_from_market_csv(outcome: ExtractionOutcome, load_batch_id: str) -> pd.DataFrame:
    """Converte cotações de mercado. Valores inválidos NÃO são imputados: seguem para a
    validação (`validate_records`), que os coloca em quarentena com o motivo."""

    df = outcome.frame.copy()
    required = {"symbol", "trade_date", "currency", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV de mercado incompleto, faltando {sorted(missing)}")
    if df.empty:
        return _empty_canonical_frame()

    working = coerce_numeric_columns(df, ["open", "high", "low", "close", "volume"])
    working["trade_date"] = ensure_date(working, "trade_date")
    extras_cols = ("open", "high", "low", "volume")
    rows = []
    for _, row in working.iterrows():
        extras_payload: dict = {}
        for key in extras_cols:
            if key in row.index and pd.notna(row[key]):
                extras_payload[key] = float(row[key]) if key != "volume" else int(row[key])
        rows.append(
            {
                "symbol": _clean_symbol(row["symbol"]),
                "metric_date": row["trade_date"],
                "metric_type": "EQUITY_LAST",
                "currency": _clean_currency(row["currency"]),
                "amount": row["close"],
                "source_system": CSV_PATTERN_SOURCE,
                "load_batch_id": load_batch_id,
                "extras": extras_payload or None,
            },
        )
    normalized = pd.DataFrame(rows)
    normalized["metric_date"] = pd.to_datetime(normalized["metric_date"], errors="coerce")
    normalized["amount"] = pd.to_numeric(normalized["amount"], errors="coerce")
    return drop_duplicates_stable(normalized, subset=NATURAL_KEY)


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
    if working.empty:
        return _empty_canonical_frame()

    # Sem imputação: posição sem valor é rejeitada na validação (não inventamos saldo).
    working = coerce_numeric_columns(working, ["position_value"])
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
                "symbol": _clean_symbol(row["fund"]),
                "metric_date": row["_metric_date"],
                "metric_type": "POSITION_MARK",
                "currency": _clean_currency(row["base_currency"]),
                "amount": row["position_value"],
                "source_system": XLSX_PATTERN_SOURCE,
                "load_batch_id": load_batch_id,
                "extras": _pythonize_extras(extras_candidates) if extras_candidates else None,
            },
        )
    normalized = pd.DataFrame(rows)
    normalized["metric_date"] = pd.to_datetime(
        normalized["metric_date"], errors="coerce"
    ).dt.normalize()
    normalized["amount"] = pd.to_numeric(normalized["amount"], errors="coerce")
    return drop_duplicates_stable(normalized, subset=NATURAL_KEY)
