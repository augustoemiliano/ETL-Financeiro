"""Rotinas HTTP relacionadas aos pipelines."""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import Settings, get_settings
from app.services.etl_service import ETLPipelineService
from app.services.report_service import ReportingService

router = APIRouter(tags=["financial"])


@router.post("/etl/run", response_model=None)
def run_etl(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    service = ETLPipelineService(settings)
    stats = service.run_full_pipeline(db)
    reporters = ReportingService(settings)
    exports = reporters.export_snapshot(db)

    serialized = stats.__dict__.copy()
    serialized["artifacts"] = exports["artifacts"]
    return jsonable_encoder(serialized)


@router.get("/reports/snapshot")
def report_snapshot(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    reporters = ReportingService(settings)
    return jsonable_encoder(reporters.export_snapshot(db))
