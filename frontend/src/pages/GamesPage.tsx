import { useEffect, useState } from 'react'
import { getGames } from '../api/games'
import type { Game } from '../api/games'

export function formatLine(line: string): string {
  if (/^[+-]?0+(\.0+)?$/.test(line)) return 'Pick’em'
  const trimmed = line.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return trimmed.startsWith('-') || trimmed.startsWith('+') ? trimmed : `+${trimmed}`
}
const kickoffFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})
function GameCard({ game }: { game: Game }) {
  const markets = game.markets.filter(m => m.type === 'spread' && m.status === 'active')
    .map(m => ({ ...m, selections: m.selections.filter(s => s.is_active && s.line !== null) }))
    .filter(m => m.selections.length > 0)
  return (
    <article className="game-card" aria-labelledby={`game-${game.id}`}>
      <header className="game-header">
        <p className="eyebrow">{game.season} · Week {game.week}</p>
        <span className="badge">{game.status.replaceAll('_', ' ')}</span>
      </header>
      <h2 id={`game-${game.id}`}>{game.away_team} <span className="at">at</span> {game.home_team}</h2>
      <time dateTime={game.start_time}>{kickoffFormat.format(new Date(game.start_time))}</time>
      {game.venue && <p className="venue">{game.venue}</p>}
      {(game.away_score !== null || game.home_score !== null) && (
        <p className="scores">Score: {game.away_team} {game.away_score ?? '—'} · {game.home_team} {game.home_score ?? '—'}</p>
      )}
      <div className="spreads">
        {markets.length === 0 ? <p className="unavailable">Spread unavailable</p> : markets.map((market, index) => (
          <section key={market.id} aria-label={`Spread market ${index + 1}`}>
            <h3>Spread{markets.length > 1 ? ` · Market ${index + 1}` : ''}</h3>
            <ul className="selections">{market.selections.map(selection => (
              <li key={selection.id}>
                <span className="selection-team">{selection.side}</span>
                <strong className="line">{formatLine(selection.line!)}</strong>
                <span className="price">Decimal odds <strong>{selection.price}</strong></span>
              </li>
            ))}</ul>
          </section>
        ))}
      </div>
    </article>
  )
}
type State = { status: 'loading' } | { status: 'error' } | { status: 'success'; games: Game[] }
export default function GamesPage() {
  const [state, setState] = useState<State>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    getGames(controller.signal).then(games => {
      if (!controller.signal.aborted) setState({ status: 'success', games })
    }).catch(() => {
      if (!controller.signal.aborted) setState({ status: 'error' })
    })
    return () => controller.abort()
  }, [attempt])
  return (
    <main>
      <header className="page-header">
        <p className="brand">AutoPredict <span> / College football</span></p>
        <h1>Games</h1>
        <p className="intro">College football matchups and stored spread selections.</p>
        <p className="demo-note"><strong>Demo data</strong> · Fictional games and odds for the simulator. These are not current schedules or live prices.</p>
      </header>
      <div role="status" aria-live="polite">
        {state.status === 'loading' && <p className="state-panel">Loading games…</p>}
        {state.status === 'success' && <p className="results-summary">{state.games.length} {state.games.length === 1 ? 'game' : 'games'} · Kickoff times in your local timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone})</p>}
      </div>
      {state.status === 'error' && <div className="state-panel error-panel" role="alert">
        <h2>Games couldn’t be loaded</h2>
        <p>Check that the backend is running, then try again.</p>
        <button onClick={() => { setState({ status: 'loading' }); setAttempt(n => n + 1) }}>Retry</button>
      </div>}
      {state.status === 'success' && (state.games.length === 0
        ? <div className="state-panel"><h2>No games stored yet</h2><p>Games will appear here when data is available.</p></div>
        : <ul className="games-list">{state.games.map(game => <li key={game.id}><GameCard game={game} /></li>)}</ul>)}
    </main>
  )
}
