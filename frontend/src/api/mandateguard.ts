const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

export type DecisionOutcome = 'allow' | 'block' | 'request_approval'
export interface EvidenceFact { key: string; value: string | number | boolean | null | Array<string | number | boolean | null> }
export interface RuleEvidence { rule_id: string; status: 'pass' | 'fail' | 'not_applicable'; reason: string; facts: EvidenceFact[] }
export interface Decision { outcome: DecisionOutcome; rule_id: string; reason: string; evidence: RuleEvidence[]; execution_mode: 'execute' | 'replay' | 'retry_existing' | 'none'; fingerprint: string; evaluated_at: string }
export interface Approval { approval_id: string; mandate_id: string; checkout_intent_id: string; status: string; amount_paise: number; expires_at: string }
export interface CheckoutAttempt { attempt_id: string; checkout_intent_id: string; amount_paise: number; status: string }
export interface PolicyStep { audit_event_id: string; decision: Decision; approval: Approval | null; checkout_attempt: CheckoutAttempt | null }
export interface AgentRun { run_id: string; checkout_intent_id: string; plan: { product_id: string; quantity: number; claimed_inventory_count: number | null; rationale: string; provider: 'gemini' | 'offline_demo' }; status: 'blocked' | 'checkout_reserved' | 'awaiting_human_approval'; steps: PolicyStep[]; external_execution_authorized: false }
export interface PaymentOrder { provider_order_id: string; attempt_id: string; amount_paise: number; currency: 'INR'; status: 'created' | 'paid'; provider_mode: 'razorpay_test' | 'simulated'; checkout_key_id: string | null; replayed: boolean }
export interface BenchmarkRow { scenario_id: string; family: string; description: string; expected_outcome: string; expected_rule_id: string; mandateguard_outcome: string; mandateguard_rule_id: string; passed: boolean }
export interface BenchmarkReport { scenario_count: number; gold_passed: number; baseline_note: string; metrics: Record<string, { violation_catch_rate: number; false_block_rate: number; decision_accuracy: number }>; rows: BenchmarkRow[] }

async function post<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...headers }, body: JSON.stringify(body) })
  const payload: unknown = await response.json()
  if (!response.ok) throw new Error(typeof payload === 'object' && payload !== null ? JSON.stringify(payload) : `HTTP ${response.status}`)
  return payload as T
}

export function runAgent(userRequest: string): Promise<AgentRun> { return post('/api/v1/agent/runs', { mandate_id: 'mandate-demo', user_request: userRequest }) }
export function evaluatePolicy(request: unknown): Promise<PolicyStep & { external_execution_authorized: false }> { return post('/api/v1/policy/evaluations', request) }
export function decideApproval(approval: Approval, key: string, decision: 'grant' | 'reject') { return post<{ approval: Approval; replayed: boolean }>(`/api/v1/human/mandates/${approval.mandate_id}/approvals/${approval.approval_id}/decisions`, { checkout_intent_id: approval.checkout_intent_id, decision }, { 'X-MandateGuard-Human-Key': key }) }
export function createPaymentOrder(attemptId: string): Promise<PaymentOrder> { return post('/api/v1/payments/orders', { attempt_id: attemptId }) }
export function verifyPayment(response: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }): Promise<{ status: 'paid' }> { return post('/api/v1/payments/verify', { provider_order_id: response.razorpay_order_id, provider_payment_id: response.razorpay_payment_id, signature: response.razorpay_signature }) }
export async function fetchBenchmark(): Promise<BenchmarkReport> { const response = await fetch(`${API_BASE}/api/v1/benchmark/report`, { headers: { Accept: 'application/json' } }); if (!response.ok) throw new Error(`Benchmark failed with HTTP ${response.status}`); return response.json() as Promise<BenchmarkReport> }

interface RazorpaySuccess { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }
type RazorpayConstructor = new (options: Record<string, unknown>) => { open: () => void }

export async function openRazorpayCheckout(order: PaymentOrder, onSuccess: (response: RazorpaySuccess) => void): Promise<void> {
  if (!order.checkout_key_id) throw new Error('Razorpay test checkout is not configured')
  if (!document.querySelector('script[data-mandateguard-razorpay]')) {
    await new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://checkout.razorpay.com/v1/checkout.js'
      script.dataset.mandateguardRazorpay = 'true'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Could not load Razorpay Checkout'))
      document.head.append(script)
    })
  }
  const Razorpay = (window as Window & { Razorpay?: RazorpayConstructor }).Razorpay
  if (!Razorpay) throw new Error('Razorpay Checkout did not initialize')
  new Razorpay({ key: order.checkout_key_id, amount: order.amount_paise, currency: order.currency, order_id: order.provider_order_id, name: 'MandateGuard Demo', description: 'Guarded test-mode purchase', handler: onSuccess, theme: { color: '#d9ff43' } }).open()
}
