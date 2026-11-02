"""Configura pytest e fixtures compartilhadas — credenciais nunca ficam aqui."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://etl_user:etl_pass@127.0.0.1:5435/etl_db",
)

from app.core.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.etl.extract.protocols import ExtractionOutcome, SourceUnavailableError  # noqa: E402
from app.models.financial_metric import FinancialMetric  # noqa: E402,F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    from app.core.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    yield
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture()
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Settings isoladas por teste: SQLite em arquivo temporário, diretórios temporários e
    retry sem espera (testes rápidos e determinísticos)."""

    def _factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'etl_test.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "logs"),
            "REPORTS_DIR": str(tmp_path / "reports"),
            "CSV_INPUT_DIR": str(SAMPLES_DIR),
            "XLSX_INPUT_DIR": str(SAMPLES_DIR),
            "FX_ENABLED": False,
            "HTTP_RETRY_ATTEMPTS": 3,
            "HTTP_RETRY_MIN_WAIT": 0,
            "HTTP_RETRY_MAX_WAIT": 0,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return _factory


@pytest.fixture()
def sqlite_session(make_settings: Callable[..., Settings]) -> Iterator[Session]:
    settings = make_settings()
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def copy_samples(tmp_path: Path) -> Callable[..., Path]:
    """Copia arquivos de exemplo para um diretório isolado (permite montar cenários)."""

    def _copy(*names: str) -> Path:
        target = tmp_path / "input"
        target.mkdir(exist_ok=True)
        for name in names:
            shutil.copy(SAMPLES_DIR / name, target / name)
        return target

    return _copy


class FakeFxExtractor:
    """Dublê da API Frankfurter: sem rede nos testes."""

    def __init__(self, *, fail: bool = False, fx_date: str = "2024-06-03") -> None:
        self.fail = fail
        self.fx_date = fx_date
        self.calls = 0

    def fetch_latest(self) -> ExtractionOutcome:
        self.calls += 1
        if self.fail:
            raise SourceUnavailableError("API FX fora do ar (simulado)")
        frame = pd.DataFrame(
            [
                {
                    "pair": f"USD/{quote}",
                    "fx_date": pd.Timestamp(self.fx_date).date(),
                    "base_currency": "USD",
                    "quote_currency": quote,
                    "rate": rate,
                }
                for quote, rate in {"BRL": 5.12, "EUR": 0.92, "GBP": 0.79}.items()
            ]
        )
        return ExtractionOutcome(name="fx_fake", frame=frame)


@pytest.fixture()
def fake_fx() -> FakeFxExtractor:
    return FakeFxExtractor()
