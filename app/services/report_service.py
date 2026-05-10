"""Gera artefatos analíticos a partir das métricas persistidas."""

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


class ReportingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def export_snapshot(
        self,
        session: Session,
        *,
        persist_files: bool = True,
        history_days: int = 7,
    ) -> dict[str, Any]:
        repo = FinancialMetricRepository(session)

        now = datetime.now(tz=UTC)
        window_end = now.date()
        window_start = window_end - timedelta(days=history_days)
        metrics = repo.summary_between(window_start, window_end)

        df = pd.DataFrame(
            [
                {
                    "symbol": m.symbol,
                    "metric_date": m.metric_date,
                    "metric_type": m.metric_type,
                    "currency": m.currency,
                    "amount": m.amount,
                    "source_system": m.source_system,
                    "extras": m.extras,
                }
                for m in metrics
            ],
        )
        ranking = summarize_portfolio_performance(df, value_col="amount", group_col="symbol")
        headline = self._financial_headlines(df)

        stamp = uuid4().hex[:8]
        reports_dir = Path(ensure_dir(self._settings.reports_dir))

        artifact_paths = {"json_summary_path": str(reports_dir / f"financial_summary_{stamp}.json")}
        if not ranking.empty and persist_files:
            csv_path = reports_dir / f"financial_ranking_{stamp}.csv"
            ranking.to_csv(csv_path, index=False)
            artifact_paths["csv_ranking_path"] = str(csv_path)

        payload = {
            "generated_at": now.isoformat(),
            "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "statistics": headline,
            "ranking": ranking.head(25).to_dict(orient="records"),
            "artifacts": artifact_paths,
        }

        if persist_files:
            with Path(payload["artifacts"]["json_summary_path"]).open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)

        return payload

    def _financial_headlines(self, df: pd.DataFrame) -> dict[str, Any]:
        if df.empty:
            return {
                "distinct_symbols": 0,
                "distinct_sources": 0,
                "gross_positive_exposure": 0.0,
                "gross_negative_exposure": 0.0,
                "median_amount": None,
                "records": 0,
            }

        positives = df.loc[df["amount"] > 0, "amount"].sum()
        negatives = df.loc[df["amount"] < 0, "amount"].sum()

        return {
            "distinct_symbols": int(df["symbol"].nunique()),
            "distinct_sources": int(df["source_system"].nunique()),
            "gross_positive_exposure": float(positives),
            "gross_negative_exposure": float(negatives),
            "median_amount": float(df["amount"].median()),
            "records": len(df.index),
        }
