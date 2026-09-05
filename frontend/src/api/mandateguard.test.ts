import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchBenchmark, runAgent } from './mandateguard'

describe('same-origin API requests', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses relative API paths for reads and writes', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchBenchmark()
    await runAgent('Buy one desk lamp')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/benchmark/report',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/agent/runs',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
