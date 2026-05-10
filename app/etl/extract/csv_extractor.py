"""Leitura parametrizável de CSVs financeiros."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.etl.extract.protocols import ExtractionOutcome, FileSourceError


class CsvMarketExtractor:
    def __init__(self, csv_path: str | Path, encoding: str = "utf-8") -> None:
        self._path = Path(csv_path)
        self._encoding = encoding

    def read(self) -> ExtractionOutcome:
        if not self._path.exists():
            raise FileSourceError(f"Arquivo CSV ausente: {self._path}")
        try:
            df = pd.read_csv(self._path, encoding=self._encoding)
        except pd.errors.ParserError as exc:
            raise FileSourceError(f"CSV malformado: {self._path}") from exc
        return ExtractionOutcome(name=f"csv_local::{self._path.name}", frame=df)
