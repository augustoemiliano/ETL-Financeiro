"""Carregamento de configurações por ambiente (12-factor).

Nada de credenciais no código: tudo via variáveis de ambiente ou `.env`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
    fx_base_currency: str = Field(default="USD", alias="FX_BASE_CURRENCY")
    # Lista separada por vírgula, ex.: "BRL,EUR,GBP".
    fx_target_currencies: str = Field(default="BRL,EUR,GBP", alias="FX_TARGET_CURRENCIES")
    # Habilita/desabilita a fonte HTTP (útil para rodar offline só com arquivos).
    fx_enabled: bool = Field(default=True, alias="FX_ENABLED")

    # Retry exponencial das chamadas HTTP (tenacity).
    http_retry_attempts: int = Field(default=4, ge=1, alias="HTTP_RETRY_ATTEMPTS")
    http_retry_min_wait_seconds: float = Field(default=2.0, ge=0, alias="HTTP_RETRY_MIN_WAIT")
    http_retry_max_wait_seconds: float = Field(default=20.0, ge=0, alias="HTTP_RETRY_MAX_WAIT")

    @property
    def fx_request_timeout(self) -> tuple[float, float]:
        return (self.fx_connect_timeout_seconds, self.fx_read_timeout_seconds)

    @property
    def fx_targets(self) -> tuple[str, ...]:
        items = (c.strip().upper() for c in self.fx_target_currencies.split(","))
        return tuple(c for c in items if c)

    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_run_time: str = Field(default="02:00", alias="SCHEDULER_RUN_TIME")
    scheduler_retry_attempts: int = Field(default=4, ge=1, alias="SCHEDULER_RETRY_ATTEMPTS")
    csv_input_dir: str = Field(default="data/samples", alias="CSV_INPUT_DIR")
    xlsx_input_dir: str = Field(default="data/samples", alias="XLSX_INPUT_DIR")

    # Janela (em dias, a partir de hoje) dos relatórios; vazio/ausente = histórico completo.
    report_history_days: int | None = Field(default=None, ge=1, alias="REPORT_HISTORY_DAYS")

    @field_validator("report_history_days", mode="before")
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        return None if value == "" else value

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
