"""Cliente HTTP síncrono com retry e tratamento consistente de erros."""

from __future__ import annotations

from typing import Any

import requests
from requests import Response
from requests.exceptions import RequestException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings


def _respectful_wait() -> wait_exponential:
    return wait_exponential(multiplier=1, min=2, max=20)


class ResilientHttpClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": settings.app_name, "Accept": "application/json"},
        )

    @retry(
        reraise=True,
        retry=retry_if_exception_type(RequestException),
        stop=stop_after_attempt(4),
        wait=_respectful_wait(),
    )
    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._session.get(
            url,
            params=params,
            timeout=self._settings.fx_request_timeout,
        )
        response.raise_for_status()
        return response.json()

    def raw_get(self, url: str, **kwargs: Any) -> Response:
        return self._session.get(url, timeout=self._settings.fx_request_timeout, **kwargs)
