export interface Strategy {
  id: string; name: string; type: 'random'; description: string | null
  is_active: boolean; config: Record<string, unknown> | null
  created_at: string; updated_at: string
}
export interface Decision {
  game_id: string; market_id: string; selection_id: string; side: string
  line: string; price: string
  quote_provenance: { observation_id: string; bookmaker: string; source_timestamp: string | null; fetched_at: string } | null
}
export interface Preview {
  strategy_id: string; generated_at: string; requested_game_ids: string[]
  decisions: Decision[]
  skipped_games: { game_id: string; reason: 'game_not_scheduled' | 'kickoff_reached' | 'spread_unavailable' }[]
}
const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
async function read<T>(path: string, signal: AbortSignal, gameIds?: string[]): Promise<T> {
  const response = await fetch(`${base}/api${path}`, {
    signal, ...(gameIds ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ game_ids: gameIds }) } : {}),
  })
  if (!response.ok) {
    const messages: Record<number, string> = { 404: 'A strategy or game is no longer available. Reload the page.', 409: 'This strategy is inactive.', 422: 'The selected games could not be submitted. Reload the page.', 503: 'The database is unavailable. Try again.' }
    throw new Error(messages[response.status] ?? 'The request failed. Try again.')
  }
  return response.json()
}
export const getStrategies = (signal: AbortSignal) => read<Strategy[]>('/strategies', signal)
export const previewDecisions = (id: string, games: string[], signal: AbortSignal) => read<Preview>(`/strategies/${encodeURIComponent(id)}/decisions`, signal, games)
