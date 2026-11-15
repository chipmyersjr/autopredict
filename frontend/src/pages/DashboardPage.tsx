import { useEffect, useState } from 'react'
import { getDashboard, type Dashboard, type PerformancePoint } from '../api/dashboard'
import { formatLine, formatRatio } from '../format'

function Performance({ points }: { points: PerformancePoint[] }) {
  if (!points.length) return <p>No settled results yet. Performance appears after settlement.</p>
  // Numeric conversion is only for SVG coordinates; all visible amounts are server strings.
  const values = points.map(point => Number(point.cumulative_profit))
  const low = Math.min(0, ...values), high = Math.max(0, ...values)
  const range = high - low || 1
  const x = (index: number) => points.length === 1 ? 300 : 60 + index / (points.length - 1) * 480
  const y = (value: number) => 35 + (high - value) / range * 150
  return <>
    <svg className="profit-chart" viewBox="0 0 600 240" role="img" aria-labelledby="profit-title profit-description">
      <title id="profit-title">Cumulative realized profit</title>
      <desc id="profit-description">UTC settlement dates, earliest to latest. Exact daily and cumulative amounts are in the performance table below. The dashed line marks zero.</desc>
      <line x1="60" x2="540" y1={y(0)} y2={y(0)} stroke="currentColor" strokeDasharray="5 5" />
      <text x="52" y={y(0) + 4} textAnchor="end">0</text>
      <polyline points={values.map((value, index) => `${x(index)},${y(value)}`).join(' ')} fill="none" stroke="#176451" strokeWidth="3" />
      {values.map((value, index) => <circle key={points[index].date} cx={x(index)} cy={y(value)} r="4" fill="#176451" />)}
      <text x="60" y="220">{points[0].date}</text>
      {points.length > 1 && <text x="540" y="220" textAnchor="end">{points[points.length - 1].date}</text>}
    </svg>
    <div className="performance-table" role="region" aria-label="Performance values" tabIndex={0}>
      <table><caption>Realized profit by UTC settlement date</caption><thead><tr><th scope="col">Date (UTC)</th><th scope="col">Daily profit</th><th scope="col">Cumulative profit</th></tr></thead>
        <tbody>{points.map(point => <tr key={point.date}><th scope="row"><time dateTime={point.date}>{point.date}</time></th><td>{point.profit}</td><td>{point.cumulative_profit}</td></tr>)}</tbody>
      </table>
    </div>
  </>
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    getDashboard(controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value)
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Dashboard unavailable. Try again.')
    })
    return () => controller.abort()
  }, [attempt])
  return <main><h1>Dashboard</h1><p className="intro">Saved results across independent theoretical simulations.</p>
    {error ? <section className="state-panel error-panel"><p role="alert">{error}</p><button onClick={() => setAttempt(value => value + 1)}>Retry dashboard</button></section>
      : !data ? <p className="state-panel" role="status">Loading dashboard…</p>
      : <>
        {data.run_count === 0 && <p className="state-panel">No simulations yet. <a href="#/games">Choose games</a> to start a Run.</p>}
        <section className="state-panel" aria-labelledby="totals-title"><h2 id="totals-title">Simulation totals</h2>
          <p>Bankroll totals sum independent simulations. Each Run has its own starting bankroll; these totals do not represent a shared wallet.</p>
          <dl className="metrics">
            {([
              ['Simulations', data.run_count], ['Active Runs', data.active_run_count], ['Completed Runs', data.completed_run_count],
              ['Starting bankroll total', data.starting_bankroll_total], ['Current bankroll total', data.current_bankroll_total],
              ['Available bankroll total', data.available_bankroll_total], ['Committed open stake', data.committed_stake_total],
              ['Realized profit', data.realized_profit], ['Realized ROI', formatRatio(data.roi)],
              ['Bets', data.bet_count], ['Open Bets', data.open_bet_count], ['Wins', data.win_count], ['Losses', data.loss_count], ['Pushes', data.push_count], ['Voids', data.void_count],
            ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl><p>ROI uses total starting bankroll across all Runs. Open Bets have no realized result.</p>
        </section>
        <section className="state-panel" aria-labelledby="performance-title"><h2 id="performance-title">Cumulative realized profit</h2><Performance points={data.performance} /></section>
        <section className="state-panel" aria-labelledby="recent-title"><h2 id="recent-title">Recent results</h2><p>Up to ten most recent settled Bets.</p>
          {!data.recent_results.length ? <p>No settled results yet.</p> : <ol className="bet-list">{data.recent_results.slice(0, 10).map(bet => <li key={bet.id}>
            <a href={`#/runs/${bet.run_id}`}>{bet.away_team} at {bet.home_team} — View saved Run</a>
            <p>{bet.side} {formatLine(bet.line)} · Price {bet.price} · Stake {bet.stake}</p>
            <p>Outcome: {bet.status} · Profit: {bet.profit ?? '—'}</p>
            {bet.settled_at && <p>Settled (UTC): <time dateTime={bet.settled_at}>{bet.settled_at}</time></p>}
          </li>)}</ol>}
        </section>
      </>}
  </main>
}
