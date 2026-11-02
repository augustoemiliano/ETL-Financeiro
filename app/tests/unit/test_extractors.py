"""EXTRACT: leitura de CSV/XLSX locais e da API FX (com cliente HTTP dublê)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from requests.exceptions import ConnectionError

from app.etl.extract.csv_extractor import CsvMarketExtractor
from app.etl.extract.frankfurter_extractor import FrankfurterFxExtractor
from app.etl.extract.protocols import FileSourceError, SourceUnavailableError
from app.etl.extract.xlsx_extractor import XlsxPortfolioExtractor
from app.tests.conftest import SAMPLES_DIR


def test_csv_extractor_reads_sample_file() -> None:
    outcome = CsvMarketExtractor(SAMPLES_DIR / "sample_quotes.csv").read()
    assert outcome.name == "csv_local::sample_quotes.csv"
    assert {"symbol", "trade_date", "currency", "close"} <= set(outcome.frame.columns)
    assert len(outcome.frame) == 3


def test_csv_extractor_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileSourceError, match="ausente"):
        CsvMarketExtractor(tmp_path / "nao_existe.csv").read()


def test_csv_extractor_empty_file_raises(tmp_path: Path) -> None:
    empty = tmp_path / "vazio.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(FileSourceError, match="vazio"):
        CsvMarketExtractor(empty).read()


def test_xlsx_extractor_reads_sample_file() -> None:
    outcome = XlsxPortfolioExtractor(SAMPLES_DIR / "sample_portfolio.xlsx").read()
    assert {"fund", "position_value", "base_currency"} <= set(outcome.frame.columns)
    assert len(outcome.frame) == 3


def test_xlsx_extractor_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "carteira.xlsx"
    pd.DataFrame({"fund": ["X"], "position_value": [10.0], "base_currency": ["BRL"]}).to_excel(
        path, index=False
    )
    outcome = XlsxPortfolioExtractor(path).read()
    assert outcome.frame.iloc[0]["fund"] == "X"


def test_xlsx_extractor_corrupted_file_raises(tmp_path: Path) -> None:
    broken = tmp_path / "quebrado.xlsx"
    broken.write_bytes(b"isto nao e um xlsx")
    with pytest.raises(FileSourceError, match="Erro ao abrir"):
        XlsxPortfolioExtractor(broken).read()


class _StubHttp:
    def __init__(self, payload=None, exc: Exception | None = None) -> None:
        self.payload = payload
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url: str, params: dict | None = None):
        self.calls.append((url, params or {}))
        if self.exc:
            raise self.exc
        return self.payload


def test_frankfurter_extractor_builds_frame(make_settings) -> None:
    http = _StubHttp(
        payload={"base": "USD", "date": "2024-06-03", "rates": {"BRL": 5.1, "EUR": 0.92}}
    )
    settings = make_settings(FX_TARGET_CURRENCIES="brl, eur")
    outcome = FrankfurterFxExtractor(settings, http=http).fetch_latest()

    url, params = http.calls[0]
    assert url.endswith("/latest")
    assert params == {"from": "USD", "to": "BRL,EUR"}
    assert sorted(outcome.frame["pair"]) == ["USD/BRL", "USD/EUR"]
    assert outcome.frame["rate"].tolist() == [5.1, 0.92]


def test_frankfurter_extractor_wraps_http_failure(make_settings) -> None:
    http = _StubHttp(exc=ConnectionError("sem rede"))
    with pytest.raises(SourceUnavailableError, match="Falha na API FX"):
        FrankfurterFxExtractor(make_settings(), http=http).fetch_latest()


def test_frankfurter_extractor_rejects_payload_without_rates(make_settings) -> None:
    http = _StubHttp(payload={"base": "USD", "rates": {}})
    with pytest.raises(SourceUnavailableError, match="sem cotações"):
        FrankfurterFxExtractor(make_settings(), http=http).fetch_latest()
