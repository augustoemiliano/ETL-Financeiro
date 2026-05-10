"""Carregamento de configurações por ambiente (12-factor).

Nada de credenciais no código: tudo via variáveis de ambiente ou `.env`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="ETL Financeiro Inteligente")
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        alias="ENVIRONMENT",
    )
    debug: bool = Field(default=False, alias="DEBUG")

    database_url: str = Field(..., alias="DATABASE_URL")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="logs", alias="LOG_DIR")
    reports_dir: str = Field(default="reports", alias="REPORTS_DIR")

    # Extração financeira — Frankfurter (API pública ECB, sem chave).
    fx_api_base_url: str = Field(
        default="https://api.frankfurter.app",
        alias="FX_API_BASE_URL",
    )
    fx_connect_timeout_seconds: float = Field(default=5.0, alias="FX_CONNECT_TIMEOUT")
    fx_read_timeout_seconds: float = Field(default=30.0, alias="FX_READ_TIMEOUT")

    @property
    def fx_request_timeout(self) -> tuple[float, float]:
        return (self.fx_connect_timeout_seconds, self.fx_read_timeout_seconds)

    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_run_time: str = Field(default="02:00", alias="SCHEDULER_RUN_TIME")
    csv_input_dir: str = Field(default="data/samples", alias="CSV_INPUT_DIR")
    xlsx_input_dir: str = Field(default="data/samples", alias="XLSX_INPUT_DIR")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
