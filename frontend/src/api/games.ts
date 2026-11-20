interface Timestamps { created_at: string; updated_at: string }
export interface Selection extends Timestamps {
  id: string; market_id: string; side: string; line: string | null
  price: string; is_active: boolean; notes: string | null
  quote_provenance?: { observation_id: string; bookmaker: string; source_timestamp: string | null; fetched_at: string } | null
}
export interface Market extends Timestamps {
  id: string; game_id: string; type: string; status: string
  description: string | null; selections: Selection[]
}
export interface Game extends Timestamps {
  id: string; season: number; week: number; home_team: string; away_team: string
  start_time: string; status: string; home_score: number | null; away_score: number | null
  venue: string | null; notes: string | null; markets: Market[]
}
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
export async function getGame(id: string, signal: AbortSignal): Promise<Game> {
  const response = await fetch(`${baseUrl}/api/games/${encodeURIComponent(id)}`, { signal })
  if (!response.ok) throw new Error('Unable to load game')
  return response.json()
}
export async function getGames(signal: AbortSignal, window?: 'current'): Promise<Game[]> {
  const response = await fetch(`${baseUrl}/api/games${window ? '?window=current' : ''}`, { signal })
  if (!response.ok) throw new Error('Unable to load games')
  return response.json()
}

export interface RefreshResult {
  success: boolean; reason: string; message: string
  remaining_refreshes: number | null; reserved_for_sunday: number
  retry_at: string | null; data_changed: boolean; run_id: string | null
}
export async function refreshGames(signal: AbortSignal): Promise<RefreshResult> {
  const response = await fetch(`${baseUrl}/api/games/refresh`, { method: 'POST', signal })
  const value = await response.json()
  const nullableString = (v: unknown) => v === null || typeof v === 'string'
  const count = (v: unknown) => typeof v === 'number' && Number.isInteger(v) && v >= 0
  if (!value || typeof value.success !== 'boolean' || typeof value.reason !== 'string' || !value.reason ||
    typeof value.message !== 'string' || !value.message.trim() || typeof value.data_changed !== 'boolean' ||
    !(value.remaining_refreshes === null || count(value.remaining_refreshes)) || !count(value.reserved_for_sunday) ||
    !nullableString(value.retry_at) || !nullableString(value.run_id)) throw new Error('Invalid refresh response')
  return value
}
