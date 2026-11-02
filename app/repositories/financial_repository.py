"""Repositório: persistência e consultas sobre FinancialMetric."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.financial_metric import FinancialMetric
from app.utils.type_coercion import plain_python

# Mesmas colunas da constraint `uq_metric_natural_key`.
NATURAL_KEY = ["symbol", "metric_date", "metric_type", "source_system"]


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
        insert_fn = self._dialect_insert()

        # Toda a carga do lote é uma única transação: qualquer falha desfaz tudo.
        try:
            for start in range(0, len(df), chunk_size):
                chunk = df.iloc[start : start + chunk_size]
                rows = [plain_python(r) for r in chunk.to_dict(orient="records")]
                stmt = insert_fn(FinancialMetric).values(rows)
                stmt = stmt.on_conflict_do_nothing(index_elements=NATURAL_KEY)
                result = self._session.execute(stmt)
                rowcount = int(result.rowcount or 0)
                inserted += rowcount
                duplicates += len(rows) - rowcount
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return inserted, duplicates

    def _dialect_insert(self):
        """PostgreSQL é o destino oficial; SQLite é suportado para dev/testes locais."""
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            return pg_insert
        if dialect == "sqlite":
            return sqlite_insert
        raise NotImplementedError(f"Dialeto não suportado para UPSERT: {dialect}")

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
