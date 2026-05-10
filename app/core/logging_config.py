"""Configuração de logging estruturado (console + arquivo por nível).

Decisões:
- Um `TimedRotatingFileHandler` por arquivo evita disco cheio sem config externa pesada.
- INFO e ERROR separados conforme solicitado; WARNING vai para INFO (padrão comum).
- Formato texto com campo `extras` permite evoluir para JSON estruturado depois.
- Fallback só-console quando o diretório não é gravável (ex.: bind mount SELinux Fedora).
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Idempotente: se já houver handlers no root logger, não duplica."""
    log_dir = Path(settings.log_dir)

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(settings.log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(settings.log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        test_path = log_dir / ".writetest"
        test_path.touch()
        test_path.unlink(missing_ok=True)
    except OSError as exc:
        root.warning("Pasta %s não utilizável para arquivos de log: %s", log_dir, exc)
        return

    info_file = TimedRotatingFileHandler(
        filename=str(log_dir / "app_info.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    info_file.setLevel(logging.INFO)
    info_file.addFilter(lambda r: r.levelno < logging.ERROR)
    info_file.setFormatter(formatter)

    error_file = TimedRotatingFileHandler(
        filename=str(log_dir / "app_error.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)

    root.addHandler(info_file)
    root.addHandler(error_file)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "etl")
