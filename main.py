"""Ponto único de entrada para CLI, scheduler e servidor HTTP."""

from __future__ import annotations

import argparse
import sys

import uvicorn
from app.core.config import get_settings
from app.core.logging_config import configure_logging, get_logger
from app.core.schedule_runner import attach_daily_etl, run_pending_forever
from app.db.session import get_engine, get_session_factory
from app.services.etl_service import ETLPipelineService
from app.services.report_service import ReportingService


def run_etl_cycle() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info("Execução manual do pipeline iniciada")
    get_engine(settings)
    SessionLocal = get_session_factory(settings)
    session = SessionLocal()
    try:
        pipeline = ETLPipelineService(settings)
        stats = pipeline.run_full_pipeline(session)
        ReportingService(settings).export_snapshot(session)
        logger.info(
            "Execução concluída: batch=%s linhas=%s inserts=%s duplicidades=%s tempo=%.3fs",
            stats.batch_id,
            stats.rows_transformed,
            stats.inserts,
            stats.duplicates,
            stats.seconds,
        )
    finally:
        session.close()


def scheduler_loop() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    if not settings.scheduler_enabled:
        logger.warning("SCHEDULER_ENABLED=false — encerrando sem loop (use apenas run-etl/api).")
        return

    attach_daily_etl(run_etl_cycle, settings.scheduler_run_time)

    logger.info(
        "Scheduler ativo (%s horário local). CTRL+C para encerrar.",
        settings.scheduler_run_time,
    )
    try:
        run_pending_forever(interval_seconds=15)
    except KeyboardInterrupt:
        logger.warning("Scheduler interrompido manualmente")


def serve_api() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.factory:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETL Financeiro Inteligente")
    sub = parser.add_subparsers(dest="command", required=True)

    run_once = sub.add_parser("run-etl", help="Executa ingestão/consolidação imediatamente")
    run_once.set_defaults(func=lambda _: run_etl_cycle())

    sched = sub.add_parser("scheduler", help="Loop diário usando schedule")
    sched.set_defaults(func=lambda _: scheduler_loop())

    api = sub.add_parser("api", help="Sobe servidor FastAPI/uvicorn")
    api.set_defaults(func=lambda _: serve_api())

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
