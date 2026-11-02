"""Orquestra o pipeline completo preservando SOLID por camadas bem definidas."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging_config import get_logger
from app.etl.extract.csv_extractor import CsvMarketExtractor
from app.etl.extract.frankfurter_extractor import FrankfurterFxExtractor
from app.etl.extract.protocols import ExtractionError, ExtractionOutcome
from app.etl.extract.xlsx_extractor import XlsxPortfolioExtractor
from app.etl.load.warehouse_loader import WarehouseLoader
from app.etl.transform.pipeline_builders import (
    build_from_fx,
    build_from_market_csv,
    build_from_portfolio_xlsx,
)
from app.etl.transform.schema import validate_records
from app.utils.paths import ensure_dir

logger = get_logger(__name__)

Builder = Callable[[ExtractionOutcome, str], pd.DataFrame]


class PipelineError(RuntimeError):
    """Nenhuma fonte pôde ser processada — não há o que carregar."""


@dataclass(frozen=True)
class SourceJob:
    """Uma fonte de dados: como extrair + como converter para o schema canônico."""

    name: str
    extract: Callable[[], ExtractionOutcome]
    build: Builder


@dataclass(frozen=True)
class RunStats:
    batch_id: str
    inserts: int
    duplicates: int
    seconds: float
    rows_transformed: int
    rows_rejected: int = 0
    sources_ok: list[str] = field(default_factory=list)
    sources_failed: list[dict[str, str]] = field(default_factory=list)
    rejected_report_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def discover_files(directory: str | Path, pattern: str) -> list[Path]:
    """Lista arquivos de entrada de forma determinística (ignora temporários do Office `~$`)."""
    base = Path(directory)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(pattern) if p.is_file() and not p.name.startswith("~$"))


class ETLPipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        fx_extractor: FrankfurterFxExtractor | None = None,
    ) -> None:
        self._settings = settings
        self._fx_extractor = fx_extractor
        if self._fx_extractor is None and settings.fx_enabled:
            self._fx_extractor = FrankfurterFxExtractor(settings)

    def build_jobs(self) -> list[SourceJob]:
        """Monta as fontes: API FX + todos os CSV/XLSX encontrados nos diretórios configurados."""
        jobs: list[SourceJob] = []
        if self._fx_extractor is not None:
            jobs.append(SourceJob("fx_api", self._fx_extractor.fetch_latest, build_from_fx))

        csv_files = discover_files(self._settings.csv_input_dir, "*.csv")
        xlsx_files = discover_files(self._settings.xlsx_input_dir, "*.xlsx")
        if not csv_files:
            logger.warning("Nenhum CSV encontrado em %s", self._settings.csv_input_dir)
        if not xlsx_files:
            logger.warning("Nenhum XLSX encontrado em %s", self._settings.xlsx_input_dir)

        for path in csv_files:
            jobs.append(
                SourceJob(f"csv::{path.name}", CsvMarketExtractor(path).read, build_from_market_csv)
            )
        for path in xlsx_files:
            jobs.append(
                SourceJob(
                    f"xlsx::{path.name}",
                    XlsxPortfolioExtractor(path).read,
                    build_from_portfolio_xlsx,
                )
            )
        return jobs

    def run_full_pipeline(self, session: Session, jobs: list[SourceJob] | None = None) -> RunStats:
        batch_id = str(uuid4())
        started_at = perf_counter()
        jobs = self.build_jobs() if jobs is None else jobs
        if not jobs:
            raise PipelineError("Nenhuma fonte configurada (FX desabilitado e sem arquivos).")

        valid_frames: list[pd.DataFrame] = []
        rejected_frames: list[pd.DataFrame] = []
        sources_ok: list[str] = []
        sources_failed: list[dict[str, str]] = []

        # Falha isolada por fonte: uma fonte quebrada não impede a carga das demais.
        for job in jobs:
            try:
                outcome = job.extract()
                normalized = job.build(outcome, batch_id)
                result = validate_records(normalized)
            except ExtractionError as exc:
                logger.error("Fonte %s indisponível (extração): %s", job.name, exc)
                sources_failed.append({"source": job.name, "stage": "extract", "error": str(exc)})
                continue
            except ValueError as exc:
                logger.error("Fonte %s inválida (transformação/validação): %s", job.name, exc)
                sources_failed.append({"source": job.name, "stage": "transform", "error": str(exc)})
                continue

            if result.rejected_count:
                logger.warning(
                    "Fonte %s: %s linha(s) rejeitada(s) pela validação",
                    job.name,
                    result.rejected_count,
                )
                rejected_frames.append(result.rejected.assign(source_job=job.name))
            valid_frames.append(result.valid)
            sources_ok.append(job.name)
            logger.info("Fonte %s: %s linha(s) válida(s)", job.name, len(result.valid.index))

        if not sources_ok:
            raise PipelineError(
                "Todas as fontes falharam: "
                + "; ".join(f"{f['source']} ({f['error']})" for f in sources_failed)
            )

        non_empty = [f for f in valid_frames if not f.empty]
        consolidated = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
        rows_total = len(consolidated)
        inserts, duplicates = WarehouseLoader(session).persist(consolidated)

        rejected_path = self._write_rejected(rejected_frames, batch_id)
        rows_rejected = sum(len(f.index) for f in rejected_frames)

        elapsed = perf_counter() - started_at
        logger.info(
            "ETL batch %s finalizado — fontes ok=%s falhas=%s linhas válidas=%s rejeitadas=%s "
            "inserts=%s duplicidades=%s em %.3fs",
            batch_id,
            len(sources_ok),
            len(sources_failed),
            rows_total,
            rows_rejected,
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
            rows_rejected=rows_rejected,
            sources_ok=sources_ok,
            sources_failed=sources_failed,
            rejected_report_path=rejected_path,
        )

    def _write_rejected(self, frames: list[pd.DataFrame], batch_id: str) -> str | None:
        """Quarentena: linhas reprovadas vão para CSV auditável em vez de sumirem."""
        if not frames:
            return None
        try:
            path = ensure_dir(self._settings.reports_dir) / f"rejected_rows_{batch_id[:8]}.csv"
            rejected = pd.concat(frames, ignore_index=True)
            if "extras" in rejected.columns:
                rejected["extras"] = rejected["extras"].map(
                    lambda v: json.dumps(v, ensure_ascii=False, default=str) if v else None
                )
            rejected.to_csv(path, index=False)
        except OSError as exc:
            logger.error("Não foi possível gravar linhas rejeitadas: %s", exc)
            return None
        return str(path)
