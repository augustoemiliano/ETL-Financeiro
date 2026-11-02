"""VALIDAÇÃO: regras de negócio por linha + contrato do schema canônico."""

from __future__ import annotations

import pandas as pd
import pytest

from app.etl.extract.protocols import ExtractionOutcome
from app.etl.transform.pipeline_builders import build_from_market_csv, build_from_portfolio_xlsx
from app.etl.transform.schema import (
    REJECTION_REASON_COLUMN,
    SchemaValidationError,
    validate_records,
)


def _row(**overrides: object) -> dict:
    base = {
        "symbol": "PETR4",
        "metric_date": "2024-01-02",
        "metric_type": "EQUITY_LAST",
        "currency": "BRL",
        "amount": 31.0,
        "source_system": "pytest",
        "load_batch_id": "b1",
        "extras": None,
    }
    base.update(overrides)
    return base


def test_valid_rows_pass_untouched() -> None:
    result = validate_records(pd.DataFrame([_row(), _row(symbol="VALE3", amount=62.9)]))
    assert len(result.valid) == 2
    assert result.rejected_count == 0
    assert pd.api.types.is_datetime64_any_dtype(result.valid["metric_date"])


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"symbol": None}, "symbol vazio"),
        ({"symbol": "   "}, "symbol vazio"),
        ({"metric_date": "não-é-data"}, "data inválida"),
        ({"currency": "REAL"}, "ISO 4217"),
        ({"amount": None}, "não numérico"),
        ({"amount": float("inf")}, "infinito"),
        ({"amount": -1.0}, "deve ser positivo"),
        ({"amount": 0.0, "metric_type": "FX_SPOT"}, "deve ser positivo"),
    ],
)
def test_invalid_rows_are_quarantined_with_reason(overrides: dict, reason: str) -> None:
    result = validate_records(pd.DataFrame([_row(), _row(**{"symbol": "BAD", **overrides})]))
    assert len(result.valid) == 1
    assert result.rejected_count == 1
    assert reason in result.rejected.iloc[0][REJECTION_REASON_COLUMN]


def test_multiple_reasons_are_accumulated() -> None:
    result = validate_records(pd.DataFrame([_row(currency="xx", amount=-5)]))
    reasons = result.rejected.iloc[0][REJECTION_REASON_COLUMN]
    assert "ISO 4217" in reasons and "positivo" in reasons


def test_negative_positions_are_allowed() -> None:
    """Posição vendida (short) é legítima; só preços/cotações precisam ser positivos."""
    result = validate_records(pd.DataFrame([_row(metric_type="POSITION_MARK", amount=-1000.0)]))
    assert result.rejected_count == 0


def test_currency_is_normalized_to_upper() -> None:
    result = validate_records(pd.DataFrame([_row(currency=" brl ")]))
    assert result.valid.iloc[0]["currency"] == "BRL"


def test_missing_columns_is_fatal() -> None:
    with pytest.raises(SchemaValidationError, match="Colunas faltantes"):
        validate_records(pd.DataFrame([{"symbol": "X"}]))


def test_empty_frame_is_valid() -> None:
    result = validate_records(pd.DataFrame(columns=list(_row().keys())))
    assert result.valid.empty and result.rejected.empty


def test_csv_with_missing_close_is_not_imputed() -> None:
    """Regressão: antes o preço ausente era preenchido com a mediana (dado inventado)."""
    csv = pd.DataFrame(
        {
            "symbol": ["AAA3", "BBB3", "CCC3"],
            "trade_date": ["2024-05-02"] * 3,
            "currency": ["BRL"] * 3,
            "close": [10.0, None, 30.0],
        }
    )
    normalized = build_from_market_csv(ExtractionOutcome("csv", csv), load_batch_id="b")
    result = validate_records(normalized)
    assert sorted(result.valid["symbol"]) == ["AAA3", "CCC3"]
    assert result.rejected.iloc[0]["symbol"] == "BBB3"


def test_xlsx_with_missing_position_is_not_imputed() -> None:
    xlsx = pd.DataFrame(
        {
            "fund": ["F1", "F2"],
            "position_value": [100.0, None],
            "base_currency": ["BRL", "BRL"],
            "ref_date": ["2024-04-01", "2024-04-01"],
        }
    )
    normalized = build_from_portfolio_xlsx(ExtractionOutcome("xlsx", xlsx), load_batch_id="b")
    result = validate_records(normalized)
    assert result.valid["symbol"].tolist() == ["F1"]
    assert result.rejected_count == 1
