import { test, expect } from '@playwright/test'

const id = '60000000-0000-4000-8000-000000000001'
const next = '60000000-0000-4000-8000-000000000002'
const run = {
  id, strategy_id: 'strategy', name: 'Durable Run', status: 'open', execution_status: 'running',
  start_time: '2026-10-02T18:00:00Z', starting_bankroll: '100.01', stake_per_bet: '0.01',
  committed_stake: '0.00', available_bankroll: '100.01', current_bankroll: '100.01',
  settled_stake: '0.00', total_profit: null, roi: null, bet_count: 0, open_bet_count: 0,
  settled_bet_count: 0, win_count: 0, loss_count: 0, push_count: 0, void_count: 0,
  game_ids: ['first', 'second'], skipped_games: [],
}
const progress = {
  run_id: id, status: 'queued', total_games: 2, completed_games: 0, predicted_games: 0,
  skipped_games: 0, retrying_games: 0, queued_games: 2, message: null,
  games: ['first', 'second'].map(game_id => ({ game_id, state: 'queued', attempts: 0, skip_reason: null })),
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route('**/api/runs', r => r.fulfill({ json: [run] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: run }))
  await page.route('**/api/runs/*/bets', r => r.fulfill({ json: [] }))
  // Any accidental mutation or cancellation fails this test immediately.
  page.on('request', request => {
    if (request.url().includes('/api/')) expect(request.method()).toBe('GET')
  })
})

for (const width of [375, 1280]) test(`persisted retry, partial outcomes and terminal polling at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  let calls = 0, reads = 0
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: calls < 3 ? [] : [{
    id: 'saved-bet', run_id: id, game_id: 'first', home_team: 'USC', away_team: 'UCLA',
    side: 'home', line: '-3.50', price: '1.9500', stake: '0.01', status: 'open',
    result: null, profit: null, placed_at: run.start_time, kickoff_at_placement: run.start_time,
    settled_at: null, reasoning: null, quote_provenance: null,
  }] }))
  await page.route('**/api/games/first', r => r.fulfill({ status: 503 }))
  await page.route(`**/api/runs/${id}`, r => { reads++; return r.fulfill({ json: { ...run,
    execution_status: calls >= 3 ? 'completed' : 'running', bet_count: calls >= 3 ? 1 : 0,
    committed_stake: calls >= 3 ? '0.01' : '0.00', available_bankroll: calls >= 3 ? '100.00' : '100.01',
    open_bet_count: calls >= 3 ? 1 : 0,
    skipped_games: calls >= 3 ? [{ game_id: 'second', reason: 'research_failed' }] : [],
  } }) })
  await page.route('**/api/runs/*/execution', r => {
    calls++
    return r.fulfill({ json: calls === 1 ? progress : calls === 2 ? {
      ...progress, status: 'running', completed_games: 1, queued_games: 0, predicted_games: 1, retrying_games: 1,
      games: [{ game_id: 'first', state: 'predicted', attempts: 1, skip_reason: null }, { game_id: 'second', state: 'retrying', attempts: 2, skip_reason: null }],
    } : { ...progress, status: 'completed', completed_games: 2, queued_games: 0, predicted_games: 1, skipped_games: 1,
      games: [{ game_id: 'first', state: 'bet_created', attempts: 1, skip_reason: null }, { game_id: 'second', state: 'skipped', attempts: 2, skip_reason: 'research_failed' }],
    } })
  })
  await page.goto(`/#/runs/${id}`)
  const region = page.getByRole('region', { name: 'Execution progress' })
  await expect(region).toContainText('0 / 2 games completed')
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeDisabled()
  await expect(region).toContainText('Retrying: 1')
  await expect(region).toContainText('Attempts: 2')
  await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toContainText('No Bets recorded')
  await expect(region).toContainText('2 / 2 games completed')
  await expect(region).toContainText('Research failed after retry')
  await expect(region).toContainText('1 saved Bets')
  await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toContainText('USC -3.5')
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeEnabled()
  expect(reads).toBe(2)
  await page.waitForTimeout(2200); expect(calls).toBe(3); expect(reads).toBe(2)
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('100.01')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('read failure retains progress; retry recovers failed execution and history/reload reads it', async ({ page }) => {
  let calls = 0
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: { ...run, execution_status: calls > 2 ? 'failed' : 'running' } }))
  await page.route('**/api/runs/*/execution', r => {
    calls++
    if (calls === 2) return r.fulfill({ status: 503, json: { detail: 'PRIVATE traceback' } })
    return r.fulfill({ json: calls === 1 ? progress : { ...progress, status: 'failed', completed_games: 2, queued_games: 0, skipped_games: 2,
      games: progress.games.map(game => ({ ...game, state: 'skipped', attempts: 2, skip_reason: 'agent_unavailable' })),
    } })
  })
  await page.goto(`/#/runs/${id}`)
  const region = page.getByRole('region', { name: 'Execution progress' })
  await expect(region).toContainText('0 / 2 games completed')
  await expect(region.getByRole('alert')).toContainText('may still be processing')
  await expect(region).toContainText('0 / 2 games completed')
  await expect(region).not.toContainText('PRIVATE')
  await page.waitForTimeout(2200); expect(calls).toBe(2)
  await page.getByRole('button', { name: 'Retry progress' }).click()
  await expect(region).toContainText('0 saved Bets')
  await expect(region).toContainText('not a financial loss')
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeDisabled()
  await page.getByRole('link', { name: 'All Runs' }).click()
  await page.getByRole('link', { name: 'Durable Run' }).click()
  await expect(region).toContainText('Prediction execution failed')
  await page.reload(); await expect(region).toContainText('Agent unavailable after retry')
})

