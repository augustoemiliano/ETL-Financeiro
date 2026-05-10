"""Orquestra o pipeline completo preservando SOLID por camadas bem definidas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.etl.extract.csv_extractor import CsvMarketExtractor
from app.etl.extract.frankfurter_extractor import FrankfurterFxExtractor
from app.etl.extract.protocols import ExtractionError
from app.etl.extract.xlsx_extractor import XlsxPortfolioExtractor
from app.etl.load.warehouse_loader import WarehouseLoader
from app.etl.transform.pipeline_builders import (
    build_from_fx,
    build_from_market_csv,
    build_from_portfolio_xlsx,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class RunStats:
    batch_id: str
    inserts: int
    duplicates: int
    seconds: float
    rows_transformed: int


class ETLPipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        fx_extractor: FrankfurterFxExtractor | None = None,
    ) -> None:
        self._settings = settings
        self._fx_extractor = fx_extractor or FrankfurterFxExtractor(settings)

    def run_full_pipeline(self, session: Session) -> RunStats:
        batch_id = str(uuid4())
        started_at = perf_counter()
        normalized_frames: list[pd.DataFrame] = []
        inserts = duplicates = rows_total = 0

        loader = WarehouseLoader(session)

        try:
            fx = self._fx_extractor.fetch_latest()
            normalized_frames.append(build_from_fx(fx, batch_id))

            csv_path = Path(self._settings.csv_input_dir) / "sample_quotes.csv"
            csv_outcome = CsvMarketExtractor(csv_path).read()
            normalized_frames.append(build_from_market_csv(csv_outcome, batch_id))

            xlsx_path = Path(self._settings.xlsx_input_dir) / "sample_portfolio.xlsx"
            xlsx_outcome = XlsxPortfolioExtractor(xlsx_path).read()
            normalized_frames.append(build_from_portfolio_xlsx(xlsx_outcome, batch_id))
        except ExtractionError as exc:
            logger.error("Erro durante extração: %s", exc)
            raise
        except ValueError as exc:
            logger.error("Erro durante transformação/validação: %s", exc)
            raise

        if normalized_frames:
            consolidated = pd.concat(normalized_frames, ignore_index=True)
        else:
            consolidated = pd.DataFrame()

        rows_total = len(consolidated)
        inserts, duplicates = loader.persist(consolidated)

        elapsed = perf_counter() - started_at
        logger.info(
            "ETL batch %s finalizado — linhas consolidadas=%s inserts=%s duplicidades=%s em %.3fs",
            batch_id,
            rows_total,
            inserts,
            duplicates,
            elapsed,
        )
        return RunStats(
            batch_id=batch_id,
            inserts=inserts,
            duplicates=duplicates,
            seconds=elapsed,
            rows_transformed=rows_total,
        )
