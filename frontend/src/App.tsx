import { useEffect, useState } from 'react'

import { fetchReadiness } from './api/health'

type BackendState = 'checking' | 'ready' | 'unavailable'

function App() {
  const [backendState, setBackendState] = useState<BackendState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    void fetchReadiness({ signal: controller.signal })
      .then(() => setBackendState('ready'))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setBackendState('unavailable')
        }
      })

    return () => controller.abort()
  }, [])

  const statusText = {
    checking: 'Checking backend…',
    ready: 'Backend ready',
    unavailable: 'Backend unavailable',
  }[backendState]

  return (
    <main className="shell">
      <section className="card" aria-labelledby="page-title">
        <p className="eyebrow">Razorpay AI Buildathon 2026</p>
        <h1 id="page-title">MandateGuard</h1>
        <p className="summary">
          Deterministic financial guardrails for AI purchasing agents.
        </p>
        <div className={`status status--${backendState}`} role="status" aria-live="polite">
          <span className="status__dot" aria-hidden="true" />
          {statusText}
        </div>
        <p className="phase-note">
          Phase 1 foundation: policy, agent, benchmark, and payment features are not implemented.
        </p>
      </section>
    </main>
  )
}

export default App
