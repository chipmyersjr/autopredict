interface StrategyFields {
  id: string; name: string; description: string | null
  is_active: boolean
  created_at: string; updated_at: string
}
export type Strategy = StrategyFields & (
  { type: 'random'; config: Record<string, never> | null } |
  { type: 'agent'; config: { profile: 'FootballAnalysisExpert' } }
)
export interface Decision {
  game_id: string; market_id: string; selection_id: string; side: string
  line: string; price: string
  quote_provenance: { observation_id: string; bookmaker: string; source_timestamp: string | null; fetched_at: string } | null
}
const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
async function read<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${base}/api${path}`, {
    signal,
  })
  if (!response.ok) {
    const messages: Record<number, string> = { 404: 'A strategy or game is no longer available. Reload the page.', 409: 'This strategy is inactive.', 422: 'The selected games could not be submitted. Reload the page.', 503: 'The database is unavailable. Try again.' }
    throw new Error(messages[response.status] ?? 'The request failed. Try again.')
  }
  return response.json()
}
export const getStrategies = (signal: AbortSignal) => read<Strategy[]>('/strategies', signal)
