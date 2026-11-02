"""API FastAPI com banco SQLite temporário (sem rede: fonte FX desabilitada)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_db
from app.api.factory import create_app
from app.core.config import get_settings
from app.db.base import Base


@pytest.fixture()
def client_factory(make_settings):
    def _build(**overrides: object) -> TestClient:
        settings = make_settings(**overrides)
        engine = create_engine(settings.database_url)
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False)

        def _db() -> Iterator:
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_db] = _db
        return TestClient(app)

    return _build


def test_health(client_factory) -> None:
    response = client_factory().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_dashboard_is_served(client_factory) -> None:
    response = client_factory().get("/")
    assert response.status_code == 200
    assert "ETL Financeiro" in response.text


def test_run_etl_endpoint_loads_and_reports(client_factory) -> None:
    client = client_factory()
    body = client.post("/etl/run").json()

    assert body["inserts"] == 9  # CSV + XLSX de exemplo (FX desabilitado no teste)
    assert body["rows_rejected"] == 3
    assert body["sources_failed"] == []
    assert "csv_metrics_path" in body["artifacts"]

    snapshot = client.get("/reports/snapshot").json()
    assert snapshot["statistics"]["records"] == 9
    assert [r["group"] for r in snapshot["portfolio_ranking"]][0] == "FIM_MULTISECTOR"


def test_snapshot_accepts_history_window(client_factory) -> None:
    client = client_factory()
    client.post("/etl/run")
    snapshot = client.get("/reports/snapshot", params={"history_days": 7}).json()
    assert snapshot["window"]["history_days"] == 7
    assert snapshot["statistics"]["records"] == 0


def test_run_etl_returns_502_when_no_source_is_available(client_factory, tmp_path) -> None:
    client = client_factory(CSV_INPUT_DIR=str(tmp_path), XLSX_INPUT_DIR=str(tmp_path))
    response = client.post("/etl/run")
    assert response.status_code == 502
    assert "Nenhuma fonte" in response.json()["detail"]
