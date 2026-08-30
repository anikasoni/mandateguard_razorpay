import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { parseReadinessResponse } from './api/health'

const readyResponse = {
  status: 'ready',
  service: 'mandateguard-api',
  database: 'ok',
  timestamp: '2026-08-29T12:00:00Z',
}

function readinessWithTimestamp(timestamp: string) {
  return { ...readyResponse, timestamp }
}

describe('readiness timestamp validation', () => {
  it.each([
    '2026-08-29T10:00:00Z',
    '2026-08-29T10:00:00.123Z',
    '2026-08-29T10:36:45.461363Z',
    '2024-02-29T23:59:59Z',
  ])('accepts a complete backend UTC timestamp: %s', (timestamp) => {
    expect(parseReadinessResponse(readinessWithTimestamp(timestamp)).timestamp).toBe(timestamp)
  })

  it.each(['2026Z', '2026-08-29Z', '2026-08-29T10:00Z'])(
    'rejects an incomplete timestamp: %s',
    (timestamp) => {
      expect(() => parseReadinessResponse(readinessWithTimestamp(timestamp))).toThrow(
        'malformed readiness response',
      )
    },
  )

  it.each([
    '0000-01-01T00:00:00Z',
    '2026-00-01T00:00:00Z',
    '2026-13-01T00:00:00Z',
    '2026-02-29T00:00:00Z',
    '2024-02-30T00:00:00Z',
    '2026-04-31T00:00:00Z',
    '2026-08-29T25:00:00Z',
    '2026-08-29T10:60:00Z',
    '2026-08-29T10:00:60Z',
  ])('rejects an impossible calendar or clock value: %s', (timestamp) => {
    expect(() => parseReadinessResponse(readinessWithTimestamp(timestamp))).toThrow(
      'malformed readiness response',
    )
  })

  it.each([
    '2026-08-29T10:00:00+00:00',
    '2026-08-29T10:00:00+05:30',
    '2026-08-29T10:00:00-00:00',
    '2026-08-29T10:00:00z',
  ])('rejects a timezone form not emitted by the backend: %s', (timestamp) => {
    expect(() => parseReadinessResponse(readinessWithTimestamp(timestamp))).toThrow(
      'malformed readiness response',
    )
  })
})

describe('App', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('renders the foundation shell and reports backend readiness', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(readyResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(screen.getByRole('heading', { name: 'MandateGuard' })).toBeInTheDocument()
    expect(await screen.findByText('Backend ready')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/v1/health/ready',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
  })

  it('reports unavailable when the readiness response is malformed', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: 'ready' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
  })

  it('reports unavailable when the backend returns a non-success status', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'database unavailable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
  })

  it('reports unavailable when the readiness request has a network error', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('network unavailable'))

    render(<App />)

    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
  })

  it('aborts a timed-out readiness request and reports unavailable', async () => {
    vi.useFakeTimers()
    vi.mocked(fetch).mockImplementation((_input, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('request aborted', 'AbortError')),
          { once: true },
        )
      })
    })

    render(<App />)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })

    expect(screen.getByText('Backend unavailable')).toBeInTheDocument()
  })
})
