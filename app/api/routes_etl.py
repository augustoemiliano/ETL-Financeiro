"""Rotinas HTTP relacionadas aos pipelines."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import Settings, get_settings
from app.core.logging_config import get_logger
from app.services.etl_service import ETLPipelineService, PipelineError
from app.services.report_service import ReportingService

router = APIRouter(tags=["financial"])
logger = get_logger(__name__)


@router.post("/etl/run", response_model=None)
def run_etl(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    try:
        stats = ETLPipelineService(settings).run_full_pipeline(db)
    except PipelineError as exc:
        # Todas as fontes falharam: problema a montante, não do cliente HTTP.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Falha ao persistir o lote")
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc

    exports = ReportingService(settings).export_snapshot(db, batch_id=stats.batch_id)
    serialized = stats.to_dict()
    serialized["artifacts"] = exports["artifacts"]
    return jsonable_encoder(serialized)


@router.get("/reports/snapshot")
def report_snapshot(
    history_days: int | None = Query(
        default=None, ge=1, description="Janela em dias; omitido = REPORT_HISTORY_DAYS"
    ),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    reporters = ReportingService(settings)
    if history_days is None:
        return jsonable_encoder(reporters.export_snapshot(db))
    return jsonable_encoder(reporters.export_snapshot(db, history_days=history_days))
