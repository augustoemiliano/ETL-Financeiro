"""Cliente HTTP síncrono com retry exponencial e tratamento consistente de erros."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests import Response
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# 429 (rate limit) e 5xx são transitórios; demais 4xx são erro do cliente (não adianta repetir).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, Timeout)):
        return True
    if isinstance(exc, HTTPError) and exc.response is not None:
        return exc.response.status_code in RETRYABLE_STATUS
    return False


class ResilientHttpClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self._settings = settings
        self._session = session or requests.Session()
        self._session.headers.update(
            {"User-Agent": settings.app_name, "Accept": "application/json"},
        )

    def _retrying(self) -> Retrying:
        return Retrying(
            reraise=True,
            retry=retry_if_exception(is_transient_error),
            stop=stop_after_attempt(self._settings.http_retry_attempts),
            wait=wait_exponential(
                multiplier=1,
                min=self._settings.http_retry_min_wait_seconds,
                max=self._settings.http_retry_max_wait_seconds,
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET com retry apenas para falhas transitórias; erros definitivos sobem na hora."""
        for attempt in self._retrying():
            with attempt:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._settings.fx_request_timeout,
                )
                response.raise_for_status()
                return response.json()
        raise RequestException("retry encerrado sem resposta")  # pragma: no cover

    def raw_get(self, url: str, **kwargs: Any) -> Response:
        return self._session.get(url, timeout=self._settings.fx_request_timeout, **kwargs)
