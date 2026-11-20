import { useEffect, useRef, useState } from 'react'
import { executionStateLabels, getRun, getRunBets, getRunExecution, getRuns, isUuid, RunApiError, settleRun, skipReasonLabels } from '../api/runs'
import type { Bet, Run, RunExecution } from '../api/runs'
import { getStrategies } from '../api/strategies'
import { formatLine } from './GamesPage'
import { formatRatio } from '../format'
import SavedBetScore from '../components/SavedBetScore'

const date = (value: string) => new Date(value).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
const pacificKickoff = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/Los_Angeles', weekday: 'short', month: 'short', day: 'numeric',
  year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
})
const savedSide = (bet: Bet) => bet.side === 'home' ? bet.home_team : bet.side === 'away' ? bet.away_team : bet.side
const accountingState = (run: Run) => run.execution_status === 'queued' || run.execution_status === 'running' ? 'Processing predictions' : run.execution_status === 'failed' ? 'Prediction execution failed' : run.status === 'completed' ? 'Completed' : run.total_profit === null ? 'Pending results' : 'Partially settled'
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
      <p>Execution: {run.execution_status}</p>
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
  const [execution, setExecution] = useState<RunExecution | null>(null)
  const [progressError, setProgressError] = useState('')
  const [progressAttempt, setProgressAttempt] = useState(0)
  const [outcomesReady, setOutcomesReady] = useState(false)
  const terminalLoaded = useRef(false)
  const initialReadFailed = useRef(false)
  useEffect(() => () => { submission.current?.abort() }, [id, attempt])
  async function settle() {
    if (submission.current || !outcomesReady || !data || data.run.status === 'completed' || data.run.execution_status !== 'completed' || execution?.status !== 'completed') return
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
    const controller = new AbortController(); setData(null); setError(null); setExecution(null); setProgressError(''); setOutcomesReady(false)
    terminalLoaded.current = false
    initialReadFailed.current = false
    if (!isUuid(id)) { setError('Invalid Run ID. Open a Run from history.'); return () => controller.abort() }
    // Let effect cleanup run before dispatching reads during StrictMode replay.
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted) return
      try {
        const [run, bets] = await Promise.all([getRun(id, controller.signal), getRunBets(id, controller.signal)])
        if (!controller.signal.aborted) setData(previous => previous ?? { run, bets })
      } catch (failure) {
        if (!controller.signal.aborted && !terminalLoaded.current) {
          initialReadFailed.current = true
          setError(failure instanceof RunApiError && failure.status === 404 ? 'Run not found.' : failure instanceof Error ? failure.message : 'Run could not be loaded.')
        }
      }
    })
    return () => controller.abort()
  }, [id, attempt])
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setProgressError('')
    if (!isUuid(id)) return () => controller.abort()
    async function poll() {
      try {
        const snapshot = await getRunExecution(id, controller.signal)
        if (controller.signal.aborted) return
        setExecution(snapshot); setProgressError('')
        if (snapshot.status === 'queued' || snapshot.status === 'running') {
          timer = setTimeout(poll, 2000)
        } else {
          // Predictions are provisional until final Run/Bets reads establish outcomes.
          if (initialReadFailed.current) return
          const [run, bets] = await Promise.all([getRun(id, controller.signal), getRunBets(id, controller.signal)])
          if (!controller.signal.aborted && !initialReadFailed.current) { terminalLoaded.current = true; setData({ run, bets }); setError(null); setOutcomesReady(true) }
        }
      } catch {
        if (!controller.signal.aborted) setProgressError('Saved progress or final outcomes could not be refreshed. The Run may still be processing. Retry to read saved state.')
      }
    }
    void Promise.resolve().then(() => { if (!controller.signal.aborted) return poll() })
    return () => { controller.abort(); clearTimeout(timer) }
  }, [id, attempt, progressAttempt])
  const run = data?.run
  return <main><header className="page-header"><p className="brand">AutoPredict / Saved simulation</p><h1>{run?.name ?? 'Run detail'}</h1><p className="intro">Persisted theoretical Bets and saved prices.</p><a href="#/runs">All Runs</a></header>
    {error ? <ErrorPanel message={error} retry={() => setAttempt(n => n + 1)} /> : !data || !run ? <p className="state-panel" role="status">Loading Run…</p> : <>
      <section className="state-panel" aria-label="Execution progress">
        <h2>Execution progress</h2>
        {execution ? <>
          <p aria-live="polite">{execution.status === 'queued' || execution.status === 'running' ? 'Processing predictions' : execution.status === 'failed' ? 'Prediction execution failed' : 'Predictions completed'} · {execution.completed_games} / {execution.total_games} games completed</p>
          <p>Queued: {execution.queued_games} · Predicted: {execution.predicted_games} · Retrying: {execution.retrying_games} · Skipped: {execution.skipped_games}</p>
          <p>Predicted games are provisional until Bets are saved. Leaving this page does not cancel execution.</p>
          <ol>{execution.games.map(game => {
            const bet = data.bets.find(item => item.game_id === game.game_id)
            return <li key={game.game_id}>{bet ? `${bet.away_team} at ${bet.home_team}` : game.game_id} — {executionStateLabels[game.state]} · Attempts: {game.attempts}{game.skip_reason && ` · ${skipReasonLabels[game.skip_reason]}`}</li>
          })}</ol>
          {(execution.status === 'completed' || execution.status === 'failed') && <p>{outcomesReady ? `${data.bets.length} saved Bets.` : 'Loading final saved outcomes…'}{execution.status === 'failed' && ' No Bets could be created. See per-game skip reasons; this is not a financial loss.'}</p>}
        </> : <p>Loading saved execution progress…</p>}
        {progressError && <div role="alert"><p>{progressError} Last known progress is retained.</p><button onClick={() => setProgressAttempt(n => n + 1)}>Retry progress</button></div>}
      </section>
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
        <button onClick={settle} disabled={settling || !outcomesReady || run.status === 'completed' || run.execution_status !== 'completed' || execution?.status !== 'completed'}>{settling ? 'Settling…' : settlementError ? 'Retry settlement safely' : 'Settle completed games'}</button>{' '}
        <button className="secondary" disabled={settling} onClick={() => { setNotice(''); setSettlementError(''); setAttempt(n => n + 1) }}>Reload saved Run detail</button>
        <div ref={feedback} tabIndex={-1} aria-label="Settlement feedback">
          <p role="status" aria-live="polite">{settling ? 'Settling saved results…' : notice}</p>
          {settlementError && <p className="request-error" role="alert">{settlementError}</p>}
        </div>
      </section>
      <section className="state-panel" aria-label="Requested games"><h2>Requested games</h2><ol>{run.game_ids.map(gameId => {
        const bet = data.bets.find(b => b.game_id === gameId), skip = run.skipped_games.find(s => s.game_id === gameId)
        return <li key={gameId}>{bet ? `${bet.away_team} at ${bet.home_team}` : gameId}{skip && ` — ${skipReasonLabels[skip.reason]}`}</li>
      })}</ol></section>
      <section className="state-panel" aria-label="Saved Bets"><h2>Saved Bets</h2><p>Execution snapshots are retained when current games or quotes change.</p>
        {!data.bets.length ? <p>No Bets recorded.</p> : <ul className="bet-list">{data.bets.map(bet => <li key={bet.id}><article>
          <h3>{bet.away_team} at {bet.home_team}</h3><p><strong>{savedSide(bet)} {formatLine(bet.line)}</strong> · Decimal odds <strong>{bet.price}</strong> · Stake <strong>{bet.stake}</strong></p>
          {bet.reasoning?.trim() && <details className="bet-reasoning">
            <summary>Agent reasoning for {bet.away_team} at {bet.home_team}</summary>
            <p>{Array.from(bet.reasoning).slice(0, 1000).join('')}</p>
          </details>}
          <p>Saved kickoff (Pacific): <time dateTime={bet.kickoff_at_placement}>{pacificKickoff(bet.kickoff_at_placement)}</time></p>
          <SavedBetScore bet={bet} />
          <p><span className="badge">{bet.status}</span> · Result: {bet.result ?? 'Not settled'} · Profit: {bet.profit ?? 'Not settled'}</p>
          {bet.result === 'pushed' && <p>Push · Stake returned · Zero profit</p>}
          {bet.result === 'void' && <p>Canceled · Void · Stake returned · Zero profit</p>}
          {bet.settled_at && <p>Settled <time dateTime={bet.settled_at}>{date(bet.settled_at)}</time> · Saved result: {bet.settlement_game_status} · {bet.away_team} {bet.settlement_away_score ?? '—'} at {bet.home_team} {bet.settlement_home_score ?? '—'}</p>}
          <p>Placed <time dateTime={bet.placed_at}>{date(bet.placed_at)}</time></p>
          {bet.quote_provenance ? <p>Saved price from {bet.quote_provenance.bookmaker} · Fetched {date(bet.quote_provenance.fetched_at)}{bet.quote_provenance.source_timestamp && ` · Source ${date(bet.quote_provenance.source_timestamp)}`} · Observation {bet.quote_provenance.observation_id}</p> : <p className="demo-note">Demo data · Fictional saved odds.</p>}
          <p className="record-id">Bet ID: {bet.id}</p>
        </article></li>)}</ul>}
      </section>
    </>}
  </main>
}
