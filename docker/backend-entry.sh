#!/usr/bin/env bash
set -euo pipefail

python scripts/wait_for_db.py
alembic upgrade head

MODE="${1:-api}"

case "${MODE}" in
api)
  exec uvicorn app.api.factory:create_app \
    --factory \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}"
  ;;
scheduler)
  exec python main.py scheduler
  ;;
etl)
  exec python main.py run-etl
  ;;
*)
  echo "Modo '${MODE}' desconhecido. Use api | scheduler | etl." >&2
  exit 1
  ;;
esac
