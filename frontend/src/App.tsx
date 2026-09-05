import { useEffect, useMemo, useState } from 'react'

import { fetchReadiness } from './api/health'
import {
  createPaymentOrder, decideApproval, evaluatePolicy, fetchBenchmark,
  openRazorpayCheckout, runAgent, verifyPayment,
  type AgentRun, type Approval, type BenchmarkReport, type CheckoutAttempt,
  type PaymentOrder, type PolicyStep,
} from './api/mandateguard'

type BackendState = 'checking' | 'ready' | 'unavailable'
type View = 'agent' | 'lab' | 'benchmark'
const products = {
  'desk-lamp': { price: 129_900, priceVersion: 3, inventoryVersion: 8 },
  'noise-cancelling-headphones': { price: 249_900, priceVersion: 5, inventoryVersion: 11 },
  'ergonomic-chair': { price: 279_900, priceVersion: 2, inventoryVersion: 6 },
  'travel-backpack': { price: 189_900, priceVersion: 1, inventoryVersion: 2 },
} as const
const ruleLabels: Record<string, string> = {
  'MG-001': 'Contract', 'MG-002': 'Idempotency', 'MG-003': 'Mandate',
  'MG-004': 'Currency', 'MG-005': 'Catalog', 'MG-006': 'Scope',
  'MG-007': 'Truthfulness', 'MG-008': 'Item cap', 'MG-009': 'Budget',
  'MG-010': 'Approval binding', 'MG-011': 'Human gate',
}

function id(prefix: string) { return `${prefix}-${crypto.randomUUID().replaceAll('-', '')}` }
function money(paise: number) { return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(paise / 100) }

function Pipeline({ run, paymentOrder, paymentStatus }: { run: AgentRun | null; paymentOrder: PaymentOrder | null; paymentStatus: 'idle' | 'paid' }) {
  const decision = run?.steps.at(-1)?.decision
  const stages = [
    { index: '01', title: 'User intent', detail: 'Natural language request', state: run ? 'complete' : 'active', trust: 'untrusted' },
    { index: '02', title: 'Gemini planner', detail: run ? `${run.plan.quantity} × ${run.plan.product_id.replaceAll('-', ' ')}` : 'Bounded structured proposal', state: run ? 'complete' : 'idle', trust: 'untrusted' },
    { index: '03', title: 'Policy firewall', detail: decision ? `${decision.rule_id} · ${decision.outcome.replace('_', ' ')}` : '11 deterministic checks', state: decision ? (decision.outcome === 'allow' ? 'complete' : 'blocked') : 'idle', trust: 'trusted' },
    { index: '04', title: 'Money movement', detail: paymentStatus === 'paid' ? 'Signature verified' : paymentOrder ? `${paymentOrder.provider_mode} order` : 'Human gate / Razorpay', state: paymentStatus === 'paid' ? 'complete' : paymentOrder ? 'active' : 'idle', trust: 'trusted' },
  ]
  return <section className="pipeline" aria-label="MandateGuard execution pipeline">
    <div className="boundary-label"><span>PROBABILISTIC</span><i /><span>DETERMINISTIC AUTHORITY</span></div>
    <div className="pipeline-grid">{stages.map((stage) => <article key={stage.index} className={`pipeline-node pipeline-node--${stage.state}`}>
      <div><span>{stage.index}</span><small>{stage.trust}</small></div><strong>{stage.title}</strong><p>{stage.detail}</p>
    </article>)}</div>
  </section>
}

function RuleMatrix({ step }: { step: PolicyStep | undefined }) {
  return <section className="rule-matrix">
    <div className="section-kicker"><span>POLICY COVERAGE</span><b>{step ? 'evaluated live' : 'awaiting request'}</b></div>
    <div className="rule-grid">{Object.entries(ruleLabels).map(([ruleId, label]) => {
      const evidence = step?.decision.evidence.find((item) => item.rule_id === ruleId)
      return <div key={ruleId} className={`rule-cell rule-cell--${evidence?.status ?? 'idle'}`} title={evidence?.reason}>
        <span>{ruleId.replace('MG-', '')}</span><small>{label}</small><i />
      </div>
    })}</div>
  </section>
}

