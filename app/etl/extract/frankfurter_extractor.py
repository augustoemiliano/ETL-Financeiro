"""Fonte síncrona baseada na API Frankfurter (cotizações públicas ECB)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.core.config import Settings
from app.etl.extract.protocols import ExtractionOutcome, SourceUnavailableError
from app.utils.http_client import ResilientHttpClient


class FrankfurterFxExtractor:
    def __init__(self, settings: Settings, http: ResilientHttpClient | None = None) -> None:
        self._settings = settings
        self._http = http or ResilientHttpClient(settings)

    def fetch_latest(
        self,
        base_currency: str | None = None,
        targets: tuple[str, ...] | None = None,
    ) -> ExtractionOutcome:
        base_currency = (base_currency or self._settings.fx_base_currency).upper()
        targets = targets or self._settings.fx_targets
        path = "/latest"
        url = self._settings.fx_api_base_url.rstrip("/") + path
        params = {"from": base_currency, "to": ",".join(sorted(targets))}
        try:
            payload = self._http.get_json(url, params=params)
        except Exception as exc:
            # Chega aqui somente depois de esgotadas as tentativas do retry.
            raise SourceUnavailableError(f"Falha na API FX: {exc}") from exc

        if not isinstance(payload, dict):
            raise SourceUnavailableError("Resposta inesperada da API FX (JSON não é objeto)")
        rates = payload.get("rates") or {}
        if not rates:
            raise SourceUnavailableError("API FX respondeu sem cotações ('rates' vazio)")
        base = payload.get("base") or base_currency
        fetched_at_raw = payload.get("date") or datetime.now(tz=UTC).date().isoformat()
        rows = []
        for quote, amount in rates.items():
            rows.append(
                {
                    "pair": f"{base}/{quote.upper()}",
                    "fx_date": pd.to_datetime(fetched_at_raw).date(),
                    "base_currency": base.upper(),
                    "quote_currency": quote.upper(),
                    "rate": float(amount),
                },
            )
        df = pd.DataFrame(rows)
        return ExtractionOutcome(name="fx_api_frankfurter", frame=df)
