"""Integrações externas isoladas atrás de contratos estáveis."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


class ExtractionError(Exception):
    ...


class SourceUnavailableError(ExtractionError):
    ...


class FileSourceError(ExtractionError):
    ...


@dataclass(frozen=True)
class ExtractionOutcome:
    name: str
    frame: pd.DataFrame
