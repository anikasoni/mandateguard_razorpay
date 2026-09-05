# MandateGuard

MandateGuard is being built as a deterministic policy gateway for AI purchasing agents. The
agent may propose commerce actions, but backend code alone enforces financial mandates. The
repository currently contains the Phase 1 foundation, the pure Phase 2A policy engine, and the
Phase 2B persistence layer, the Phase 2C API, and a demo-ready agent-to-payment vertical slice.

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
- Demo: a bounded Gemini planner (with deterministic offline fallback) proposes a catalog item;
  the backend executes every commerce tool through the deterministic policy service.
- Demo: Razorpay test-mode Orders and backend-only HMAC payment verification. When no Razorpay
  keys are configured, order creation is explicitly labelled `simulated`.
- MandateBench: 20 frozen scenarios across mandate violations, offer truthfulness, and state
  reliability, with per-scenario evidence and raw-agent/prompt-only proxy comparisons.
- Product UI: live agent run, safety scenarios, human approval/resume, payment checkout, rule
  evidence, fingerprints, and benchmark results.
- Pydantic environment configuration and UTC-aware timestamp utilities.
- Backend and frontend linting, typing, tests, builds, and CI.

Webhook ingestion, YAML policy loading, and production identity/access management remain future
work. The demo creates Razorpay Orders only after a guarded local reservation; policy evaluation
itself never authorizes an external side effect.

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

For the full seeded demo, set a private human key in `.env`, optionally add Gemini and Razorpay
test credentials, then run:

```powershell
.\scripts\demo.ps1
```

Without Gemini or Razorpay credentials the same workflow remains demonstrable using the labelled
offline planner and simulated order mode. Live Razorpay keys are deliberately rejected.

## Run locally

```powershell
.\scripts\dev.ps1
```

The API listens on `http://127.0.0.1:8000`, the UI on `http://127.0.0.1:5173`, and API docs
are available at `http://127.0.0.1:8000/docs`.
The backend permits both `http://localhost:5173` and `http://127.0.0.1:5173` as local UI
origins by default; wildcard origins are not enabled.

## Railway hackathon deployment

Create one Railway service from this repository with the repository root left as the service
root. The checked-in `railway.json` selects the root `Dockerfile`, readiness endpoint, and
restart policy; leave the dashboard start command empty so the image entrypoint is used. Set the
service to exactly one replica, generate one public HTTPS domain, and attach one volume mounted
at `/data`.

Set these Railway service variables, replacing placeholders with private values and the domain
Railway generated:

```text
MANDATEGUARD_ENVIRONMENT=production
MANDATEGUARD_LOG_LEVEL=INFO
MANDATEGUARD_DATABASE_URL=sqlite:////data/mandateguard.db
MANDATEGUARD_CORS_ORIGINS=https://<your-generated-domain>
MANDATEGUARD_HUMAN_APPROVAL_KEY=<private-value-at-least-16-characters>
MANDATEGUARD_GEMINI_API_KEY=<private-gemini-api-key>
MANDATEGUARD_GEMINI_MODEL=gemini-3.1-flash-lite
MANDATEGUARD_RAZORPAY_KEY_ID=<rzp_test_key_id>
MANDATEGUARD_RAZORPAY_KEY_SECRET=<private-test-key-secret>
RAILWAY_RUN_UID=0
```

Do not set `PORT`; Railway supplies it. Gemini and Razorpay credentials remain backend-only and
are not Docker build arguments or Vite variables. Razorpay accepts test-mode keys only. The
human approval key is a demo trust boundary and is entered by the human operator when needed;
it is not embedded in the frontend bundle.

Railway mounts volumes as root, so this deployment uses `RAILWAY_RUN_UID=0` and the container
process runs as root to write `/data`. This is an explicit hackathon limitation. The SQLite
volume also requires the service to remain at one replica. Migrations and the idempotent
synthetic demo seed run on every container start before one Uvicorn worker begins accepting
traffic.

Health endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

Policy endpoints:

- `POST /api/v1/policy/evaluations`
- `POST /api/v1/human/mandates/{mandate_id}/approvals/{approval_id}/decisions`

Demo endpoints:

- `POST /api/v1/agent/runs`
- `POST /api/v1/payments/orders`
- `POST /api/v1/payments/verify` (called by the backend integration, never by the agent)
- `GET /api/v1/benchmark/report`

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

Optional integrations use environment-only credentials:

```text
MANDATEGUARD_GEMINI_API_KEY=<private-gemini-api-key>
MANDATEGUARD_GEMINI_MODEL=gemini-3.1-flash-lite
MANDATEGUARD_RAZORPAY_KEY_ID=<rzp_test_key-id>
MANDATEGUARD_RAZORPAY_KEY_SECRET=<private-test-key-secret>
```

## MandateBench

The benchmark contains 20 independently labelled fixtures: 10 mandate/boundary scenarios, six
truthfulness scenarios, and four replay/state scenarios. It reports violation catch rate,
false-block rate, decision accuracy, terminal rule, and the individual result for every case.
The raw-agent and prompt-only columns are frozen illustrative proxies—not live LLM experiments or
claims about a production model. Run the report with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/benchmark/report
```

## Architecture boundary

All financial values are integer paise and all persisted timestamps are UTC-aware.
Financial-policy and payment-verification authority belongs exclusively to deterministic backend
code; `verify_payment` is not an agent tool. Future benchmark labels must be frozen independently
of the implementation they assess.

## Limitations

This is a hackathon prototype, not a production payment gateway. Its catalog and benchmark are
synthetic; 20 scenarios are evidence, not exhaustive safety proof. The local human API key is a
demo trust boundary, not production authentication. Razorpay support is test-mode Orders plus
checkout-signature verification: webhook ingestion, refunds, an outbox for provider/DB crash
recovery, and production reconciliation are intentionally absent. MandateGuard does not claim
equivalence with Razorpay's internal certification pipeline.
