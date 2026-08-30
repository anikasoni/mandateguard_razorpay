# MandateGuard

MandateGuard will be a deterministic policy gateway for AI purchasing agents. The agent may
propose commerce actions, but backend code alone will enforce financial mandates and verify
payment state. This repository is currently at the Phase 1 foundation stage.

## Phase 1 capabilities

- FastAPI application with liveness and SQLite-backed readiness endpoints.
- Pydantic environment configuration and UTC-aware timestamp utilities.
- SQLAlchemy 2 and Alembic foundations, with no domain tables yet.
- React, TypeScript, and Vite application shell that reports backend readiness.
- Backend and frontend linting, typing, tests, builds, and CI.

Phase 1 does **not** implement policy rules, an AI agent, benchmarks, a catalog, Razorpay
payments, webhooks, mandates, checkouts, or audit events.

## Prerequisites

- Conda environment `mandate` with Python 3.12
- Node.js 24 and npm

## Setup

```powershell
Copy-Item .env.example .env
conda run -n mandate python -m pip install -e ".[dev]"
npm.cmd --prefix frontend ci
```

No secrets are required in Phase 1. Future credentials must be supplied only through
environment variables and must never be committed.

## Run locally

```powershell
.\scripts\dev.ps1
```

The API listens on `http://127.0.0.1:8000`, the UI on `http://127.0.0.1:5173`, and API docs
are available at `http://127.0.0.1:8000/docs`.
The backend permits both `http://localhost:5173` and `http://127.0.0.1:5173` as local UI
origins by default; wildcard origins are not enabled.

Health endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

## Verify

```powershell
.\scripts\verify.ps1
```

See `AGENTS.md` for individual commands and repository invariants.

## Architecture boundary

All financial values will be integer paise and all timestamps UTC-aware. Financial-policy and
payment-verification authority belongs exclusively to deterministic backend code;
`verify_payment` is not an agent tool. Future benchmark labels must be frozen independently of
the implementation they assess.

## Limitations

The product implementation and evaluation suite do not exist in Phase 1. The planned catalog
will be synthetic, the benchmark will be a starting evidence set rather than exhaustive proof,
and MandateGuard will not claim equivalence with Razorpay's internal certification pipeline.
