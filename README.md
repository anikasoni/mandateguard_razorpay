# MandateGuard

MandateGuard is being built as a deterministic policy gateway for AI purchasing agents. The
agent may propose commerce actions, but backend code alone enforces financial mandates. The
repository currently contains the Phase 1 foundation, the pure Phase 2A policy engine, and the
Phase 2B persistence layer, plus the Phase 2C policy API and explicit human approval lifecycle.

## Implemented capabilities

- Phase 1: FastAPI application with liveness and SQLite-backed readiness endpoints.
- Phase 1: React, TypeScript, and Vite application shell that reports backend readiness.
- Phase 2A: pure deterministic domain models, policy rules, ordered evidence, stable decision
  fingerprints, replay classifications, and retry classifications.
- Phase 2B: SQLAlchemy records and field-parity mappers for mandates, scopes, products,
  approvals, checkout attempts, and append-only audit events.
- Phase 2B: Alembic schema migration, repository layer, and a transactional `PolicyService`
  using an explicit SQLite write transaction for atomic decisions, effects, and audits.
- Phase 2C: one policy evaluation API for all four agent-visible tool contracts and an
  environment-key-protected human approval endpoint.
- Phase 2C: atomic, exact-bound, expiry-aware grant/reject decisions with append-only human
  decision audits and idempotent identical retries.
- Pydantic environment configuration and UTC-aware timestamp utilities.
- Backend and frontend linting, typing, tests, builds, and CI.

An AI/LLM agent, Razorpay and payment/webhook handling, MandateBench, YAML loading, and product
UI features remain future work. Policy checkout results reserve local state only and do not
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

Health and policy evaluation require no secrets. The human approval endpoint requires the
environment-only local-demo key documented below. Credentials must never be committed.

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

Policy endpoints:

- `POST /api/v1/policy/evaluations`
- `POST /api/v1/human/mandates/{mandate_id}/approvals/{approval_id}/decisions`

The policy POST accepts the existing discriminated `ToolRequest` JSON contract. Policy blocks,
approval routing, unknown mandates, and semantically malformed requests are successful,
audited evaluations returned with HTTP 200. Every response explicitly reports
`external_execution_authorized: false`.

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

The human-only grant/reject endpoint is disabled until a private local-demo key of at least 16
characters is provided. Send the same value in `X-MandateGuard-Human-Key`; never expose it to an
agent or commit a real value:

```text
MANDATEGUARD_HUMAN_APPROVAL_KEY=<private-local-demo-value>
```

Policy state, policy audits, and human approval decisions are persisted transactionally. A
replay only returns the existing stored record and never authorizes an external side effect.

## Architecture boundary

All financial values are integer paise and all persisted timestamps are UTC-aware.
Financial-policy and payment-verification authority belongs exclusively to deterministic backend
code; `verify_payment` is not an agent tool. Future benchmark labels must be frozen independently
of the implementation they assess.

## Limitations

The repository is not yet a complete product: it has no external checkout executor, payment
provider integration, agent integration, product workflow, or benchmark. The local human API
key is a demo trust boundary, not production authentication. Future benchmark evidence will not
be exhaustive proof, and MandateGuard does not claim equivalence with Razorpay's internal
certification pipeline.
