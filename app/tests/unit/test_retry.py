"""RETRY: cliente HTTP (tenacity) e job do scheduler."""

from __future__ import annotations

import json

import pytest
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout
from tenacity import wait_none

from app.core.schedule_runner import build_resilient_job
from app.utils.http_client import ResilientHttpClient, is_transient_error


def _response(status: int, payload: dict | None = None) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(payload or {}).encode()
    resp.url = "http://fx.test/latest"
    return resp


class _ScriptedSession(requests.Session):
    """Session que devolve/levanta itens de um roteiro, um por chamada."""

    def __init__(self, script: list) -> None:
        super().__init__()
        self.script = list(script)
        self.calls = 0

    def get(self, url, **kwargs):  # type: ignore[override]
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_retry_recovers_after_transient_failures(make_settings) -> None:
    session = _ScriptedSession(
        [ConnectionError("queda"), Timeout("lento"), _response(200, {"ok": 1})]
    )
    client = ResilientHttpClient(make_settings(HTTP_RETRY_ATTEMPTS=3), session=session)

    assert client.get_json("http://fx.test/latest") == {"ok": 1}
    assert session.calls == 3


def test_retry_gives_up_after_max_attempts(make_settings) -> None:
    session = _ScriptedSession([_response(503)] * 5)
    client = ResilientHttpClient(make_settings(HTTP_RETRY_ATTEMPTS=3), session=session)

    with pytest.raises(HTTPError):
        client.get_json("http://fx.test/latest")
    assert session.calls == 3


def test_client_errors_are_not_retried(make_settings) -> None:
    session = _ScriptedSession([_response(404), _response(200)])
    client = ResilientHttpClient(make_settings(HTTP_RETRY_ATTEMPTS=4), session=session)

    with pytest.raises(HTTPError):
        client.get_json("http://fx.test/latest")
    assert session.calls == 1


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionError(), True),
        (Timeout(), True),
        (HTTPError(response=_response(429)), True),
        (HTTPError(response=_response(500)), True),
        (HTTPError(response=_response(400)), False),
        (ValueError("json inválido"), False),
    ],
)
def test_is_transient_error(exc: Exception, expected: bool) -> None:
    assert is_transient_error(exc) is expected


def test_scheduler_job_retries_until_success() -> None:
    calls = {"n": 0}

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("falha temporária")

    build_resilient_job(flaky, attempts=4, wait=wait_none())()
    assert calls["n"] == 3


def test_scheduler_job_swallows_final_failure_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    calls = {"n": 0}

    def always_fails() -> None:
        calls["n"] += 1
        raise RuntimeError("banco fora")

    job = build_resilient_job(always_fails, attempts=2, wait=wait_none())
    job()  # não pode propagar: o loop do scheduler precisa continuar vivo

    assert calls["n"] == 2
    assert "falhou após 2 tentativas" in caplog.text
