"""Testes contra PostgreSQL (deduplicação SQL real). Rodar com Postgres ativo."""

from __future__ import annotations

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.etl.load.warehouse_loader import WarehouseLoader
from app.models.financial_metric import FinancialMetric


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
def postgres_session() -> Session:
    engine = _postgres_engine()
    FinancialMetric.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    session.execute(text("TRUNCATE financial_metrics RESTART IDENTITY CASCADE"))
    session.commit()

    try:
        yield session
    finally:
        session.close()


@pytest.mark.integration
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

    inserted_first, duplicate_first = loader.persist(canonical_row)
    inserted_second, duplicate_second = loader.persist(canonical_row)

    assert inserted_first >= 1
    assert duplicate_first == 0
    assert duplicate_second >= 1
    assert inserted_second == 0