function StepCard({ step, index }: { step: PolicyStep; index: number }) {
  const decisive = step.decision.evidence.find((item) => item.rule_id === step.decision.rule_id)
  const applicable = step.decision.evidence.filter((item) => item.status !== 'not_applicable').length
  return <article className={`trace trace--${step.decision.outcome}`}>
    <div className="trace-index">{String(index + 1).padStart(2, '0')}</div><div className="trace-body">
      <div className="trace__head"><span className="tool-name">{step.decision.request.tool?.replaceAll('_', ' ') ?? 'invalid request'}</span><span className="rule">{step.decision.rule_id}</span><strong>{step.decision.outcome.replace('_', ' ')}</strong><span>{step.decision.execution_mode}</span></div>
      <p>{step.decision.reason.replaceAll('_', ' ')}</p>
      {decisive && decisive.facts.length > 0 && <div className="facts">{decisive.facts.map((fact) => <code key={fact.key}>{fact.key}: {JSON.stringify(fact.value)}</code>)}</div>}
      <small>{applicable}/11 applicable · audit {step.audit_event_id.slice(0, 16)}… · fp {step.decision.fingerprint.slice(0, 10)}…</small>
    </div>
  </article>
}

function App() {
  const [backendState, setBackendState] = useState<BackendState>('checking')
  const [view, setView] = useState<View>('agent')
  const [prompt, setPrompt] = useState('Buy one desk lamp for my study table')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [run, setRun] = useState<AgentRun | null>(null)
  const [labSteps, setLabSteps] = useState<PolicyStep[]>([])
  const [humanKey, setHumanKey] = useState('')
  const [paymentOrder, setPaymentOrder] = useState<PaymentOrder | null>(null)
  const [paymentStatus, setPaymentStatus] = useState<'idle' | 'paid'>('idle')
  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetchReadiness({ signal: controller.signal }).then(() => setBackendState('ready')).catch(() => setBackendState('unavailable'))
    return () => controller.abort()
  }, [])

  const visibleSteps = useMemo(() => (view === 'agent' ? run?.steps ?? [] : labSteps), [labSteps, run?.steps, view])
  const latestStep = visibleSteps.at(-1)
  const approval = useMemo(() => visibleSteps.map((step) => step.approval).find((item): item is Approval => item !== null), [visibleSteps])
  const attempt = useMemo(() => [...visibleSteps].reverse().map((step) => step.checkout_attempt).find((item): item is CheckoutAttempt => item !== null), [visibleSteps])
  const proposedAmount = run ? (products[run.plan.product_id as keyof typeof products]?.price ?? 0) * run.plan.quantity : attempt?.amount_paise ?? 0

  async function execute(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action() } catch (caught) { setError(caught instanceof Error ? caught.message : 'Request failed') } finally { setBusy(false) }
  }
  function runAgentRequest() { void execute(async () => { setPaymentOrder(null); setPaymentStatus('idle'); setRun(await runAgent(prompt)) }) }
  function scenario(kind: 'valid' | 'cap' | 'urgency' | 'retry') {
    void execute(async () => {
      setPaymentOrder(null)
      const intent = id(`intent-${kind}`)
      const productId = kind === 'cap' ? 'ergonomic-chair' : 'desk-lamp'
      const product = products[productId]
      const tool = kind === 'urgency' ? 'present_offer' : 'create_checkout'
      const request = { request_id: id('request'), mandate_id: 'mandate-demo', tool, arguments: { product_id: productId, checkout_intent_id: intent, quantity: 1, currency: 'INR', quoted_unit_price_paise: product.price, price_version: product.priceVersion, inventory_version: product.inventoryVersion, ...(tool === 'present_offer' ? { claims: { claimed_inventory_count: 2 } } : { approval_id: null }) } }
      const first = await evaluatePolicy(request)
      setLabSteps(kind === 'retry' ? [first, await evaluatePolicy(request)] : [first])
    })
  }
  function grant() {
    if (!approval || !run) return
    void execute(async () => {
      await decideApproval(approval, humanKey, 'grant')
      const product = products[run.plan.product_id as keyof typeof products]
      if (!product) throw new Error('Selected product is unavailable')
      const response = await evaluatePolicy({ request_id: id('request-approved'), mandate_id: approval.mandate_id, tool: 'create_checkout', arguments: { product_id: run.plan.product_id, checkout_intent_id: approval.checkout_intent_id, quantity: run.plan.quantity, currency: 'INR', quoted_unit_price_paise: product.price, price_version: product.priceVersion, inventory_version: product.inventoryVersion, approval_id: approval.approval_id } })
      setRun({ ...run, status: 'checkout_reserved', steps: [...run.steps, response] })
    })
  }
  function createOrder() { if (attempt) void execute(async () => setPaymentOrder(await createPaymentOrder(attempt.attempt_id))) }
  function pay() {
    if (!paymentOrder) return
    void execute(async () => openRazorpayCheckout(paymentOrder, (response) => { void execute(async () => { await verifyPayment(response); setPaymentStatus('paid') }) }))
  }
  function loadBenchmark() { setView('benchmark'); if (!benchmark) void execute(async () => setBenchmark(await fetchBenchmark())) }

  return <main className="app-shell">
    <header className="topbar"><div><span className="logo-mark">M</span><strong role="heading" aria-level={2}>MandateGuard</strong><small>Runtime trust layer for agentic commerce</small></div><div className="top-signals"><span>POLICY v2A</span><span>APPEND-ONLY</span><span className={`backend backend--${backendState}`}><i />{backendState === 'ready' ? 'Backend ready' : backendState === 'unavailable' ? 'Backend unavailable' : 'Checking backend'}</span></div></header>
    <section className="hero"><div><p className="eyebrow">RAZORPAY AI BUILDATHON 2026 · TRACK 01</p><h1>The authorization layer<br /><em>AI commerce is missing.</em></h1><p>Gemini can propose. Only MandateGuard can authorize. Every rupee is checked against trusted state, exact human consent and replay-safe execution before payment.</p></div><aside className="hero-proof"><span>LIVE SAFETY POSTURE</span><strong>11</strong><p>deterministic controls</p><div><b>100%</b><small>violation catch*</small></div><div><b>0%</b><small>false blocks*</small></div><footer>*20 frozen gold scenarios</footer></aside></section>
    <Pipeline run={run} paymentOrder={paymentOrder} paymentStatus={paymentStatus} />
    <section className="mandate-strip"><div><span>Active mandate</span><strong>₹6,000</strong><small>stateful total budget</small></div><div><span>Per-item ceiling</span><strong>₹2,500</strong><small>hard backend boundary</small></div><div><span>Human checkpoint</span><strong>≥ ₹2,000</strong><small>exact intent binding</small></div><div><span>Execution guarantees</span><strong>INR · TTL · Replay</strong><small>atomic reservation</small></div></section>
    <nav className="tabs"><button className={view === 'agent' ? 'active' : ''} onClick={() => setView('agent')}><span>01</span> Live authorization</button><button className={view === 'lab' ? 'active' : ''} onClick={() => setView('lab')}><span>02</span> Adversarial lab</button><button className={view === 'benchmark' ? 'active' : ''} onClick={loadBenchmark}><span>03</span> MandateBench</button></nav>
    {error && <div className="error" role="alert">{error}</div>}
    <section className={`workspace ${view === 'benchmark' ? 'workspace--benchmark' : ''}`}><div className="control-panel">
      {view === 'agent' && <><div className="section-kicker"><span>UNTRUSTED AGENT ZONE</span><b>Gemini · structured output</b></div><h2>Propose a transaction</h2><p className="panel-copy">Use natural language. The model can choose—but it cannot spend, approve itself or bypass policy.</p><label htmlFor="prompt">PURCHASE INTENT</label><textarea id="prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} /><div className="suggestions">{['Buy one desk lamp', 'Buy noise-cancelling headphones', 'Buy an ergonomic chair', 'Desk lamp — only 2 left'].map((value) => <button key={value} onClick={() => setPrompt(value)}>{value}</button>)}</div><button className="primary" disabled={busy || backendState !== 'ready'} onClick={runAgentRequest}>{busy ? 'Evaluating proposal…' : 'Send through MandateGuard'}<span>→</span></button>{run && <div className="agent-plan"><div><span>{run.plan.provider === 'gemini' ? 'GEMINI LIVE PROPOSAL' : 'OFFLINE FALLBACK'}</span><b>UNTRUSTED</b></div><strong>{run.plan.quantity} × {run.plan.product_id.replaceAll('-', ' ')}</strong><p>{run.plan.rationale}</p><code>proposed_value {money(proposedAmount)}</code></div>}</>}
      {view === 'lab' && <><div className="section-kicker"><span>ADVERSARIAL TEST HARNESS</span><b>production policy engine</b></div><h2>Break the agent safely</h2><p className="panel-copy">Each case attacks a different commerce failure mode against real persisted policy state.</p><div className="scenario-grid"><button onClick={() => scenario('valid')}><b>01</b><span>Legitimate checkout<small>Control case · should authorize</small></span><code>ALLOW</code></button><button onClick={() => scenario('cap')}><b>02</b><span>Subtle item-cap breach<small>₹2,799 against ₹2,500 ceiling</small></span><code>MG-008</code></button><button onClick={() => scenario('urgency')}><b>03</b><span>Fabricated scarcity<small>Agent says 2; catalog says 12</small></span><code>MG-007</code></button><button onClick={() => scenario('retry')}><b>04</b><span>Timeout + exact retry<small>Same intent must not charge twice</small></span><code>MG-002</code></button></div></>}
      {view === 'benchmark' && <><div className="section-kicker"><span>REPRODUCIBLE AGENT EVALUATION</span><b>independent frozen labels</b></div><div className="benchmark-head"><div><h2>MandateBench / 20</h2><p>Policy correctness across mandate, truthfulness and distributed-state failures.</p></div>{benchmark && <div className="gold-score"><strong>{benchmark.gold_passed}/{benchmark.scenario_count}</strong><span>gold cases matched</span></div>}</div>{benchmark && <><div className="metric-grid">{Object.entries(benchmark.metrics).map(([name, metric]) => <article key={name} className={name === 'mandateguard' ? 'metric-featured' : ''}><span>{name.replaceAll('_', ' ')}</span><strong>{metric.violation_catch_rate}%</strong><small>violation catch</small><div><b>{metric.false_block_rate}%</b> false block · <b>{metric.decision_accuracy}%</b> accuracy</div></article>)}</div><small className="honesty">{benchmark.baseline_note}</small><div className="benchmark-rows"><header><b>ID</b><span>ADVERSARIAL SCENARIO</span><code>TERMINAL RULE</code><strong>RESULT</strong></header>{benchmark.rows.map((row) => <div key={row.scenario_id}><b>{row.scenario_id}</b><span>{row.description}<small>{row.family.replace('_', ' ')}</small></span><code>{row.mandateguard_rule_id}</code><strong>{row.passed ? 'PASS' : 'FAIL'}</strong></div>)}</div></>}</>}
    </div>
    {view !== 'benchmark' && <aside className="trace-panel"><div className="section-kicker"><span>TRUSTED ENFORCEMENT ZONE</span><b>backend authority</b></div><div className="trace-title"><div><h2>Authorization ledger</h2><p>Every decision is deterministic, persisted and fingerprinted.</p></div><b>{visibleSteps.length} events</b></div>{latestStep && <div className={`decision-banner decision-banner--${latestStep.decision.outcome}`}><div className="shield">{latestStep.decision.outcome === 'block' ? '×' : latestStep.decision.outcome === 'request_approval' ? '!' : '✓'}</div><div><span>FINAL AUTHORIZATION</span><strong>{latestStep.decision.outcome.replace('_', ' ')}</strong><p>{latestStep.decision.outcome === 'block' ? `${money(proposedAmount)} prevented from reaching payment` : latestStep.decision.outcome === 'request_approval' ? 'Funds remain locked until exact human consent' : 'Locally authorized; external execution remains gated'}</p></div><code>{latestStep.decision.rule_id}</code></div>}<RuleMatrix step={latestStep} />{visibleSteps.length === 0 ? <div className="empty-trace"><div className="empty-shield">M</div><strong>No transaction trusted yet</strong><span>Agent proposals will be decomposed into policy-checked actions here.</span></div> : <div className="trace-list">{visibleSteps.map((step, index) => <StepCard key={step.audit_event_id} step={step} index={index} />)}</div>}{run?.status === 'awaiting_human_approval' && approval && <div className="approval-box"><div><strong>Human checkpoint</strong><b>EXACT BINDING</b></div><span>{money(approval.amount_paise)} · intent {approval.checkout_intent_id.slice(0, 14)}…</span><input type="password" placeholder="Local human approval key" value={humanKey} onChange={(event) => setHumanKey(event.target.value)} /><button disabled={!humanKey || busy} onClick={grant}>Grant exact intent and resume</button></div>}{attempt && <div className="payment-box"><div><strong>Guarded reservation</strong><b>{attempt.status.toUpperCase()}</b></div><span>{money(attempt.amount_paise)} · {attempt.attempt_id.slice(0, 18)}…</span><button disabled={busy} onClick={createOrder}>Create Razorpay test order</button>{paymentOrder && <p><b>{paymentOrder.provider_mode === 'razorpay_test' ? 'RAZORPAY TEST MODE' : 'CLEARLY LABELLED SIMULATION'}</b><br />{paymentOrder.provider_order_id}</p>}{paymentOrder?.provider_mode === 'razorpay_test' && paymentStatus !== 'paid' && <button disabled={busy} onClick={pay}>Open Razorpay test checkout</button>}{paymentStatus === 'paid' && <strong className="paid">✓ Payment signature verified by backend</strong>}</div>}</aside>}
    </section>
    <footer className="page-footer"><span>DETERMINISTIC AUTHORITY</span><span>INTEGER PAISE</span><span>CONCURRENCY-SAFE RESERVATIONS</span><span>APPEND-ONLY AUDITS</span><i /><small>No claim of Razorpay certification equivalence</small></footer>
  </main>
}

export default App
