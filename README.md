# MandateGuard

MandateGuard is being built as a deterministic policy gateway for AI purchasing agents. The
agent may propose commerce actions, but backend code alone enforces financial mandates. The
repository currently contains the Phase 1 foundation, the pure Phase 2A policy engine, and the
Phase 2B persistence and transactional policy-orchestration layer.

## Implemented capabilities

- Phase 1: FastAPI application with liveness and SQLite-backed readiness endpoints.
- Phase 1: React, TypeScript, and Vite application shell that reports backend readiness.
- Phase 2A: pure deterministic domain models, policy rules, ordered evidence, stable decision
  fingerprints, replay classifications, and retry classifications.
- Phase 2B: SQLAlchemy records and field-parity mappers for mandates, scopes, products,
  approvals, checkout attempts, and append-only audit events.
- Phase 2B: Alembic schema migration, repository layer, and a transactional `PolicyService`
  using an explicit SQLite write transaction for atomic decisions, effects, and audits.
- Pydantic environment configuration and UTC-aware timestamp utilities.
- Backend and frontend linting, typing, tests, builds, and CI.

API routes for policy evaluation, an AI/LLM agent, Razorpay and payment/webhook handling,
MandateBench, YAML loading, and product UI features remain future work. Phase 2B does not
execute an external checkout.

## Prerequisites

- Conda environment `mandate` with Python 3.12
- Node.js 24 and npm

## Setup

```powershell
Copy-Item .env.example .env
conda run -n mandate python -m pip install -e ".[dev]"
npm.cmd --prefix frontend ci
conda run -n mandate python -m alembic -c backend/alembic.ini upgrade head
```

No secrets are required for the currently implemented phases. Future credentials must be
supplied only through environment variables and must never be committed.

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

## Trusted policy lifetimes

Pending approval and checkout reservation lifetimes are backend-owned settings. They are never
accepted from an agent or tool request. Defaults are 900 seconds for pending approvals and 300
seconds for checkout reservations; both accept values from 1 through 86,400 seconds:

```text
MANDATEGUARD_PENDING_APPROVAL_TTL_SECONDS=900
MANDATEGUARD_CHECKOUT_RESERVATION_TTL_SECONDS=300
```

Phase 2B persists policy state and audit decisions transactionally. It does not execute an
external checkout: a replay only returns the existing stored record and never authorizes an
external side effect.

## Architecture boundary

All financial values are integer paise and all persisted timestamps are UTC-aware.
Financial-policy and payment-verification authority belongs exclusively to deterministic backend
code; `verify_payment` is not an agent tool. Future benchmark labels must be frozen independently
of the implementation they assess.

## Limitations

The repository is not yet a complete product: it has no policy API transport, external checkout
executor, payment provider integration, agent integration, product workflow, or benchmark.
Future benchmark evidence will not be exhaustive proof, and MandateGuard does not claim
equivalence with Razorpay's internal certification pipeline.
