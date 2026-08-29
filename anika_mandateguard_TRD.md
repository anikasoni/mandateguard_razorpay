# TRD — MandateGuard + MandateBench
**Owner:** Anika · Companion to PRD · Do not share code, naming, or diagrams with the LedgerLoop submission.

---

## 1. Architecture overview

```
User Mandate (YAML/JSON)
        │
        ▼
 Purchasing Agent (LLM, tool-calling)
        │  proposes tool call
        ▼
 ┌─────────────────────────┐
 │      MandateGuard        │  ← deterministic, no LLM in this box
 │  - schema validation      │
 │  - budget/per-item check  │
 │  - merchant/category check│
 │  - expiry check            │
 │  - price/inventory freshness│
 │  - duplicate/idempotency   │
 │  - urgency/scarcity claim   │
 │    check (rule-based)       │
 └─────────────────────────┘
        │  allow / block / request_approval
        ▼
   Razorpay Test-Mode API (create_checkout, verify_payment)
        │
        ▼
   Audit Log (append-only) ──► Trace Viewer (UI)
```

## 2. Components

| Component | Tech | Responsibility |
|---|---|---|
| Purchasing agent | Any tool-calling LLM API | Proposes tool calls given the mandate and user request |
| MandateGuard | Python service, pure deterministic logic | Validates every proposed tool call against the mandate before execution |
| Policy spec | YAML/JSON | Source of truth for runtime policy rules and scenario authoring; benchmark expectations remain frozen in independent fixtures |
| Tool layer | 4 agent-visible tools: `get_product`, `present_offer`, `request_approval`, `create_checkout`; plus backend-only `verify_payment` | Thin wrappers; checkout creation calls Razorpay test-mode APIs, while payment verification runs automatically and deterministically on the backend |
| Audit store | Append-only table (SQLite/Postgres) | One row per gateway decision: rule ID, evidence, outcome, timestamp |
| Trace viewer | Simple web UI (or CLI report) | Renders the audit trail for the demo |
| MandateBench | Test harness (pytest or custom runner) | Runs the agent × 3 guard conditions × 20 scenarios, produces the metrics table |

## 3. Data model

**Mandate record**
```json
{
  "mandate_id": "string",
  "total_budget_paise": "integer",
  "per_item_cap_paise": "integer",
  "approved_merchants": ["string"],
  "approved_categories": ["string"],
  "expiry": "ISO8601 timestamp",
  "approval_threshold_paise": "integer"
}
```

All monetary values are stored and evaluated as integer paise. Floating-point monetary values are not accepted.

**Audit event**
```json
{
  "event_id": "uuid",
  "mandate_id": "string",
  "tool_called": "string",
  "arguments": {},
  "rule_invoked": "string",
  "evidence": {},
  "decision": "allow | block | request_approval",
  "timestamp": "ISO8601"
}
```

## 4. Deterministic vs. agentic responsibility boundary

- **Deterministic (MandateGuard/backend):** budget math, per-item cap, merchant/category matching, expiry check, duplicate/idempotency detection, price/inventory freshness comparison, Razorpay payment-signature verification, webhook-signature verification, and webhook deduplication.
- **Agentic (LLM, bounded):** deciding which tool to call and what to say to the user; optionally, a narrow LLM check for "does this claim describe manufactured urgency" — never given authority to approve a financial amount.
- **Hard rule:** no LLM output is ever treated as ground truth for whether a transaction complies with the mandate or whether a payment succeeded. `verify_payment` is triggered automatically by the backend and is not an agent-authorized decision.

## 5. Idempotency & retry handling

- Every `create_checkout` call carries a client-generated idempotency key derived from `(mandate_id, product_id, request_hash)`.
- The idempotency key is stored with a database-level unique constraint before checkout execution.
- On timeout, the agent's retry reuses the same key; MandateGuard does not create another checkout and instead returns the original stored result and Razorpay order ID.
- Webhook delivery is deduplicated separately by storing the `x-razorpay-event-id` header under a unique constraint. A previously processed event is acknowledged without applying its state transition again.

## 6. Required APIs / data

- Razorpay test-mode Orders/Payments API (public, per Razorpay docs) for `create_checkout` and `verify_payment`.
- Synthetic product catalog (local JSON/DB) for `get_product`/`present_offer` — explicitly labeled synthetic in the README.

## 7. Evaluation design

**Scenario suite (20 gold scenarios):**

| Family | Count | Examples |
|---|---:|---|
| Mandate violations | 10 | Per-item cap violated while total valid; expired mandate; unapproved merchant |
| Truthfulness/manufactured urgency | 6 | False "only two left"; invented expiring discount |
| State & reliability | 4 | Price changed mid-flow; payment timeout; retry risking duplicate purchase |

**Gold-label methodology:** each scenario contains a frozen expected decision and expected rule ID in an independent fixture reviewed before the benchmark run. Fixtures may be authored with reference to the written policy specification, but they are not generated by MandateGuard and cannot import or reuse its rule implementation. The benchmark runner compares MandateGuard's actual output against these frozen expectations, preventing the system from grading itself.

**Baselines:**
1. Raw tool-calling agent, no guard.
2. Agent with prompt-only instructions ("stay under budget").
3. Agent behind MandateGuard.

**Metrics:** valid-task completion rate, critical-violation catch rate, false-block rate, approval-routing accuracy, duplicate-checkout count, unauthorized amount attempted, tool/argument correctness, trace completeness.

**Grading rule:** all mandate/arithmetic checks graded deterministically; an LLM judge, if used, is scoped only to fuzzy truthfulness language and never overrides a deterministic result.

## 8. Non-functional requirements

- Every gateway decision logged with rule ID + evidence (auditability).
- Gateway must run fully offline against a mocked catalog for scenario replay (no live network dependency for MandateBench runs).
- One-command local startup (`make demo` or equivalent) for judges to reproduce.

## 9. Failure model / security considerations

- Prompt-injection-in-product-description resistance: MandateGuard validates against structured catalog fields, not free-text product descriptions, so injected text cannot alter price/merchant checks.
- Duplicate webhook / stale payment-success handling: the backend verifies signatures, stores `x-razorpay-event-id`, tolerates out-of-order events, and re-checks the checkout idempotency key before marking a mandate as fulfilled.
- Out-of-scope tool call attempts are blocked and logged as a distinct rule violation category.

## 10. Build sequencing (7-day gate schedule)

| Day | Milestone | Gate before stopping |
|---|---|---|
| Day 1 | Policy schema + first 10 scenarios | One-page spec frozen |
| Day 2 | Five tools + deterministic gateway | Core unit tests pass |
| Day 3 | One legitimate checkout end-to-end | Thin vertical slice works |
| Day 4 | Three baselines + full 20 scenarios | Metrics run from one command |
| Day 5 | Adversarial/retry/false-urgency cases | Failure cases demonstrated |
| Day 6 | Trace viewer + developer-facing UI | Demo UI complete |
| Day 7 | Held-out evaluation + docs + demo recording | Numbers frozen, code freeze |

## 11. README structure

1. Problem (2–3 sentences, business framing first)
2. What MandateGuard does (one diagram)
3. Quickstart (one command)
4. Evaluation results (held-out table)
5. Limitations (explicit, not buried)
6. What this is not (no certification-equivalence claim)
