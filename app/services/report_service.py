"""Gera artefatos analíticos (CSV + JSON) a partir das métricas persistidas."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.etl.transform.metrics import summarize_portfolio_performance
from app.repositories.financial_repository import FinancialMetricRepository
from app.utils.paths import ensure_dir

_UNSET = object()

METRIC_COLUMNS = [
    "metric_date",
    "metric_type",
    "symbol",
    "currency",
    "amount",
    "source_system",
    "load_batch_id",
]


class ReportingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def export_snapshot(
        self,
        session: Session,
        *,
        persist_files: bool = True,
        history_days: int | None | object = _UNSET,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Monta o snapshot e (opcionalmente) grava os relatórios em `REPORTS_DIR`.

        Arquivos gerados (mesmo carimbo `<UTC>_<id>`):
        - `financial_metrics_*.csv`: todas as métricas da janela (dado consolidado);
        - `source_summary_*.csv`: contagem, período e valor médio por fonte/tipo;
        - `portfolio_ranking_*.csv`: posições mais recentes da carteira ranqueadas por valor;
        - `financial_summary_*.json`: estatísticas + rankings + caminhos dos artefatos.
        """

        if history_days is _UNSET:
            history_days = self._settings.report_history_days

        repo = FinancialMetricRepository(session)
        now = datetime.now(tz=UTC)
        window_end = now.date()
        window_start = window_end - timedelta(days=history_days) if history_days else None
        metrics = repo.summary_between(window_start, window_end if window_start else None)

        df = pd.DataFrame(
            [
                {
                    "metric_date": m.metric_date,
                    "metric_type": m.metric_type,
                    "symbol": m.symbol,
                    "currency": m.currency,
                    "amount": m.amount,
                    "source_system": m.source_system,
                    "load_batch_id": m.load_batch_id,
                }
                for m in metrics
            ],
            columns=METRIC_COLUMNS,
        )
        source_summary = self._source_summary(df)
        portfolio_ranking = self._portfolio_ranking(df)

        stamp = f"{now:%Y%m%dT%H%M%SZ}_{(batch_id or uuid4().hex)[:8]}"
        artifacts: dict[str, str] = {}
        if persist_files:
            reports_dir = Path(ensure_dir(self._settings.reports_dir))
            outputs = {
                "csv_metrics_path": (df, f"financial_metrics_{stamp}.csv"),
                "csv_source_summary_path": (source_summary, f"source_summary_{stamp}.csv"),
                "csv_portfolio_ranking_path": (portfolio_ranking, f"portfolio_ranking_{stamp}.csv"),
            }
            for key, (frame, filename) in outputs.items():
                path = reports_dir / filename
                frame.to_csv(path, index=False)
                artifacts[key] = str(path)
            artifacts["json_summary_path"] = str(reports_dir / f"financial_summary_{stamp}.json")

        payload = {
            "generated_at": now.isoformat(),
            "window": {
                "start": window_start.isoformat() if window_start else None,
                "end": window_end.isoformat(),
                "history_days": history_days,
            },
            "statistics": self._financial_headlines(df),
            "source_summary": source_summary.to_dict(orient="records"),
            "portfolio_ranking": portfolio_ranking.head(25).to_dict(orient="records"),
            "artifacts": artifacts,
        }

        if persist_files:
            with Path(artifacts["json_summary_path"]).open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)

        return payload

    @staticmethod
    def _source_summary(df: pd.DataFrame) -> pd.DataFrame:
        columns = [
            "source_system",
            "metric_type",
            "records",
            "symbols",
            "first_date",
            "last_date",
            "avg_amount",
        ]
        if df.empty:
            return pd.DataFrame(columns=columns)
        grouped = (
            df.groupby(["source_system", "metric_type"])
            .agg(
                records=("amount", "size"),
                symbols=("symbol", "nunique"),
                first_date=("metric_date", "min"),
                last_date=("metric_date", "max"),
                avg_amount=("amount", "mean"),
            )
            .reset_index()
        )
        grouped["avg_amount"] = grouped["avg_amount"].round(6)
        return grouped[columns]

    @staticmethod
    def _portfolio_ranking(df: pd.DataFrame) -> pd.DataFrame:
        """Ranking só faz sentido sobre posições (mesma natureza/moeda), nunca misturando
        cotações de câmbio e preços de ações. Usa a marcação mais recente de cada fundo."""
        columns = ["group", "currency", "total", "share_pct", "rank"]
        positions = df[df["metric_type"] == "POSITION_MARK"]
        if positions.empty:
            return pd.DataFrame(columns=columns)
        latest = positions.sort_values("metric_date").groupby("symbol", as_index=False).last()
        frames = []
        for currency, group in latest.groupby("currency"):
            ranked = summarize_portfolio_performance(group, value_col="amount", group_col="symbol")
            ranked.insert(1, "currency", currency)
            frames.append(ranked)
        result = pd.concat(frames, ignore_index=True)
        result["share_pct"] = result["share_pct"].round(4)
        return result[columns]

    @staticmethod
    def _financial_headlines(df: pd.DataFrame) -> dict[str, Any]:
        if df.empty:
            return {
                "records": 0,
                "distinct_symbols": 0,
                "distinct_sources": 0,
                "records_by_type": {},
                "portfolio_total_by_currency": {},
                "period": {"first_date": None, "last_date": None},
            }

        positions = df[df["metric_type"] == "POSITION_MARK"]
        latest_positions = (
            positions.sort_values("metric_date").groupby("symbol", as_index=False).last()
        )
        totals = latest_positions.groupby("currency")["amount"].sum().round(2)

        return {
            "records": len(df.index),
            "distinct_symbols": int(df["symbol"].nunique()),
            "distinct_sources": int(df["source_system"].nunique()),
            "records_by_type": {k: int(v) for k, v in df["metric_type"].value_counts().items()},
            "portfolio_total_by_currency": {k: float(v) for k, v in totals.items()},
            "period": {
                "first_date": str(df["metric_date"].min()),
                "last_date": str(df["metric_date"].max()),
            },
        }
