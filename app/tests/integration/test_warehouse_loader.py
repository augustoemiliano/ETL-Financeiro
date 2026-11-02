"""Testes contra PostgreSQL real (ON CONFLICT nativo). Rodam no CI com service container.

Localmente: `docker compose up -d postgres` e `pytest -m integration`. Sem Postgres
acessível na `DATABASE_URL`, os testes são pulados (skip), nunca falham.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.etl.load.warehouse_loader import WarehouseLoader
from app.models.financial_metric import FinancialMetric
from app.services.etl_service import ETLPipelineService
from app.services.report_service import ReportingService

pytestmark = pytest.mark.integration


def _postgres_engine():
    database_url = os.getenv("DATABASE_URL", "")
    if "postgresql" not in database_url:
        pytest.skip("integração Postgres requer DATABASE_URL com driver postgresql")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("Postgres inacessível neste ambiente (subir docker-compose).")

    return engine


@pytest.fixture()
def postgres_session() -> Iterator[Session]:
    engine = _postgres_engine()
    # No CI a tabela já vem do `alembic upgrade head`; create_all é no-op nesse caso.
    Base.metadata.create_all(bind=engine)

    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    session.execute(text("TRUNCATE financial_metrics RESTART IDENTITY CASCADE"))
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_warehouse_loader_suppresses_duplicates(postgres_session: Session) -> None:
    loader = WarehouseLoader(postgres_session)

    canonical_row = pd.DataFrame(
        [
            {
                "symbol": "DUP/FX",
                "metric_date": "2025-01-05",
                "metric_type": "FX_SPOT",
                "currency": "USD",
                "amount": 1.11,
                "source_system": "pytest",
                "load_batch_id": "batch-alpha",
                "extras": {},
            },
        ]
    )

    assert loader.persist(canonical_row) == (1, 0)
    assert loader.persist(canonical_row) == (0, 1)


def test_full_pipeline_against_postgres(postgres_session: Session, make_settings, fake_fx) -> None:
    settings = make_settings(DATABASE_URL=os.environ["DATABASE_URL"])
    service = ETLPipelineService(settings, fx_extractor=fake_fx)

    first = service.run_full_pipeline(postgres_session)
    second = service.run_full_pipeline(postgres_session)

    assert first.inserts == 12
    assert second.inserts == 0 and second.duplicates == 12
    total = postgres_session.scalar(select(func.count()).select_from(FinancialMetric))
    assert total == 12

    payload = ReportingService(settings).export_snapshot(postgres_session, persist_files=False)
    assert payload["statistics"]["records"] == 12
    assert payload["statistics"]["portfolio_total_by_currency"] == {"BRL": 245501.25}
