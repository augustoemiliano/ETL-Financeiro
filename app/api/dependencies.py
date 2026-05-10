"""Injeções de dependência utilizadas pela camada HTTP."""

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session


def get_db(settings: Settings = Depends(get_settings)) -> Generator[Session, None, None]:
    yield from get_db_session(settings)
