"""Persistência transacional usando repositório (sem misturar com extract/transform)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.repositories.financial_repository import FinancialMetricRepository


class WarehouseLoader:
    def __init__(self, session: Session) -> None:
        self._repo = FinancialMetricRepository(session)

    def persist(self, df: pd.DataFrame, chunk_size: int = 500) -> tuple[int, int]:
        if df.empty:
            return (0, 0)
        clean = df.replace({np.nan: None}).copy()
        return self._repo.upsert_dataframe(clean, chunk_size=chunk_size)
