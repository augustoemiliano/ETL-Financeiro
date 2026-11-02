"""Sessões e factory de engines — isolado da camada HTTP."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base

_engine = None
_SessionLocal = None


def engine_kwargs(settings: Settings) -> dict:
    """Parâmetros de pool só fazem sentido para servidores (PostgreSQL)."""
    kwargs: dict = {"pool_pre_ping": True, "echo": settings.debug}
    if settings.database_url.startswith("sqlite"):
        # Permite uso da mesma conexão SQLite pelas threads do FastAPI.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=10, max_overflow=20)
    return kwargs


def reset_engine() -> None:
    """Descarta engine/sessões em cache (útil em testes e trocas de DATABASE_URL)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_engine(settings: Settings | None = None):
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    settings = settings or get_settings()
    _engine = create_engine(settings.database_url, **engine_kwargs(settings))
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _SessionLocal
    get_engine(settings)
    assert _SessionLocal is not None
    return _SessionLocal


def get_db_session(settings: Settings | None = None) -> Generator[Session, None, None]:
    SessionLocal = get_session_factory(settings)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(engine, metadata=Base.metadata) -> None:
    metadata.create_all(bind=engine)
