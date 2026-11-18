/** Bounded public errors: never display arbitrary server/proxy response text. */
export class ResultsApiError extends Error {
  constructor(message: string, public status: number, public definite: boolean) { super(message) }
}

const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const uncertain = 'Settlement may have been saved. Retry settlement safely or reload saved Run detail.'
const settlementErrors: Record<number, string> = {
  404: 'The requested Run was not found. Reload Run history.',
  409: 'The saved settlement data cannot be resolved safely. Reload saved Run detail before retrying.',
  422: 'The settlement request is invalid. Reload saved Run detail and try again.',
  503: 'The simulator is unavailable. Check local setup and retry settlement.',
}

export async function readResults<T>(path: string, signal: AbortSignal, kind: 'settlement' | 'dashboard'): Promise<T> {
  const settlement = kind === 'settlement'
  try {
    const response = await fetch(`${base}/api${path}`, {
      method: settlement ? 'POST' : 'GET',
      signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
    })
    if (!response.ok) {
      const definite = [404, 409, 422, 503].includes(response.status)
      const message = settlement
        ? settlementErrors[response.status] ?? uncertain
        : response.status === 503 ? 'The dashboard is unavailable. Check local setup and try again.' : 'Could not load the dashboard. Try again.'
      throw new ResultsApiError(message, response.status, definite)
    }
    return await response.json()
  } catch (error) {
    // Navigation cancellation belongs to the caller; do not turn it into an alert.
    if (signal.aborted) throw error
    if (error instanceof ResultsApiError) throw error
    throw new ResultsApiError(settlement ? uncertain : 'Could not load the dashboard. Try again.', 0, false)
  }
}
