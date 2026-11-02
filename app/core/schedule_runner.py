"""Loop síncrono de agendamentos — alternativa mais leve que Celery para cargas diárias."""

from __future__ import annotations

import logging
from collections.abc import Callable

import schedule
from tenacity import Retrying, before_sleep_log, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def build_resilient_job(
    trigger: Callable[[], None],
    *,
    attempts: int = 4,
    wait: wait_base | None = None,
) -> Callable[[], None]:
    """Envolve o job com retry exponencial.

    Se todas as tentativas falharem, o erro é registrado e engolido de propósito: uma janela
    diária ruim não pode derrubar o processo do scheduler (o próximo dia roda normalmente).
    """

    wait_strategy = wait if wait is not None else wait_exponential(min=45, max=600)

    def resilient_trigger() -> None:
        try:
            for attempt in Retrying(
                reraise=True,
                stop=stop_after_attempt(attempts),
                wait=wait_strategy,
                before_sleep=before_sleep_log(logger, logging.WARNING),
            ):
                with attempt:
                    trigger()
        except Exception:
            logger.exception("Job agendado falhou após %s tentativas", attempts)

    return resilient_trigger


def attach_daily_etl(
    trigger: Callable[[], None],
    run_time_local: str,
    *,
    attempts: int = 4,
) -> Callable[[], None]:
    schedule.clear()
    resilient_trigger = build_resilient_job(trigger, attempts=attempts)
    schedule.every().day.at(run_time_local).do(resilient_trigger)
    logger.info("Agenda diária configurada para %s (timezone local)", run_time_local)
    return resilient_trigger


def run_pending_forever(interval_seconds: int = 30) -> None:
    import time as time_stdlib

    while True:
        schedule.run_pending()
        time_stdlib.sleep(interval_seconds)
