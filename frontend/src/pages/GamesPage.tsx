import { useEffect, useRef, useState } from 'react'
import { getGames } from '../api/games'
import { getStrategies, previewDecisions } from '../api/strategies'
import type { Strategy, Preview } from '../api/strategies'
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
export function unavailableReason(game: Game, now = Date.now()): string | null {
  if (game.status !== 'scheduled') return 'Game is not scheduled'
  if (!Number.isFinite(Date.parse(game.start_time))) return 'Kickoff unknown'
  if (Date.parse(game.start_time) <= now) return 'Kickoff reached'
  const valid = game.markets.some(m => {
    const pair = m.selections.filter(s => s.is_active)
    return m.type === 'spread' && m.status === 'active' && pair.length === 2 && game.home_team !== game.away_team &&
      new Set(pair.map(s => s.side)).size === 2 && pair.every(s => [game.home_team, game.away_team].includes(s.side) && s.line !== null && Number.isFinite(Number(s.line)) && Number.isFinite(Number(s.price)) && Number(s.price) > 1) && Number(pair[0].line) === -Number(pair[1].line)
  })
  return valid ? null : 'No eligible paired spread'
}
function GameCard({ game, selected, toggle, now }: { game: Game; selected: boolean; toggle: () => void; now: number }) {
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
      <time dateTime={game.start_time}>{Number.isFinite(Date.parse(game.start_time)) ? kickoffFormat.format(new Date(game.start_time)) : 'Kickoff unknown'}</time>
      {game.venue && <p className="venue">{game.venue}</p>}
      {(game.away_score !== null || game.home_score !== null) && (
        <p className="scores">Score: {game.away_team} {game.away_score ?? '—'} · {game.home_team} {game.home_score ?? '—'}</p>
      )}
      <label className="game-select"><input type="checkbox" checked={selected} disabled={Boolean(unavailableReason(game, now))} onChange={toggle} /> Select {game.away_team} at {game.home_team}</label>
      {unavailableReason(game, now) && <p className="unavailable">{unavailableReason(game, now)}</p>}
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
  const [strategies, setStrategies] = useState<Strategy[] | null>(null)
  const [strategyError, setStrategyError] = useState(false)
  const [strategyAttempt, setStrategyAttempt] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const pending = useRef<AbortController | null>(null)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => { clearInterval(timer); pending.current?.abort() }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setStrategies(null); setStrategyError(false)
    getStrategies(controller.signal).then(items => { if (!controller.signal.aborted) setStrategies(items) }).catch(() => { if (!controller.signal.aborted) setStrategyError(true) })
    return () => controller.abort()
  }, [strategyAttempt])
  const strategy = strategies?.find(s => s.id === '40000000-0000-4000-8000-000000000001')
  function toggle(id: string) {
    pending.current?.abort(); pending.current = null; setBusy(false); setPreview(null); setError(null)
    setSelected(ids => ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id])
  }
  async function execute() {
    if (!strategy?.is_active || !selected.length || pending.current) return
    const controller = new AbortController()
    pending.current = controller; setBusy(true); setError(null); setPreview(null)
    try {
      const result = await previewDecisions(strategy.id, selected, controller.signal)
      if (!controller.signal.aborted) setPreview(result)
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Unable to generate decisions. Try again.')
    } finally {
      if (pending.current === controller) { pending.current = null; setBusy(false) }
    }
  }
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
      {state.status === 'success' && state.games.length > 0 && <section className="state-panel strategy-panel" aria-label="Random Strategy">
        <h2>Random Strategy</h2>
        <p>Preview one randomly chosen spread per eligible game. The server checks eligibility when you execute.</p>
        {strategyError ? <><p role="alert">Strategies couldn’t be loaded.</p><button onClick={() => setStrategyAttempt(n => n + 1)}>Retry strategies</button></> : strategies === null ? <p>Loading strategy…</p> : !strategy ? <p>Random Strategy unavailable</p> : !strategy.is_active ? <p>Random Strategy inactive</p> : null}
        <p>{selected.length} games selected</p>
        <button disabled={!selected.length || !strategy?.is_active || busy} onClick={execute}>{busy ? 'Generating decisions…' : 'Execute Random Strategy'}</button>
        {error && <p role="alert">{error}</p>}
        <div aria-live="polite">{busy && <p>Generating decision preview…</p>}</div>
        {preview && <section className="decision-results" aria-label="Decision preview">
          <h2>Decision preview</h2>
          <p>Generated <time dateTime={preview.generated_at}>{kickoffFormat.format(new Date(preview.generated_at))}</time>. No bets recorded.</p>
          {!preview.decisions.length && <p>No eligible games — all selected games were skipped.</p>}
          <ul>{preview.decisions.map(d => <li key={d.game_id}>
            <p>{state.games.find(g => g.id === d.game_id)?.away_team} at {state.games.find(g => g.id === d.game_id)?.home_team}</p>
            <strong>{d.side} {formatLine(d.line)}</strong> · Decimal odds <strong>{d.price}</strong>
            {d.quote_provenance && <p>Saved quote from {d.quote_provenance.bookmaker} · Fetched {d.quote_provenance.fetched_at}{d.quote_provenance.source_timestamp && ` · Source ${d.quote_provenance.source_timestamp}`}</p>}
          </li>)}</ul>
          <ul>{preview.skipped_games.map(skip => <li key={skip.game_id}>{state.games.find(g => g.id === skip.game_id)?.away_team} at {state.games.find(g => g.id === skip.game_id)?.home_team}: {{ game_not_scheduled: 'Game is not scheduled', kickoff_reached: 'Kickoff reached', spread_unavailable: 'Spread unavailable' }[skip.reason]}</li>)}</ul>
        </section>}
      </section>}
      {state.status === 'success' && (state.games.length === 0
        ? <div className="state-panel"><h2>No games stored yet</h2><p>Games will appear here when data is available.</p></div>
        : <ul className="games-list">{state.games.map(game => <li key={game.id}><GameCard game={game} selected={selected.includes(game.id)} toggle={() => toggle(game.id)} now={now} /></li>)}</ul>)}
    </main>
  )
}
