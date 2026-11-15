import { useEffect, useState } from 'react'
import { getGame } from '../api/games'
import type { Game } from '../api/games'
import type { Bet } from '../api/runs'

/** Read stored results independently of whether this Bet has been settled. */
export default function SavedBetScore({ bet }: { bet: Bet }) {
  const [game, setGame] = useState<Game | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setGame(null); setFailed(false)
    getGame(bet.game_id, controller.signal).then(value => {
      if (!controller.signal.aborted) setGame(value)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [bet.game_id, bet.settled_at])
  if (game?.status === 'completed' && game.home_score !== null && game.away_score !== null) {
    return <p>Final score: {bet.away_team} {game.away_score} · {bet.home_team} {game.home_score}</p>
  }
  // A stored settlement remains readable even if the current game read fails.
  if (failed && bet.settlement_game_status === 'completed' && bet.settlement_home_score != null && bet.settlement_away_score != null) {
    return <p>Final score (saved at settlement): {bet.away_team} {bet.settlement_away_score} · {bet.home_team} {bet.settlement_home_score}</p>
  }
  return failed ? <p>Game score unavailable. Reload saved Run detail to retry.</p> : null
}
