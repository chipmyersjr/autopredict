import { test, expect } from '@playwright/test'
import type { SettlementResult } from '../src/api/runs'
import type { Dashboard } from '../src/api/dashboard'

const time = '2026-10-03T01:02:03+00:00'
const run = {
  id: 'saved-run', user_id: 'user', strategy_id: 'shared', name: null, notes: null,
  status: 'open', execution_status: 'completed' as const, execution_started_at: time, execution_finished_at: time,
  starting_bankroll: '100.00', stake_per_bet: '10.00', start_time: time,
  end_time: null, final_bankroll: null, total_profit: '-0.50', roi: '-0.0050',
  created_at: time, updated_at: time, game_ids: ['game'], bet_count: 4,
  committed_stake: '10.00', available_bankroll: '89.50', current_bankroll: '99.50',
  settled_stake: '30.00', open_bet_count: 1, settled_bet_count: 3,
  win_count: 1, loss_count: 1, push_count: 1, void_count: 0, skipped_games: [],
}
const bet = {
  id: 'bet', run_id: run.id, game_id: 'game', market_id: 'market', selection_id: 'selection',
  side: 'Saved home', reasoning: null, line: '-3.50', price: '1.9500', home_team: 'Saved home', away_team: 'Saved away',
  kickoff_at_placement: time, stake: '10.00', status: 'won', result: 'won', profit: '9.50',
  placed_at: time, settled_at: time, created_at: time, updated_at: time,
  settlement_home_score: 31, settlement_away_score: 24, settlement_game_status: 'completed',
  quote_provenance: { observation_id: 'observation', bookmaker: 'Saved book', source_timestamp: null, fetched_at: time },
}
const settlement: SettlementResult = {
  run, bets: [bet], settled_bet_ids: [bet.id],
  pending_games: [{ game_id: 'pending', reason: 'game_not_final' }, { game_id: 'missing', reason: 'final_scores_missing' }],
}
const dashboard: Dashboard = {
  run_count: 1, active_run_count: 1, completed_run_count: 0,
  starting_bankroll_total: '100.00', current_bankroll_total: '99.50', available_bankroll_total: '89.50',
  committed_stake_total: '10.00', realized_profit: '-0.50', roi: '-0.0050', bet_count: 4,
  open_bet_count: 1, win_count: 1, loss_count: 1, push_count: 1, void_count: 0,
  recent_results: [bet], performance: [{ date: '2026-10-03', profit: '-0.50', cumulative_profit: '-0.50' }],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [] }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.goto('/')
})

test('bodyless settlement preserves decimals, nulls, evidence, pending and no-op responses', async ({ page }) => {
  let calls = 0
  await page.route('**/api/runs/saved%2Frun/settle', r => {
    expect(r.request().method()).toBe('POST')
    expect(r.request().postData()).toBeNull()
    expect(r.request().headers()['idempotency-key']).toBeUndefined()
    expect(r.request().headers()['content-type']).toBeUndefined()
    return r.fulfill({ json: calls++ ? { ...settlement, settled_bet_ids: [] } : settlement })
  })
  const values = await page.evaluate(async () => {
    const path = '/src/api/runs.ts'
    const { settleRun } = await import(path)
    const signal = new AbortController().signal
    return [await settleRun('saved/run', signal), await settleRun('saved/run', signal)]
  })
  expect(values).toEqual([settlement, { ...settlement, settled_bet_ids: [] }])
  expect(calls).toBe(2)
})

test('dashboard GET retains exact aggregate strings, UTC series and saved Bet snapshots', async ({ page }) => {
  await page.route('**/api/dashboard', r => {
    expect(r.request().method()).toBe('GET')
    expect(r.request().postData()).toBeNull()
    return r.fulfill({ json: dashboard })
  })
  expect(await page.evaluate(async () => {
    const path = '/src/api/dashboard.ts'
    return (await import(path)).getDashboard(new AbortController().signal)
  })).toEqual(dashboard)
})

for (const status of [404, 409, 422, 503, 500]) test(`settlement ${status} uses bounded safe errors`, async ({ page }) => {
  await page.route('**/api/runs/saved/settle', r => r.fulfill({ status, json: { detail: 'PRIVATE server traceback' } }))
  const error = await page.evaluate(async () => {
    const path = '/src/api/runs.ts'
    try { await (await import(path)).settleRun('saved', new AbortController().signal) }
    catch (e) { const error = e as Error & { status: number; definite: boolean }; return { message: error.message, status: error.status, definite: error.definite } }
  })
  expect(error?.status).toBe(status)
  expect(error?.definite).toBe(status !== 500)
  expect(error?.message).not.toContain('PRIVATE')
  expect(error?.message).toMatch(status === 500 ? /may have been saved.*Retry.*reload/ : /Run|settlement|simulator/)
})

for (const mode of ['network', 'timeout', 'invalid-json', 'abort'] as const) test(`settlement ${mode} recovery semantics`, async ({ page }) => {
  await page.route('**/api/runs/saved/settle', async r => {
    if (mode === 'network') return r.abort('failed')
    if (mode === 'invalid-json') return r.fulfill({ body: '{' })
    await new Promise(resolve => setTimeout(resolve, 150))
    await r.fulfill({ json: settlement })
  })
  const error = await page.evaluate(async mode => {
    const path = '/src/api/runs.ts'
    const { settleRun } = await import(path)
    const controller = new AbortController()
    const original = AbortSignal.timeout
    if (mode === 'timeout') AbortSignal.timeout = () => original(10)
    if (mode === 'abort') controller.abort()
    try { await settleRun('saved', controller.signal) }
    catch (e) { const error = e as Error & { definite?: boolean }; return { name: error.name, message: error.message, definite: error.definite } }
    finally { AbortSignal.timeout = original }
  }, mode)
  if (mode === 'abort') expect(error?.name).toBe('AbortError')
  else {
    expect(error?.definite).toBe(false)
    expect(error?.message).toContain('Settlement may have been saved')
    expect(error?.message).toContain('Retry settlement safely or reload')
  }
})

test('dashboard failure is safe and retryable', async ({ page }) => {
  await page.route('**/api/dashboard', r => r.fulfill({ status: 503, body: 'PRIVATE proxy error' }))
  expect(await page.evaluate(async () => {
    const path = '/src/api/dashboard.ts'
    try { await (await import(path)).getDashboard(new AbortController().signal) }
    catch (e) { return (e as Error).message }
  })).toBe('The dashboard is unavailable. Check local setup and try again.')
})

test('ROI formatting shifts exact decimal strings without floating point rounding', async ({ page }) => {
  expect(await page.evaluate(async () => {
    const path = '/src/format.ts'
    const { formatRatio } = await import(path)
    return [null, '0.0000', '-0.0000', '-0.0050', '+0.0123', '1.0000', '0.0001',
      '9999999999999999.9999', '-0.123456789', 'invalid'].map(formatRatio)
  })).toEqual(['—', '0%', '0%', '-0.5%', '1.23%', '100%', '0.01%', '999999999999999999.99%', '-12.3456789%', '—'])
})
