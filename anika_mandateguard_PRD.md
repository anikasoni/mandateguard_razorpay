# PRD — MandateGuard + MandateBench
**Owner:** Anika · **Track:** 01 — AI Growth & Agentic Commerce · **Razorpay AI Buildathon 2026**

---

## 1. Problem statement

AI purchasing agents can now call payment tools directly, but the instructions that are supposed to constrain them ("spend under ₹6,000 total, never more than ₹2,500 per item") are natural-language prompts, not enforceable contracts. A model can misread, forget, or be manipulated out of a budget constraint mid-conversation, and nothing stops the resulting tool call from executing. Razorpay's own Agent Studio guardrails post confirms this is a live concern, not a hypothetical one: Razorpay runs a platform-level validation layer and a certification pipeline that screens agent actions for compliance boundaries, amount validation, scope violations, and dark patterns before any third-party agent reaches its marketplace (razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/). Razorpay's builder platform opens to external developers on May 9, meaning a population of developers will soon need to get their own agents through that exact gate.

## 2. Target user

A developer building an AI purchasing/checkout agent on top of Razorpay APIs — either independently or aiming to publish through the Agent Studio marketplace — who needs to prove, not just assert, that their agent cannot exceed a user's financial mandate.

## 3. Value proposition

> Integrate Razorpay commerce while proving — with a reproducible test suite, not a claim — that your agent cannot exceed the user's financial mandate.

MandateGuard is a deterministic policy gateway every proposed money-moving tool call must pass through. MandateBench is the evidence: a scenario suite and baseline comparison showing the gateway catches violations a raw or prompt-guarded agent lets through.

## 4. User stories

1. As a developer, I give my purchasing agent a mandate (budget, per-item cap, approved merchants, expiry) and I can see, for any tool call it attempts, whether MandateGuard allowed it, blocked it, or routed it for approval — and exactly which rule fired.
2. As a developer, I can run my agent against a fixed scenario suite and get a report comparing "no guard," "prompt-only guard," and "MandateGuard" on violation catch rate, false-block rate, and completion rate — so I can show, not tell, that the gateway adds value.
3. As a reviewer (judge/engineer), I can watch a legitimate purchase succeed, a subtle per-item violation get caught while the total budget stays valid, a fabricated-urgency claim get rejected, and a timeout-triggered retry get deduplicated — in under five minutes, with an audit trail for every decision.

## 5. Scope (MVP)

**In scope:**
- One mandate schema (JSON/YAML): total budget, per-item cap, approved merchant list/category, expiry, approval threshold.
- Five agent tools: `get_product`, `present_offer`, `request_approval`, `create_checkout`, `verify_payment`.
- MandateGuard deterministic gateway sitting in front of all five tools.
- One synthetic merchant catalog; real Razorpay test-mode checkout for the money-movement leg.
- MandateBench: 20 gold scenarios across mandate violations (10), truthfulness/manufactured urgency (6), state & reliability (4).
- Three-way baseline comparison: raw tool-calling agent / prompt-only guard / MandateGuard.
- A trace/audit viewer showing rule invoked, evidence, and allow/block/approve decision per action.

**Explicit non-goals:**
- No general-purpose agent framework.
- No more than 5–6 commerce tools.
- No marketplace, no multi-merchant support.
- No LLM acting as the financial-policy judge — all mandate/arithmetic decisions are deterministic.
- No claim of replacing or being equivalent to Razorpay's actual certification pipeline.

## 6. Success metrics

| Metric | Target |
|---|---|
| Critical-violation catch rate (MandateGuard) | 100% on the 20-scenario gold set |
| False-block rate (MandateGuard) | Reported honestly; demonstrate at least one false-block case and explain it |
| Violation catch rate, raw agent vs. prompt-only vs. MandateGuard | Show MandateGuard strictly dominates both baselines |
| Duplicate-checkout prevention under retry/timeout | 0 duplicate charges across timeout-retry scenarios |
| Trace completeness | Every decision has rule ID + evidence + outcome logged |

## 7. Five-minute demo sequence

1. (0:00–0:30) Problem framing: prompts aren't enforceable mandates.
2. (0:30–1:10) Mandate schema + gateway architecture.
3. (1:10–1:50) Legitimate purchase completes end-to-end on Razorpay test-mode.
4. (1:50–2:30) Subtle per-item violation blocked (total valid, per-item invalid).
5. (2:30–3:10) Manufactured-urgency claim blocked.
6. (3:10–3:50) Timeout → retry → idempotency key prevents duplicate checkout.
7. (3:50–4:20) Baseline comparison table, including a false-block case caught by weaker guards but correctly permitted by MandateGuard.
8. (4:20–5:00) Limitations; how a developer would use this before Razorpay's real certification.

## 8. Known limitations to state openly

- Synthetic catalog, not a live merchant.
- 20 scenarios is a starting evidence set, not exhaustive coverage.
- Does not claim equivalence with Razorpay's internal certification pipeline.
- LLM judge (if used at all) is restricted to fuzzy truthfulness calls, never financial arithmetic.
