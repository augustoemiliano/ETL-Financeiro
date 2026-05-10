"""Repositório: persistência e consultas sobre FinancialMetric."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.financial_metric import FinancialMetric
from app.utils.type_coercion import plain_python


class FinancialMetricRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_dataframe(self, df: pd.DataFrame, chunk_size: int = 500) -> tuple[int, int]:
        """UPSERT incremental (PostgreSQL ON CONFLICT), retorna (attempted inserts, duplicates)."""

        if df.empty:
            return (0, 0)

        required = {"symbol", "metric_date", "metric_type", "currency", "amount", "source_system"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Colunas obrigatórias ausentes: {sorted(missing)}")

        inserted = 0
        duplicates = 0
        df = df.copy()
        df["metric_date"] = pd.to_datetime(df["metric_date"]).dt.date

        for start in range(0, len(df), chunk_size):
            chunk = df.iloc[start : start + chunk_size]
            rows = [plain_python(r) for r in chunk.to_dict(orient="records")]
            stmt = pg_insert(FinancialMetric).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_metric_natural_key",
            )
            result = self._session.execute(stmt)
            rowcount = int(result.rowcount or 0)
            inserted += rowcount
            duplicates += len(rows) - rowcount
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return inserted, duplicates

    def bulk_insert_naive(self, rows: Iterable[dict]) -> int:
        """Inserção sequencial por linha para testes (evita nuances de bulk INSERT)."""

        count = 0
        batch = []
        for row in rows:
            batch.append(FinancialMetric(**row))
        self._session.add_all(batch)
        count = len(batch)
        self._session.flush()
        return count

    def summary_between(self, start: date, end: date) -> list[FinancialMetric]:
        stmt = (
            select(FinancialMetric)
            .where(FinancialMetric.metric_date >= start, FinancialMetric.metric_date <= end)
            .order_by(FinancialMetric.metric_date.asc())
        )
        return list(self._session.scalars(stmt))
