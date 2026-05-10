"""Pequeno utilitário de bootstrap para garantir Postgres acessível no Docker."""

from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text


def wait_for_database(url: str, attempts: int = 60, sleep_seconds: int = 2) -> None:
    for attempt in range(1, attempts + 1):
        try:
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("[wait-for-db] conexão bem-sucedida", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[wait-for-db] tentativa {attempt}/{attempts} falhou: {exc}", flush=True)
            time.sleep(sleep_seconds)
    raise RuntimeError("Banco não ficou disponível dentro do tempo limite esperado")


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL ausente.", file=sys.stderr)
        return 1
    wait_for_database(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
