import type { Decision, Preview } from './strategies'
import { readResults } from './results'
export type SkippedGame = Preview['skipped_games'][number]
export interface RunCreate {
  strategy_id: string; game_ids: string[]; starting_bankroll: string; stake_per_bet: string
  name?: string; notes?: string
}
export interface Run {
  id: string; user_id: string; strategy_id: string; name: string | null; notes: string | null
  status: string; starting_bankroll: string; stake_per_bet: string; start_time: string
  end_time: string | null; final_bankroll: string | null; total_profit: string | null; roi: string | null
  created_at: string; updated_at: string; game_ids: string[]; bet_count: number
  committed_stake: string; available_bankroll: string; skipped_games: SkippedGame[]
  current_bankroll: string; settled_stake: string
  open_bet_count: number; settled_bet_count: number
  win_count: number; loss_count: number; push_count: number; void_count: number
}
export interface Bet extends Decision {
  id: string; run_id: string; home_team: string; away_team: string; kickoff_at_placement: string
  stake: string; status: string; result: string | null; profit: string | null
  placed_at: string; settled_at: string | null; created_at: string; updated_at: string
  settlement_home_score: number | null; settlement_away_score: number | null
  settlement_game_status: string | null
}
export interface RunResult { run: Run; bets: Bet[]; skipped_games: SkippedGame[] }
export interface SettlementResult {
  run: Run; bets: Bet[]; settled_bet_ids: string[]
  pending_games: { game_id: string; reason: 'game_not_final' | 'final_scores_missing' }[]
}
export const settleRun = (id: string, signal: AbortSignal) =>
  readResults<SettlementResult>(`/runs/${encodeURIComponent(id)}/settle`, signal, 'settlement')
export class RunApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
  get definite() { return [404, 409, 422, 503].includes(this.status) }
}
const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')
const safeDetails: Record<string, string> = {
  'Strategy inactive': 'This strategy is inactive. Choose an active strategy.',
  'No eligible games': 'No eligible games. Reload Games and select upcoming games with paired spreads.',
  'Insufficient starting bankroll for eligible games': 'Insufficient starting bankroll for eligible games. Increase the bankroll or reduce the stake.',
  'Idempotency-Key already used with different input': 'This request key was already used with different settings. Review Run history before starting a new request.',
  'Local simulation User is not configured; run python -m app.seed_user': 'The local simulator is not configured. Run the User bootstrap described in README, then retry.',
  'Database unavailable': 'The database is unavailable. Try again.',
}
async function read<T>(path: string, signal: AbortSignal, intent?: PendingRun): Promise<T> {
  const response = await fetch(`${base}/api${path}`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
    ...(intent ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': intent.key }, body: JSON.stringify(intent.body) } : {}),
  })
  if (!response.ok) {
    let detail: unknown
    try { detail = (await response.json()).detail } catch { /* Fall back to safe status wording. */ }
    const fallback: Record<number, string> = { 404: 'The requested Run, Bet, strategy or game was not found.', 409: 'The request conflicts with saved data. Review your settings and Run history.', 422: 'Check the game selection and positive money values (at most two decimal places).', 503: 'The simulator is unavailable. Check local setup and try again.' }
    throw new RunApiError(typeof detail === 'string' && safeDetails[detail] || fallback[response.status] || 'The request outcome is unknown. Retry with the saved request.', response.status)
  }
  return response.json()
}
export const getRuns = (signal: AbortSignal) => read<Run[]>('/runs', signal)
export const getRun = (id: string, signal: AbortSignal) => read<Run>(`/runs/${encodeURIComponent(id)}`, signal)
export const getRunBets = (id: string, signal: AbortSignal) => read<Bet[]>(`/runs/${encodeURIComponent(id)}/bets`, signal)
export const getBet = (id: string, signal: AbortSignal) => read<Bet>(`/bets/${encodeURIComponent(id)}`, signal)
export const createRun = (intent: PendingRun, signal: AbortSignal) => read<RunResult>('/runs', signal, intent)

export interface PendingRun { key: string; body: RunCreate }
export const pendingStorageKey = 'autopredict.pending-run.v1'
export const isUuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
export function moneyCents(value: string): bigint | null {
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return cents > 0n && cents <= 999999999999n ? cents : null
}
export function loadPending(): PendingRun | null {
  try {
    const raw = sessionStorage.getItem(pendingStorageKey)
    if (!raw) return null
    const intent = JSON.parse(raw)
    const b = intent?.body
    if (!isUuid(intent?.key) || !b || !isUuid(b.strategy_id) || !Array.isArray(b.game_ids) || !b.game_ids.length || !b.game_ids.every(isUuid) || new Set(b.game_ids).size !== b.game_ids.length || typeof b.starting_bankroll !== 'string' || moneyCents(b.starting_bankroll) === null || typeof b.stake_per_bet !== 'string' || moneyCents(b.stake_per_bet) === null || (b.name !== undefined && (typeof b.name !== 'string' || !b.name.trim() || b.name.length > 255)) || (b.notes !== undefined && typeof b.notes !== 'string') || Object.keys(b).some(k => !['strategy_id','game_ids','starting_bankroll','stake_per_bet','name','notes'].includes(k)) || Object.keys(intent).some(k => !['key','body'].includes(k))) {
      sessionStorage.removeItem(pendingStorageKey); return null
    }
    return intent
  } catch {
    try { sessionStorage.removeItem(pendingStorageKey) } catch { /* Storage may be disabled. */ }
    return null
  }
}
export function savePending(intent: PendingRun) { sessionStorage.setItem(pendingStorageKey, JSON.stringify(intent)) }
export function clearPending(key: string) {
  if (loadPending()?.key === key) sessionStorage.removeItem(pendingStorageKey)
}
