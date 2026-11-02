"""Cria tabela núcleo de métricas financeiras."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001_financial_metrics"
down_revision = None


def _now_utc_default() -> sa.TextClause:
    # PostgreSQL é o alvo oficial; SQLite é aceito apenas para desenvolvimento local.
    if op.get_context().dialect.name == "postgresql":
        return sa.text("timezone('utc', now())")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("metric_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("extras", sa.JSON(), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("load_batch_id", sa.String(length=128), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=_now_utc_default(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "symbol",
            "metric_date",
            "metric_type",
            "source_system",
            name="uq_metric_natural_key",
        ),
    )
    op.create_index(
        "ix_financial_metrics_metric_date",
        "financial_metrics",
        ["metric_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_financial_metrics_metric_date", table_name="financial_metrics")
    op.drop_table("financial_metrics")
