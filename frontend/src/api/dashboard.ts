import type { Bet } from './runs'
import { readResults } from './results'

export interface PerformancePoint { date: string; profit: string; cumulative_profit: string }
export interface Dashboard {
  run_count: number; active_run_count: number; completed_run_count: number
  starting_bankroll_total: string; current_bankroll_total: string
  available_bankroll_total: string; committed_stake_total: string
  realized_profit: string; roi: string | null
  bet_count: number; open_bet_count: number
  win_count: number; loss_count: number; push_count: number; void_count: number
  recent_results: Bet[]; performance: PerformancePoint[]
}
export const getDashboard = (signal: AbortSignal) => readResults<Dashboard>('/dashboard', signal, 'dashboard')
