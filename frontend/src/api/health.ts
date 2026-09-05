export interface ReadinessResponse {
  status: 'ready'
  service: 'mandateguard-api'
  database: 'ok'
  timestamp: string
}

export interface ReadinessRequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

export const DEFAULT_READINESS_TIMEOUT_MS = 5_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isUtcTimestamp(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false
  }

  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$/.exec(value)
  if (!match) {
    return false
  }

  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match
  const year = Number(yearText)
  const month = Number(monthText)
  const day = Number(dayText)
  const hour = Number(hourText)
  const minute = Number(minuteText)
  const second = Number(secondText)

  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return false
  }

  const isLeapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysInMonth = [31, isLeapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

  return day >= 1 && day <= daysInMonth[month - 1]
}

export function parseReadinessResponse(value: unknown): ReadinessResponse {
  if (
    !isRecord(value) ||
    value.status !== 'ready' ||
    value.service !== 'mandateguard-api' ||
    value.database !== 'ok' ||
    !isUtcTimestamp(value.timestamp)
  ) {
    throw new Error('Backend returned a malformed readiness response')
  }

  return {
    status: value.status,
    service: value.service,
    database: value.database,
    timestamp: value.timestamp,
  }
}

export async function fetchReadiness(
  options: ReadinessRequestOptions = {},
): Promise<ReadinessResponse> {
  const { signal, timeoutMs = DEFAULT_READINESS_TIMEOUT_MS } = options
  const requestController = new AbortController()
  let timedOut = false

  const abortFromCaller = () => requestController.abort()
  if (signal?.aborted) {
    abortFromCaller()
  } else {
    signal?.addEventListener('abort', abortFromCaller, { once: true })
  }

  const timeout = globalThis.setTimeout(() => {
    timedOut = true
    requestController.abort()
  }, timeoutMs)

  try {
    const response = await fetch('/api/v1/health/ready', {
      headers: { Accept: 'application/json' },
      signal: requestController.signal,
    })

    if (!response.ok) {
      throw new Error(`Backend readiness failed with HTTP ${response.status}`)
    }

    const payload: unknown = await response.json()
    return parseReadinessResponse(payload)
  } catch (error: unknown) {
    if (timedOut) {
      throw new Error(`Backend readiness timed out after ${timeoutMs}ms`, { cause: error })
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeout)
    signal?.removeEventListener('abort', abortFromCaller)
  }
}
