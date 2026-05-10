"""Validação orientada ao contrato esperado antes do LOAD."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    nullable: bool = False


SCHEMA_PIPELINE_OUTPUT: list[ColumnSpec] = [
    ColumnSpec("symbol", nullable=False),
    ColumnSpec("metric_date", nullable=False),
    ColumnSpec("metric_type", nullable=False),
    ColumnSpec("currency", nullable=False),
    ColumnSpec("amount", nullable=False),
    ColumnSpec("source_system", nullable=False),
    ColumnSpec("load_batch_id", nullable=True),
    ColumnSpec("extras", nullable=True),
]


class SchemaValidationError(ValueError):
    ...


def assert_schema(df: pd.DataFrame, spec: list[ColumnSpec]) -> None:
    missing = [c.name for c in spec if c.name not in df.columns]
    if missing:
        raise SchemaValidationError(f"Colunas faltantes: {missing}")

    for column in spec:
        series = df[column.name]
        if column.nullable is False and series.isna().any():
            bad = series[series.isna()].index.tolist()
            snippet = bad[:15]
            suffix = "..." if len(bad) > 15 else ""
            raise SchemaValidationError(
                f"Coluna {column.name} possui valores nulos nas linhas {snippet}{suffix}",
            )
