"""Leitura parametrizável de planilhas XLSX."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.etl.extract.protocols import ExtractionOutcome, FileSourceError


class XlsxPortfolioExtractor:
    def __init__(
        self,
        xlsx_path: str | Path,
        *,
        sheet_name: str | int = 0,
        engine: str = "openpyxl",
    ) -> None:
        self._path = Path(xlsx_path)
        self._sheet_name = sheet_name
        self._engine = engine

    def read(self) -> ExtractionOutcome:
        if not self._path.exists():
            raise FileSourceError(f"Planilha ausente: {self._path}")
        try:
            df = pd.read_excel(
                self._path,
                sheet_name=self._sheet_name,
                engine=self._engine,
            )
        except Exception as exc:
            raise FileSourceError(f"Erro ao abrir planilha: {self._path}") from exc
        return ExtractionOutcome(name=f"xlsx_local::{self._path.name}", frame=df)
