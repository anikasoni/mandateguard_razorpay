# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY backend/src/ backend/src/
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MANDATEGUARD_FRONTEND_DIST_DIR=/app/frontend/dist
WORKDIR /app
COPY --from=python-builder /wheels/ /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-index --find-links=/tmp/wheels mandateguard \
    && rm -rf /tmp/wheels
COPY backend/alembic.ini backend/alembic.ini
COPY backend/migrations/env.py backend/migrations/env.py
COPY backend/migrations/versions/*.py backend/migrations/versions/
COPY scripts/start.sh scripts/start.sh
COPY --from=frontend-builder /build/frontend/dist/ frontend/dist/
RUN chmod 0755 scripts/start.sh \
    && mkdir -p /data

ENTRYPOINT ["/app/scripts/start.sh"]