test('one in-flight poll; navigating aborts reads and late progress cannot alter another Run', async ({ page }) => {
  let release!: () => void, calls = 0
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route(`**/api/runs/${id}/execution`, async r => {
    calls++; await gate
    await r.fulfill({ json: { ...progress, status: 'failed' } }).catch(() => {})
  })
  await page.route(`**/api/runs/${next}`, r => r.fulfill({ json: { ...run, id: next, name: 'Other Run' } }))
  await page.route(`**/api/runs/${next}/execution`, r => r.fulfill({ json: { ...progress, run_id: next } }))
  await page.goto(`/#/runs/${id}`)
  await expect(page.getByRole('heading', { name: 'Durable Run' })).toBeVisible()
  await page.waitForTimeout(2300); expect(calls).toBe(1)
  await page.evaluate(value => { location.hash = `/runs/${value}` }, next)
  await expect(page.getByRole('heading', { name: 'Other Run' })).toBeVisible()
  release()
  await expect(page.getByRole('region', { name: 'Execution progress' })).toContainText('Processing predictions')
  await expect(page.getByText('Prediction execution failed', { exact: false })).toHaveCount(0)
  await page.getByRole('link', { name: 'All Runs' }).click()
  await page.waitForTimeout(2200); expect(calls).toBe(1)
})

test('terminal outcome read failure can retry the same saved execution without enabling settlement early', async ({ page }) => {
  let calls = 0, reads = 0, fail = true
  await page.route(`**/api/runs/${id}`, r => {
    reads++
    return r.fulfill(reads === 2 && fail ? { status: 503 } : { json: { ...run, execution_status: 'completed' } })
  })
  await page.route(`**/api/runs/${id}/execution`, r => {
    calls++
    return r.fulfill({ json: { ...progress, status: 'completed', completed_games: 2, queued_games: 0, skipped_games: 2,
      games: progress.games.map(game => ({ ...game, state: 'skipped', skip_reason: 'kickoff_reached' })),
    } })
  })
  await page.goto(`/#/runs/${id}`)
  const region = page.getByRole('region', { name: 'Execution progress' })
  await expect(region.getByRole('alert')).toBeVisible()
  await expect(region).toContainText('2 / 2 games completed')
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeDisabled()
  fail = false
  await page.getByRole('button', { name: 'Retry progress' }).click()
  await expect(region).toContainText('0 saved Bets')
  await expect(region.getByRole('alert')).toHaveCount(0)
  await page.waitForTimeout(2200)
  expect(calls).toBe(2); expect(reads).toBe(3)
})

test('a slow initial detail response cannot replace terminal saved outcomes', async ({ page }) => {
  let reads = 0, release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route(`**/api/runs/${id}`, async r => {
    if (++reads === 1) {
      await gate
      return r.fulfill({ json: run }).catch(() => {})
    }
    return r.fulfill({ json: { ...run, name: 'Final persisted Run', execution_status: 'completed' } })
  })
  await page.route(`**/api/runs/${id}/execution`, r => r.fulfill({ json: { ...progress, status: 'completed' } }))
  await page.goto(`/#/runs/${id}`)
  await expect(page.getByRole('heading', { name: 'Final persisted Run' })).toBeVisible()
  release()
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeEnabled()
  await expect(page.getByRole('heading', { name: 'Final persisted Run' })).toBeVisible()
})
