#!/bin/sh
set -eu

: "${PORT:?PORT must be set}"

python -m mandateguard.core.startup
alembic -c /app/backend/alembic.ini upgrade head
python -m mandateguard.demo.seed

exec uvicorn mandateguard.main:app --host 0.0.0.0 --port "$PORT" --workers 1
