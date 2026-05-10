"""Loop síncrono de agendamentos — alternativa mais leve que Celery para cargas diárias."""

from __future__ import annotations

from collections.abc import Callable

import schedule
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def attach_daily_etl(trigger: Callable[[], None], run_time_local: str) -> Callable[[], None]:
    schedule.clear()

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(min=45, max=600))
    def resilient_trigger() -> None:
        trigger()


    schedule.every().day.at(run_time_local).do(resilient_trigger)
    logger.info("Agenda diária configurada para %s (timezone local)", run_time_local)
    return resilient_trigger


def run_pending_forever(interval_seconds: int = 30) -> None:
    import time as time_stdlib

    while True:
        schedule.run_pending()
        time_stdlib.sleep(interval_seconds)
