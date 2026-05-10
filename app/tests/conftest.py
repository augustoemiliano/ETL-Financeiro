"""Configura pytest e defaults de ambiente — credenciais nunca ficam aqui."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://etl_user:etl_pass@127.0.0.1:5435/etl_db",
)


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
