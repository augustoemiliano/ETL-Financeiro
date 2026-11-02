"""Pipeline ponta a ponta (extract → transform → validação → load → relatórios) em SQLite.

Roda em qualquer máquina, sem Docker. O mesmo fluxo é exercitado contra PostgreSQL real em
`test_warehouse_loader.py` (marcador `integration`, executado no CI com service container).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from app.etl.load.warehouse_loader import WarehouseLoader
from app.models.financial_metric import FinancialMetric
from app.services.etl_service import ETLPipelineService, PipelineError
from app.services.report_service import ReportingService
from app.tests.conftest import PROJECT_ROOT, FakeFxExtractor


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(FinancialMetric))


def _metric_row(**overrides: object) -> dict:
    row = {
        "symbol": "DUP/FX",
        "metric_date": "2025-01-05",
        "metric_type": "FX_SPOT",
        "currency": "USD",
        "amount": 1.11,
        "source_system": "pytest",
        "load_batch_id": "batch-alpha",
        "extras": {"k": "v"},
    }
    row.update(overrides)
    return row


# ----------------------------------------------------------------------------- LOAD


def test_loader_inserts_and_suppresses_duplicates(sqlite_session: Session) -> None:
    loader = WarehouseLoader(sqlite_session)
    frame = pd.DataFrame([_metric_row(), _metric_row(symbol="OTHER/FX")])

    assert loader.persist(frame) == (2, 0)
    assert loader.persist(frame) == (0, 2)
    assert _count(sqlite_session) == 2
    stored = sqlite_session.scalars(select(FinancialMetric).order_by(FinancialMetric.id)).first()
    assert stored.extras == {"k": "v"}


def test_loader_rolls_back_whole_batch_on_error(sqlite_session: Session) -> None:
    loader = WarehouseLoader(sqlite_session)
    # `chunk_size=1`: o 1º chunk entra, o 2º viola NOT NULL → nada pode ficar gravado.
    frame = pd.DataFrame([_metric_row(), _metric_row(symbol="X", currency=None)])

    with pytest.raises(Exception):  # noqa: B017 - erro do driver (IntegrityError)
        loader.persist(frame, chunk_size=1)
    assert _count(sqlite_session) == 0


def test_loader_rejects_frame_without_required_columns(sqlite_session: Session) -> None:
    with pytest.raises(ValueError, match="Colunas obrigatórias"):
        WarehouseLoader(sqlite_session).persist(pd.DataFrame([{"symbol": "X"}]))


# ------------------------------------------------------------------- PIPELINE (E2E)


def test_full_pipeline_loads_all_sources(make_settings, sqlite_session, fake_fx) -> None:
    service = ETLPipelineService(make_settings(), fx_extractor=fake_fx)
    stats = service.run_full_pipeline(sqlite_session)

    # samples: 3 FX + 3 (sample_quotes) + 3 válidas de sample_quotes_2024_02 + 3 posições
    assert stats.rows_transformed == 12
    assert stats.inserts == 12
    assert stats.rows_rejected == 3
    assert stats.sources_failed == []
    assert stats.sources_ok == [
        "fx_api",
        "csv::sample_quotes.csv",
        "csv::sample_quotes_2024_02.csv",
        "xlsx::sample_portfolio.xlsx",
    ]
    by_type = dict(
        sqlite_session.execute(
            select(FinancialMetric.metric_type, func.count()).group_by(FinancialMetric.metric_type)
        ).all()
    )
    assert by_type == {"FX_SPOT": 3, "EQUITY_LAST": 6, "POSITION_MARK": 3}

    # Linhas reprovadas ficam em quarentena auditável.
    with Path(stats.rejected_report_path).open(encoding="utf-8") as fh:
        rejected = list(csv.DictReader(fh))
    assert {r["symbol"] for r in rejected} == {"WEGE3", "ITUB4", "ABEV3"}
    assert all(r["rejection_reason"] for r in rejected)


def test_pipeline_is_idempotent(make_settings, sqlite_session, fake_fx) -> None:
    service = ETLPipelineService(make_settings(), fx_extractor=fake_fx)
    first = service.run_full_pipeline(sqlite_session)
    second = service.run_full_pipeline(sqlite_session)

    assert first.inserts == 12
    assert second.inserts == 0
    assert second.duplicates == 12
    assert _count(sqlite_session) == 12


def test_failed_source_does_not_block_the_others(make_settings, sqlite_session) -> None:
    service = ETLPipelineService(make_settings(), fx_extractor=FakeFxExtractor(fail=True))
    stats = service.run_full_pipeline(sqlite_session)

    assert stats.inserts == 9  # só arquivos locais
    assert stats.sources_failed[0]["source"] == "fx_api"
    assert stats.sources_failed[0]["stage"] == "extract"


def test_malformed_file_is_reported_as_transform_failure(
    make_settings, sqlite_session, copy_samples
) -> None:
    input_dir = copy_samples("sample_quotes.csv")
    (input_dir / "layout_errado.csv").write_text("ticker,preco\nPETR4,30\n", encoding="utf-8")
    settings = make_settings(CSV_INPUT_DIR=str(input_dir), XLSX_INPUT_DIR=str(input_dir))

    stats = ETLPipelineService(settings).run_full_pipeline(sqlite_session)

    assert stats.inserts == 3
    assert stats.sources_failed == [
        {
            "source": "csv::layout_errado.csv",
            "stage": "transform",
            "error": stats.sources_failed[0]["error"],
        }
    ]
    assert "faltando" in stats.sources_failed[0]["error"]


def test_pipeline_fails_when_every_source_fails(make_settings, sqlite_session, tmp_path) -> None:
    empty_dir = tmp_path / "vazio"
    empty_dir.mkdir()
    settings = make_settings(CSV_INPUT_DIR=str(empty_dir), XLSX_INPUT_DIR=str(empty_dir))
    service = ETLPipelineService(settings, fx_extractor=FakeFxExtractor(fail=True))

    with pytest.raises(PipelineError, match="Todas as fontes falharam"):
        service.run_full_pipeline(sqlite_session)
    assert _count(sqlite_session) == 0


def test_pipeline_without_any_source_configured(make_settings, sqlite_session, tmp_path) -> None:
    settings = make_settings(CSV_INPUT_DIR=str(tmp_path), XLSX_INPUT_DIR=str(tmp_path))
    with pytest.raises(PipelineError, match="Nenhuma fonte"):
        ETLPipelineService(settings).run_full_pipeline(sqlite_session)


# --------------------------------------------------------------------------- REPORTS


def test_reports_are_written_with_consolidated_data(make_settings, sqlite_session, fake_fx) -> None:
    settings = make_settings()
    stats = ETLPipelineService(settings, fx_extractor=fake_fx).run_full_pipeline(sqlite_session)
    payload = ReportingService(settings).export_snapshot(sqlite_session, batch_id=stats.batch_id)

    artifacts = payload["artifacts"]
    assert set(artifacts) == {
        "csv_metrics_path",
        "csv_source_summary_path",
        "csv_portfolio_ranking_path",
        "json_summary_path",
    }
    assert all(Path(p).exists() for p in artifacts.values())
    assert stats.batch_id[:8] in artifacts["csv_metrics_path"]

    metrics = pd.read_csv(artifacts["csv_metrics_path"])
    assert len(metrics) == 12  # histórico completo: dados de 2024 entram no relatório

    ranking = pd.read_csv(artifacts["csv_portfolio_ranking_path"])
    assert ranking["group"].tolist() == ["FIM_MULTISECTOR", "CDB_LC", "RF_PLUS"]
    assert ranking["share_pct"].sum() == pytest.approx(100, abs=0.01)

    summary = json.loads(Path(artifacts["json_summary_path"]).read_text(encoding="utf-8"))
    assert summary["statistics"]["records"] == 12
    assert summary["statistics"]["portfolio_total_by_currency"] == {"BRL": 245501.25}


def test_report_history_window_filters_old_data(make_settings, sqlite_session, fake_fx) -> None:
    settings = make_settings()
    ETLPipelineService(settings, fx_extractor=fake_fx).run_full_pipeline(sqlite_session)
    payload = ReportingService(settings).export_snapshot(
        sqlite_session, history_days=7, persist_files=False
    )
    assert payload["statistics"]["records"] == 0  # amostras são de 2024
    assert payload["artifacts"] == {}


def test_report_on_empty_database(make_settings, sqlite_session) -> None:
    payload = ReportingService(make_settings()).export_snapshot(sqlite_session)
    assert payload["statistics"]["records"] == 0
    assert pd.read_csv(payload["artifacts"]["csv_portfolio_ranking_path"]).empty


# --------------------------------------------------------------------------- MIGRATION


def test_alembic_migration_runs_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_fx
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert "financial_metrics" in inspector.get_table_names()
    unique = inspector.get_unique_constraints("financial_metrics")
    assert unique[0]["column_names"] == ["symbol", "metric_date", "metric_type", "source_system"]

    command.downgrade(cfg, "base")
    assert "financial_metrics" not in inspect(engine).get_table_names()
    engine.dispose()
