"""Métrica financeira consolidada para o star schema simplificado."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "metric_date",
            "metric_type",
            "source_system",
            name="uq_metric_natural_key",
        ),
        Index("ix_financial_metrics_metric_date", "metric_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date(), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    extras: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    load_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
