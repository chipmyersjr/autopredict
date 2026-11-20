import { useEffect, useRef, useState } from 'react'
import { getGames, refreshGames } from '../api/games'
import { getStrategies } from '../api/strategies'
import type { Strategy } from '../api/strategies'
import type { Game } from '../api/games'
import DryRunForm from '../components/DryRunForm'

import { formatLine } from '../format'
export { formatLine } from '../format'

const kickoffFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  timeZone: 'America/Los_Angeles',
})
function teamLabel(game: Game | undefined, side: string): string {
  if (side === 'home') return game?.home_team ?? side
  if (side === 'away') return game?.away_team ?? side
  return side
}
export function unavailableReason(game: Game, now = Date.now()): string | null {
  if (game.status !== 'scheduled') return 'Game is not scheduled'
  if (!Number.isFinite(Date.parse(game.start_time))) return 'Kickoff unknown'
  if (Date.parse(game.start_time) <= now) return 'Kickoff reached'
  const valid = game.markets.some(m => {
    const pair = m.selections.filter(s => s.is_active)
    const sides = new Set(pair.map(s => s.side))
    const completeSides = sides.size === 2 && (
      (sides.has('home') && sides.has('away')) ||
      (sides.has(game.home_team) && sides.has(game.away_team))
    )
    return m.type === 'spread' && m.status === 'active' && pair.length === 2 && game.home_team !== game.away_team &&
      completeSides && pair.every(s => s.line !== null && s.line.trim() !== '' && Number.isFinite(Number(s.line)) && Number.isFinite(Number(s.price)) && Number(s.price) > 1) && Number(pair[0].line) === -Number(pair[1].line)
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
      {game.notes?.startsWith('Demo data:') && <p className="demo-note"><strong>Demo data</strong> · Fictional games and odds for the simulator. These are not current schedules or live prices.</p>}
      {game.status === 'scheduled' && Date.parse(game.start_time) <= now && <p>Kickoff reached · Awaiting provider status update</p>}
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
                <span className="selection-team">{teamLabel(game, selection.side)}</span>
                <strong className="line">{formatLine(selection.line!)}</strong>
                <span className="price">Decimal odds <strong>{selection.price}</strong></span>
                {selection.quote_provenance && <span>Bookmaker: {selection.quote_provenance.bookmaker} · Saved {kickoffFormat.format(new Date(selection.quote_provenance.fetched_at))}</span>}
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
  const [strategyId, setStrategyId] = useState<string>()
  const [step, setStep] = useState<'strategy' | 'games' | 'finalize'>('strategy')
  const [pending, setPending] = useState(false)
  const initialized = useRef(false)
  const [reviewChanged, setReviewChanged] = useState(false)
  const [now, setNow] = useState(Date.now())
  const refreshPending = useRef<AbortController | null>(null)
  const refreshButton = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null)
  useEffect(() => () => { refreshPending.current?.abort() }, [])
  useEffect(() => {
    if (refreshMessage !== null) dialog.current?.showModal()
  }, [refreshMessage])
  async function refresh() {
    if (refreshPending.current) return
    const controller = new AbortController()
    refreshPending.current = controller
    setRefreshing(true)
    try {
      const result = await refreshGames(controller.signal)
      if (controller.signal.aborted) return
      setRefreshMessage(result.message)
      if (result.data_changed) {
        setReviewChanged(true)
        setAttempt(n => n + 1)
      }
    } catch {
      if (!controller.signal.aborted) setRefreshMessage('Refresh failed. Unable to refresh games. Please try again.')
    } finally {
      if (refreshPending.current === controller) {
        refreshPending.current = null
        if (!controller.signal.aborted) setRefreshing(false)
      }
    }
  }
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => { clearInterval(timer) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setStrategies(null); setStrategyError(false)
    getStrategies(controller.signal).then(items => { if (!controller.signal.aborted) setStrategies(items) }).catch(() => { if (!controller.signal.aborted) setStrategyError(true) })
    return () => controller.abort()
  }, [strategyAttempt])
  const strategy = strategies?.find(s => s.id === strategyId && s.is_active)
  function toggle(id: string) {
    setSelected(ids => ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id])
  }
  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    getGames(controller.signal, 'current').then(games => {
      if (!controller.signal.aborted) {
        if (!initialized.current) {
          // An empty week may later acquire games through explicit Refresh.
          if (games.length) {
            setSelected(games.filter(game => !unavailableReason(game)).map(game => game.id))
            initialized.current = true
          }
        } else setSelected(ids => ids.filter(id => games.some(game => game.id === id && !unavailableReason(game))))
        setState({ status: 'success', games })
      }
    }).catch(() => {
      if (!controller.signal.aborted) setState({ status: 'error' })
    })
    return () => controller.abort()
  }, [attempt])
  useEffect(() => {
    if (state.status !== 'success') return
    const eligible = new Set(state.games.filter(game => !unavailableReason(game, now)).map(game => game.id))
    if (selected.some(id => !eligible.has(id))) {
      setSelected(ids => ids.filter(id => eligible.has(id)))
      setReviewChanged(true)
    }
  }, [now, state, selected])
  const eligibleSelected = state.status === 'success' ? selected.filter(id => state.games.some(game => game.id === id && !unavailableReason(game, now))) : []
  return (
    <main>
      <header className="page-header">
        <p className="brand">AutoPredict <span> / College football</span></p>
        <h1>Games</h1>
        <p className="intro">College football matchups and stored spread selections.</p>
        <p>Odds are saved observations, not guaranteed live prices.</p>
        <button ref={refreshButton} disabled={refreshing} onClick={refresh}>{refreshing ? 'Refreshing…' : 'Refresh'}</button>
      </header>
      <dialog ref={dialog} aria-labelledby="refresh-title" aria-describedby="refresh-message"
        onKeyDown={event => {
          // The dialog has one focusable control. Keep both tab directions on it,
          // including in browsers that otherwise move focus to browser chrome.
          if (event.key === 'Tab') {
            event.preventDefault()
            event.currentTarget.querySelector('button')?.focus()
          }
        }}
        onClose={() => { setRefreshMessage(null); refreshButton.current?.focus() }}>
        <h2 id="refresh-title">Refresh result</h2>
        <p id="refresh-message">{refreshMessage}</p>
        <button autoFocus onClick={() => dialog.current?.close()}>Close</button>
      </dialog>
      <div role="status" aria-live="polite">
        {state.status === 'loading' && <p className="state-panel">Loading games…</p>}
        {state.status === 'success' && <p className="results-summary">{state.games.length} {state.games.length === 1 ? 'game' : 'games'} · Kickoff times in Pacific time</p>}
      </div>
      {state.status === 'error' && <div className="state-panel error-panel" role="alert">
        <h2>Games couldn’t be loaded</h2>
        <p>Check that the backend is running, then try again.</p>
        <button onClick={() => { setState({ status: 'loading' }); setAttempt(n => n + 1) }}>Retry</button>
      </div>}
      <p aria-label="Run creation steps">1 · Strategy → 2 · Games → 3 · Finalize</p>
      <fieldset disabled={pending} className="creation-controls">
      {step === 'strategy' && <section className="state-panel strategy-panel" aria-label="Choose a strategy">
        <h2>1 · Choose a strategy</h2>
        <p>Choose a shared Strategy. Predictions start only after final submission.</p>
        {strategyError ? <><p role="alert">Strategies couldn’t be loaded.</p><button onClick={() => setStrategyAttempt(n => n + 1)}>Retry strategies</button></> : strategies === null ? <p>Loading strategies…</p> : <>
          {!strategies.some(s => s.is_active) && <p>No active strategies available.</p>}
          <div className="strategy-options" role="radiogroup" aria-label="Strategy">
            {strategies.map(item => <label className="strategy-option" key={item.id}>
              <input type="radio" name="strategy" value={item.id} checked={strategyId === item.id} disabled={!item.is_active} onChange={() => setStrategyId(item.id)} />
              <strong>{item.name}</strong><span>{item.description}</span>{!item.is_active && <span>Inactive</span>}
            </label>)}
          </div>
        </>}
        <button disabled={!strategy} onClick={() => setStep('games')}>Continue to Games</button>
      </section>}
      {step !== 'strategy' && <section className="state-panel" aria-label="Select games">
        <h2>2 · Select games</h2>
        <p>Strategy: {strategy?.name ?? 'Unavailable'} · {eligibleSelected.length} games selected</p>
        <button className="secondary" onClick={() => setStep('strategy')}>Back to Strategy</button>{' '}
        <button disabled={state.status !== 'success'} onClick={() => {
          if (state.status === 'success') setSelected(state.games.filter(game => !unavailableReason(game, now)).map(game => game.id))
        }}>Select All eligible games</button>{' '}
        <button disabled={!strategy || !eligibleSelected.length || state.status !== 'success' || refreshing || reviewChanged} onClick={() => setStep('finalize')}>Continue to Finalize</button>
      </section>}
      {reviewChanged && <div className="state-panel" role="status"><p>Saved games or odds changed. Unavailable or missing games were removed from your selection. Review the current games before submitting.</p><button onClick={() => { setStep('games'); setReviewChanged(false) }}>Review updated games</button></div>}
      </fieldset>
      <DryRunForm selected={eligibleSelected} strategyId={strategy?.id} enabled={Boolean(strategy) && state.status === 'success' && !refreshing && !reviewChanged}
        visible={step === 'finalize'} onPending={setPending} onBack={() => setStep('games')}
        review={<><p>Strategy: <strong>{strategy?.name ?? 'Unavailable'}</strong></p><ul>{state.status === 'success' && state.games.filter(game => eligibleSelected.includes(game.id)).map(game => <li key={game.id}>{game.away_team} at {game.home_team} · {kickoffFormat.format(new Date(game.start_time))}</li>)}</ul></>} />
      <fieldset disabled={pending} className="creation-controls">
      {state.status === 'success' && (state.games.length === 0
        ? <div className="state-panel"><h2>No games stored yet</h2><p>No games stored for this week. Use Refresh to load this week’s FBS games.</p></div>
        : <ul className="games-list">{state.games.map(game => <li key={game.id}><GameCard game={game} selected={eligibleSelected.includes(game.id)} toggle={() => toggle(game.id)} now={now} /></li>)}</ul>)}
      </fieldset>
    </main>
  )
}
