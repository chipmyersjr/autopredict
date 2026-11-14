import { useEffect, useState } from 'react'
import { getRun, getRunBets, getRuns, isUuid, RunApiError } from '../api/runs'
import type { Bet, Run } from '../api/runs'
import { getStrategies } from '../api/strategies'
import { formatLine } from './GamesPage'

const date = (value: string) => new Date(value).toLocaleString(undefined, { timeZoneName: 'short' })
const skipLabels = { game_not_scheduled: 'Game is not scheduled', kickoff_reached: 'Kickoff reached', spread_unavailable: 'Spread unavailable' }
function ErrorPanel({ message, retry }: { message: string; retry: () => void }) {
  return <div className="state-panel error-panel" role="alert"><p>{message}</p><button onClick={retry}>Retry</button>{' '}<a href="#/runs">Run history</a></div>
}
function useStrategyNames() {
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    const controller = new AbortController()
    getStrategies(controller.signal).then(items => { if (!controller.signal.aborted) setNames(Object.fromEntries(items.map(s => [s.id, s.name]))) }).catch(() => {})
    return () => controller.abort()
  }, [])
  return names
}
export function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null), [error, setError] = useState<string | null>(null), [attempt, setAttempt] = useState(0)
  const names = useStrategyNames()
  useEffect(() => {
    const controller = new AbortController(); setRuns(null); setError(null)
    getRuns(controller.signal).then(items => { if (!controller.signal.aborted) setRuns(items) }).catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Runs could not be loaded.') })
    return () => controller.abort()
  }, [attempt])
  return <main><header className="page-header"><p className="brand">AutoPredict / Simulations</p><h1>Runs</h1><p className="intro">Saved theoretical simulations and their Bet snapshots.</p></header>
    {error ? <ErrorPanel message={error} retry={() => setAttempt(n => n + 1)} /> : runs === null ? <p className="state-panel" role="status">Loading Runs…</p> : !runs.length ? <div className="state-panel"><h2>No Runs yet</h2><p>Select games to create your first simulation.</p><a href="#/games">Choose games</a></div> : <ul className="history-list">{runs.map(run => <li key={run.id}><article className="state-panel">
      <h2><a href={`#/runs/${run.id}`}>{run.name ?? `Run ${run.id.slice(0, 8)}`}</a></h2>
      <p>Strategy: {names[run.strategy_id] ?? run.strategy_id}</p>
      <p><time dateTime={run.start_time}>{date(run.start_time)}</time> · <span className="badge">{run.status}</span> · {run.bet_count} Bets</p>
    </article></li>)}</ul>}
  </main>
}
export function RunDetail({ id }: { id: string }) {
  const [data, setData] = useState<{ run: Run; bets: Bet[] } | null>(null), [error, setError] = useState<string | null>(null), [attempt, setAttempt] = useState(0)
  const names = useStrategyNames()
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null)
    if (!isUuid(id)) { setError('Invalid Run ID. Open a Run from history.'); return () => controller.abort() }
    Promise.all([getRun(id, controller.signal), getRunBets(id, controller.signal)]).then(([run, bets]) => { if (!controller.signal.aborted) setData({ run, bets }) }).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof RunApiError && failure.status === 404 ? 'Run not found.' : failure instanceof Error ? failure.message : 'Run could not be loaded.')
    })
    return () => controller.abort()
  }, [id, attempt])
  const run = data?.run
  return <main><header className="page-header"><p className="brand">AutoPredict / Saved simulation</p><h1>{run?.name ?? 'Run detail'}</h1><p className="intro">Persisted theoretical Bets and saved prices.</p><a href="#/runs">All Runs</a></header>
    {error ? <ErrorPanel message={error} retry={() => setAttempt(n => n + 1)} /> : !data || !run ? <p className="state-panel" role="status">Loading Run…</p> : <>
      <section className="state-panel" aria-label="Run summary">
        <h2>Run summary <span className="badge">{run.status}</span></h2>
        <p>Run ID: <a href={`#/runs/${run.id}`}>{run.id}</a></p><p>Strategy: {names[run.strategy_id] ?? run.strategy_id}</p>
        <p>Started <time dateTime={run.start_time}>{date(run.start_time)}</time></p>
        <dl className="metrics"><div><dt>Starting bankroll</dt><dd>{run.starting_bankroll}</dd></div><div><dt>Stake per Bet</dt><dd>{run.stake_per_bet}</dd></div><div><dt>Committed stake</dt><dd>{run.committed_stake}</dd></div><div><dt>Available bankroll</dt><dd>{run.available_bankroll}</dd></div><div><dt>Open Bets</dt><dd>{data.bets.filter(b => b.status === 'open').length}</dd></div><div><dt>Final bankroll</dt><dd>{run.final_bankroll ?? 'Not settled'}</dd></div><div><dt>Total profit</dt><dd>{run.total_profit ?? 'Not settled'}</dd></div><div><dt>ROI</dt><dd>{run.roi ?? 'Not settled'}</dd></div></dl>
        <p>Available bankroll excludes open committed stakes. Results remain unsettled.</p>{run.notes && <p>{run.notes}</p>}
      </section>
      <section className="state-panel" aria-label="Requested games"><h2>Requested games</h2><ol>{run.game_ids.map(gameId => {
        const bet = data.bets.find(b => b.game_id === gameId), skip = run.skipped_games.find(s => s.game_id === gameId)
        return <li key={gameId}>{bet ? `${bet.away_team} at ${bet.home_team}` : gameId}{skip && ` — ${skipLabels[skip.reason]}`}</li>
      })}</ol></section>
      <section className="state-panel" aria-label="Saved Bets"><h2>Saved Bets</h2><p>Execution snapshots are retained when current games or quotes change.</p>
        {!data.bets.length ? <p>No Bets recorded.</p> : <ul className="bet-list">{data.bets.map(bet => <li key={bet.id}><article>
          <h3>{bet.away_team} at {bet.home_team}</h3><p><strong>{bet.side} {formatLine(bet.line)}</strong> · Decimal odds <strong>{bet.price}</strong> · Stake <strong>{bet.stake}</strong></p>
          <p><span className="badge">{bet.status}</span> · Result: {bet.result ?? 'Not settled'} · Profit: {bet.profit ?? 'Not settled'}</p>
          <p>Placed <time dateTime={bet.placed_at}>{date(bet.placed_at)}</time> · Saved kickoff <time dateTime={bet.kickoff_at_placement}>{date(bet.kickoff_at_placement)}</time></p>
          {bet.quote_provenance ? <p>Saved price from {bet.quote_provenance.bookmaker} · Fetched {date(bet.quote_provenance.fetched_at)}{bet.quote_provenance.source_timestamp && ` · Source ${date(bet.quote_provenance.source_timestamp)}`} · Observation {bet.quote_provenance.observation_id}</p> : <p className="demo-note">Demo data · Fictional saved odds.</p>}
          <p className="record-id">Bet ID: {bet.id}</p>
        </article></li>)}</ul>}
      </section>
    </>}
  </main>
}
