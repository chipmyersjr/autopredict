import { useEffect, useRef, useState } from 'react'
import { getRun, getRunBets, getRuns, isUuid, RunApiError, settleRun } from '../api/runs'
import type { Bet, Run } from '../api/runs'
import { getStrategies } from '../api/strategies'
import { formatLine } from './GamesPage'
import { formatRatio } from '../format'

const date = (value: string) => new Date(value).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
const accountingState = (run: Run) => run.status === 'completed' ? 'Completed' : run.total_profit === null ? 'Pending results' : 'Partially settled'
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
      <p>{accountingState(run)} · Realized profit: {run.total_profit ?? 'Not settled'} · ROI: {formatRatio(run.roi)}</p>
      <p>Open Bets: {run.open_bet_count} · Settled Bets: {run.settled_bet_count} · Wins: {run.win_count} · Losses: {run.loss_count} · Pushes: {run.push_count} · Voids: {run.void_count}</p>
      {run.status === 'completed' && <p>Final bankroll: {run.final_bankroll}{run.end_time && <> · Ended <time dateTime={run.end_time}>{date(run.end_time)}</time></>}</p>}
    </article></li>)}</ul>}
  </main>
}
export function RunDetail({ id }: { id: string }) {
  const [data, setData] = useState<{ run: Run; bets: Bet[] } | null>(null), [error, setError] = useState<string | null>(null), [attempt, setAttempt] = useState(0)
  const names = useStrategyNames()
  const submission = useRef<AbortController | null>(null)
  const feedback = useRef<HTMLDivElement>(null)
  const [settling, setSettling] = useState(false)
  const [notice, setNotice] = useState('')
  const [settlementError, setSettlementError] = useState('')
  useEffect(() => () => { submission.current?.abort() }, [id, attempt])
  async function settle() {
    if (submission.current || !data || data.run.status === 'completed') return
    const controller = new AbortController()
    submission.current = controller
    setSettling(true); setNotice(''); setSettlementError('')
    try {
      const result = await settleRun(id, controller.signal)
      if (controller.signal.aborted) return
      setData({ run: result.run, bets: result.bets })
      const pending = result.pending_games.map(item => `${result.bets.find(b => b.game_id === item.game_id)?.away_team ?? item.game_id} at ${result.bets.find(b => b.game_id === item.game_id)?.home_team ?? 'saved game'}: ${item.reason === 'final_scores_missing' ? 'Final scores missing' : 'Game not final'}.`).join(' ')
      setNotice(`${result.settled_bet_ids.length ? `${result.settled_bet_ids.length} newly settled Bets.` : 'No new Bets settled.'} ${pending}`)
    } catch (failure) {
      if (!controller.signal.aborted) setSettlementError(failure instanceof Error ? failure.message : 'Settlement may have been saved. Retry safely or reload saved Run detail.')
    } finally {
      if (!controller.signal.aborted) {
        submission.current = null; setSettling(false)
        feedback.current?.focus()
      }
    }
  }
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
        <p>{accountingState(run)}</p>
        <dl className="metrics">{[
          ['Starting bankroll', run.starting_bankroll], ['Stake per Bet', run.stake_per_bet],
          ['Open committed stake', run.committed_stake], ['Available bankroll', run.available_bankroll],
          ['Current bankroll', run.current_bankroll], ['Settled stake', run.settled_stake],
          ['Open Bets', run.open_bet_count], ['Settled Bets', run.settled_bet_count],
          ['Wins', run.win_count], ['Losses', run.loss_count], ['Pushes', run.push_count], ['Voids', run.void_count],
          ['Realized profit', run.total_profit ?? 'Not settled'], ['Realized ROI', formatRatio(run.roi)],
          ...(run.status === 'completed' ? [['Final bankroll', run.final_bankroll]] : []),
        ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        {run.status === 'completed' && run.end_time && <p>Ended <time dateTime={run.end_time}>{date(run.end_time)}</time></p>}
        <p>Available bankroll excludes open committed stakes. Settlement uses saved game results and does not refresh providers.</p>{run.notes && <p>{run.notes}</p>}
        <button onClick={settle} disabled={settling || run.status === 'completed'}>{settling ? 'Settling…' : settlementError ? 'Retry settlement safely' : 'Settle completed games'}</button>{' '}
        <button className="secondary" disabled={settling} onClick={() => { setNotice(''); setSettlementError(''); setAttempt(n => n + 1) }}>Reload saved Run detail</button>
        <div ref={feedback} tabIndex={-1} aria-label="Settlement feedback">
          <p role="status" aria-live="polite">{settling ? 'Settling saved results…' : notice}</p>
          {settlementError && <p className="request-error" role="alert">{settlementError}</p>}
        </div>
      </section>
      <section className="state-panel" aria-label="Requested games"><h2>Requested games</h2><ol>{run.game_ids.map(gameId => {
        const bet = data.bets.find(b => b.game_id === gameId), skip = run.skipped_games.find(s => s.game_id === gameId)
        return <li key={gameId}>{bet ? `${bet.away_team} at ${bet.home_team}` : gameId}{skip && ` — ${skipLabels[skip.reason]}`}</li>
      })}</ol></section>
      <section className="state-panel" aria-label="Saved Bets"><h2>Saved Bets</h2><p>Execution snapshots are retained when current games or quotes change.</p>
        {!data.bets.length ? <p>No Bets recorded.</p> : <ul className="bet-list">{data.bets.map(bet => <li key={bet.id}><article>
          <h3>{bet.away_team} at {bet.home_team}</h3><p><strong>{bet.side} {formatLine(bet.line)}</strong> · Decimal odds <strong>{bet.price}</strong> · Stake <strong>{bet.stake}</strong></p>
          <p><span className="badge">{bet.status}</span> · Result: {bet.result ?? 'Not settled'} · Profit: {bet.profit ?? 'Not settled'}</p>
          {bet.result === 'pushed' && <p>Push · Stake returned · Zero profit</p>}
          {bet.result === 'void' && <p>Canceled · Void · Stake returned · Zero profit</p>}
          {bet.settled_at && <p>Settled <time dateTime={bet.settled_at}>{date(bet.settled_at)}</time> · Saved result: {bet.settlement_game_status} · {bet.away_team} {bet.settlement_away_score ?? '—'} at {bet.home_team} {bet.settlement_home_score ?? '—'}</p>}
          <p>Placed <time dateTime={bet.placed_at}>{date(bet.placed_at)}</time> · Saved kickoff <time dateTime={bet.kickoff_at_placement}>{date(bet.kickoff_at_placement)}</time></p>
          {bet.quote_provenance ? <p>Saved price from {bet.quote_provenance.bookmaker} · Fetched {date(bet.quote_provenance.fetched_at)}{bet.quote_provenance.source_timestamp && ` · Source ${date(bet.quote_provenance.source_timestamp)}`} · Observation {bet.quote_provenance.observation_id}</p> : <p className="demo-note">Demo data · Fictional saved odds.</p>}
          <p className="record-id">Bet ID: {bet.id}</p>
        </article></li>)}</ul>}
      </section>
    </>}
  </main>
}
