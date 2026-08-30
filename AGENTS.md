# MandateGuard Repository Instructions

## Architecture

- `backend/src/mandateguard/` is the FastAPI application. `api/` owns HTTP transport,
  `core/` owns configuration/logging/time, and `db/` owns SQLAlchemy infrastructure.
- `frontend/` is the React, TypeScript, and Vite client.
- `backend/migrations/` contains Alembic migration infrastructure.
- `scripts/` contains local PowerShell workflows; `.github/workflows/` contains CI.
- The PRD and revised TRD at the repository root are requirements documents. Preserve them.
- Do not create future policy, agent, Razorpay, benchmark, catalog, or product-feature
  directories until their phase is explicitly authorized.

## Commands

Run Python commands in the `mandate` Conda environment when the shell does not inherit it:

```powershell
conda run -n mandate python -m pip install -e ".[dev]"
conda run -n mandate python -m pytest backend/tests
conda run -n mandate python -m ruff check backend
conda run -n mandate python -m ruff format --check backend
conda run -n mandate python -m mypy backend/src
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run test -- --run
npm.cmd --prefix frontend run build
.\scripts\verify.ps1
.\scripts\dev.ps1
```

## Non-negotiable invariants

- Represent every monetary value as an integer number of paise. Never use floats for money.
- Produce UTC-aware timestamps. SQLite persistence must normalize writes to UTC and restore
  timezone awareness on reads.
- Financial-policy enforcement is deterministic backend code. An LLM may propose actions but
  must never authorize, validate, or override a financial decision.
- `verify_payment` is backend-only. Payment signatures and webhook signatures are verified by
  backend code, never by the agent.
- Benchmark expectations are frozen, independently authored fixtures. Benchmark fixtures must
  not import policy implementation or derive their expected labels from it.
- Secrets come only from environment variables. Never commit credentials, `.env` files, test
  keys, payment secrets, webhook secrets, or LLM keys.
- Keep the product within the PRD/TRD scope and state limitations honestly. Do not claim
  equivalence with Razorpay's certification pipeline.

## Phase 1 definition of done

- Root editable installation discovers `backend/src/mandateguard`.
- Backend lint, formatting, typing, tests, coverage, health, and SQLite readiness checks pass.
- Alembic loads successfully without domain tables or migrations.
- Frontend dependency installation, lint, type-check, tests, and production build pass.
- CI mirrors the local verification commands.
- The PRD and TRD are unchanged.
- No policy rules, agent, benchmark, catalog, payment, webhook, audit, mandate, or checkout
  implementation exists.
- Work remains uncommitted and unpushed unless the user explicitly authorizes Git operations.
