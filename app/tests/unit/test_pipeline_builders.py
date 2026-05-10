import pandas as pd
import pytest

from app.etl.extract.protocols import ExtractionOutcome
from app.etl.transform.pipeline_builders import (
    build_from_fx,
    build_from_market_csv,
    build_from_portfolio_xlsx,
)


def test_build_from_fx_standardizes_symbols() -> None:
    fx = pd.DataFrame(
        [
            {
                "pair": "USD/BRL",
                "fx_date": "2024-06-01",
                "base_currency": "USD",
                "quote_currency": "BRL",
                "rate": 5.12,
            }
        ]
    )
    outcome = ExtractionOutcome("fx_fixture", fx)
    result = build_from_fx(outcome, load_batch_id="batch-xyz")
    assert len(result) == 1
    assert result.iloc[0]["metric_type"] == "FX_SPOT"
    assert result.iloc[0]["symbol"] == "USD/BRL"
    assert result.iloc[0]["amount"] == pytest.approx(5.12)


def test_build_from_market_csv_cleans_numbers() -> None:
    csv = pd.DataFrame(
        {
            "symbol": ["vale3", "vale3"],
            "trade_date": ["2024-05-02", "2024-05-02"],
            "currency": ["brl", "brl"],
            "close": [10.5, 10.5],
        }
    )
    outcome = ExtractionOutcome("csv_fixture", csv)
    normalized = build_from_market_csv(outcome, load_batch_id="batch-xyz")
    assert normalized["symbol"].tolist() == ["VALE3"]
    assert normalized.iloc[0]["metric_type"] == "EQUITY_LAST"


def test_build_from_portfolio_xlsx_reads_positions() -> None:
    workbook = pd.DataFrame(
        {
            "fund": ["rf_xyz", "cr_multimercados"],
            "position_value": [15000.0, 78500.5],
            "base_currency": ["BRL", "BRL"],
            "ref_date": ["2024-04-01", "2024-04-02"],
            "custodian": ["BTG", "XP"],
        }
    )
    outcome = ExtractionOutcome("xlsx_fixture", workbook)
    normalized = build_from_portfolio_xlsx(outcome, load_batch_id="batch-xyz")
    assert set(normalized["symbol"]) >= {"RF_XYZ"}
    amount = normalized.loc[normalized["symbol"] == "RF_XYZ", "amount"].iloc[0]
    assert amount == pytest.approx(15000)
