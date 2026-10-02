interface Timestamps { created_at: string; updated_at: string }
export interface Selection extends Timestamps {
  id: string; market_id: string; side: string; line: string | null
  price: string; is_active: boolean; notes: string | null
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
export async function getGames(signal: AbortSignal): Promise<Game[]> {
  const response = await fetch(`${baseUrl}/api/games`, { signal })
  if (!response.ok) throw new Error('Unable to load games')
  return response.json()
}
