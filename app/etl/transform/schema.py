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


class SchemaValidationError(ValueError): ...


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


# --------------------------------------------------------------------------------------
# Regras de negócio por linha: linhas inválidas são separadas (quarentena), não carregadas.
# --------------------------------------------------------------------------------------

ISO_CURRENCY_PATTERN = r"^[A-Z]{3}$"
# Cotações e preços precisam ser estritamente positivos; posições podem ser negativas (short).
STRICTLY_POSITIVE_TYPES = frozenset({"FX_SPOT", "EQUITY_LAST"})
REJECTION_REASON_COLUMN = "rejection_reason"


@dataclass(frozen=True)
class ValidationResult:
    valid: pd.DataFrame
    rejected: pd.DataFrame

    @property
    def rejected_count(self) -> int:
        return len(self.rejected.index)


def _is_blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def validate_records(df: pd.DataFrame) -> ValidationResult:
    """Aplica regras de qualidade linha a linha e garante o contrato do schema canônico.

    Retorna as linhas válidas (prontas para o LOAD) e as rejeitadas com o motivo em
    `rejection_reason`. Colunas ausentes continuam sendo erro fatal (`SchemaValidationError`).
    """

    missing = [c.name for c in SCHEMA_PIPELINE_OUTPUT if c.name not in df.columns]
    if missing:
        raise SchemaValidationError(f"Colunas faltantes: {missing}")

    if df.empty:
        empty = df.copy()
        return ValidationResult(valid=empty, rejected=empty.assign(**{REJECTION_REASON_COLUMN: []}))

    working = df.copy()
    amounts = pd.to_numeric(working["amount"], errors="coerce")
    dates = pd.to_datetime(working["metric_date"], errors="coerce")
    currency = working["currency"].astype(str).str.strip().str.upper()

    checks: list[tuple[pd.Series, str]] = [
        (_is_blank(working["symbol"]), "symbol vazio"),
        (dates.isna(), "data inválida ou ausente"),
        (_is_blank(working["metric_type"]), "metric_type vazio"),
        (_is_blank(working["source_system"]), "source_system vazio"),
        (~currency.str.match(ISO_CURRENCY_PATTERN), "moeda fora do padrão ISO 4217"),
        (amounts.isna() | ~amounts.abs().lt(float("inf")), "valor não numérico ou infinito"),
        (
            working["metric_type"].isin(STRICTLY_POSITIVE_TYPES) & amounts.le(0),
            "preço/cotação deve ser positivo",
        ),
    ]

    reasons = pd.Series([[] for _ in range(len(working))], index=working.index, dtype=object)
    for mask, message in checks:
        for idx in mask[mask.fillna(True)].index:
            reasons.at[idx].append(message)

    is_valid = reasons.map(len).eq(0)
    valid = working.loc[is_valid].copy()
    valid["amount"] = amounts.loc[is_valid].astype(float)
    valid["metric_date"] = dates.loc[is_valid]
    valid["currency"] = currency.loc[is_valid]
    valid = valid.reset_index(drop=True)

    rejected = working.loc[~is_valid].copy()
    rejected[REJECTION_REASON_COLUMN] = reasons.loc[~is_valid].map("; ".join)
    rejected = rejected.reset_index(drop=True)

    assert_schema(valid, SCHEMA_PIPELINE_OUTPUT)
    return ValidationResult(valid=valid, rejected=rejected)
