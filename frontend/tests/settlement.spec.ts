import { test, expect } from '@playwright/test'

const id = '60000000-0000-4000-8000-000000000001'
const nextId = '60000000-0000-4000-8000-000000000002'
const time = '2026-10-02T18:00:00Z'
const run = {
  id, user_id: 'user', strategy_id: 'strategy', name: 'Mixed oracle', notes: null,
  status: 'open', execution_status: 'completed', starting_bankroll: '100.00', stake_per_bet: '10.00',
  start_time: time, end_time: null, final_bankroll: null, total_profit: null, roi: null,
  created_at: time, updated_at: time, game_ids: ['win', 'loss', 'push', 'pending'],
  bet_count: 4, committed_stake: '40.00', available_bankroll: '60.00', current_bankroll: '100.00',
  settled_stake: '0.00', open_bet_count: 4, settled_bet_count: 0,
  win_count: 0, loss_count: 0, push_count: 0, void_count: 0, skipped_games: [],
}
const bets = run.game_ids.map(game_id => ({
  id: game_id, run_id: id, game_id, selection_id: 'saved', market_id: 'saved',
  home_team: `Home ${game_id}`, away_team: `Away ${game_id}`, side: `Home ${game_id}`,
  line: '0.00', price: '1.9500', stake: '10.00', status: 'open', result: null, profit: null,
  placed_at: time, settled_at: null, kickoff_at_placement: time, created_at: time, updated_at: time,
  settlement_home_score: null, settlement_away_score: null, settlement_game_status: null,
  quote_provenance: { bookmaker: 'Saved Book', fetched_at: time, source_timestamp: time, observation_id: 'saved-observation' },
}))
const partial = { ...run, total_profit: '-0.50', roi: '-0.0050', committed_stake: '10.00',
  available_bankroll: '89.50', current_bankroll: '99.50', settled_stake: '30.00',
  open_bet_count: 1, settled_bet_count: 3, win_count: 1, loss_count: 1, push_count: 1 }
const resolved = bets.map((bet, i) => i === 3 ? bet : { ...bet,
  status: ['won', 'lost', 'pushed'][i], result: ['won', 'lost', 'pushed'][i],
  profit: ['9.50', '-10.00', '0.00'][i], settled_at: time,
  settlement_game_status: 'completed', settlement_home_score: [21, 7, 7][i], settlement_away_score: [7, 21, 7][i],
})
const final = { ...partial, status: 'completed', final_bankroll: '99.50', end_time: time,
  committed_stake: '0.00', available_bankroll: '99.50', settled_stake: '40.00',
  open_bet_count: 0, settled_bet_count: 4, void_count: 1 }
const finalBets = resolved.map((bet, i) => i !== 3 ? bet : { ...bet, status: 'void', result: 'void', profit: '0.00', settled_at: time, settlement_game_status: 'canceled' })

test.beforeEach(async ({ page }) => {
  await page.route('**/api/runs/*/execution', r => r.fulfill({ json: {
    run_id: r.request().url().split('/').at(-2), status: 'completed', total_games: 4,
    completed_games: 4, predicted_games: 4, skipped_games: 0, retrying_games: 0, queued_games: 0,
    games: run.game_ids.map(game_id => ({ game_id, state: 'bet_created', attempts: 1, skip_reason: null })), message: null,
  } }))
})

for (const width of [375, 1280]) test(`mixed settlement oracle, no-op and persisted history at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  let saved: object = run, savedBets: object[] = bets, calls = 0
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route('**/api/runs', r => r.fulfill({ json: [saved] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: saved }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: savedBets }))
  await page.route(`**/api/runs/${id}/settle`, async r => {
    calls++
    expect(r.request().method()).toBe('POST'); expect(r.request().postData()).toBeNull()
    expect(r.request().headers()['idempotency-key']).toBeUndefined()
    if (calls === 1) { saved = partial; savedBets = resolved }
    if (calls === 3) { saved = final; savedBets = finalBets }
    await new Promise(resolve => setTimeout(resolve, 100))
    await r.fulfill({ json: { run: saved, bets: savedBets, settled_bet_ids: calls === 1 ? ['win','loss','push'] : calls === 3 ? ['pending'] : [], pending_games: calls < 3 ? [{ game_id: 'pending', reason: calls === 1 ? 'final_scores_missing' : 'game_not_final' }] : [] } })
  })
  await page.goto(`/#/runs/${id}`)
  const summary = page.getByRole('region', { name: 'Run summary' })
  const savedRegion = page.getByRole('region', { name: 'Saved Bets', exact: true })
  await expect(summary).toContainText('Pending results')
  const settle = page.getByRole('button', { name: 'Settle completed games', exact: true })
  await expect(settle).toBeEnabled()
  await settle.focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Settling…' })).toBeDisabled()
  await expect(page.getByRole('status')).toContainText('3 newly settled Bets.')
  await expect(page.getByRole('status')).toContainText('Final scores missing')
  await expect(page.getByLabel('Settlement feedback')).toBeFocused()
  for (const value of ['Partially settled', '-0.50', '-0.5%', '89.50', '99.50']) await expect(summary).toContainText(value)
  await expect(summary.getByText('Final bankroll', { exact: true })).toHaveCount(0)
  for (const value of ['won', 'lost', 'pushed', 'Profit: 0.00', 'Stake returned', 'Saved result: completed', '1.9500', 'Saved Book', 'Pick’em']) await expect(savedRegion).toContainText(value)
  await settle.click(); await expect(page.getByRole('status')).toContainText('No new Bets settled.')
  await expect(page.getByRole('status')).toContainText('Game not final')
  await expect(summary).toContainText('89.50')
  await settle.click(); await expect(summary).toContainText('Completed')
  await expect(settle).toBeDisabled(); await expect(summary).toContainText('Final bankroll99.50')
  await expect(savedRegion).toContainText('Canceled · Void · Stake returned')
  await page.reload(); await expect(summary).toContainText('Final bankroll99.50')
  await expect(savedRegion).toContainText('Saved Book'); expect(calls).toBe(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/settlement-${width}.png`, fullPage: true })
  await page.getByRole('link', { name: 'All Runs' }).click()
  await expect(page.getByRole('main')).toContainText('Realized profit: -0.50 · ROI: -0.5%')
  await expect(page.getByRole('main')).toContainText('Final bankroll: 99.50')
})

for (const status of [0, 404, 409, 422, 503, 500]) test(`settlement failure ${status} allows safe retry and reload`, async ({ page }) => {
  let calls = 0
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: calls ? final : run }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: calls ? finalBets : bets }))
  await page.route(`**/api/runs/${id}/settle`, r => {
    calls++
    if (calls > 1) return r.fulfill({ json: { run: final, bets: finalBets, settled_bet_ids: [], pending_games: [] } })
    return status ? r.fulfill({ status, json: { detail: 'private exception' } }) : r.abort('failed')
  })
  await page.goto(`/#/runs/${id}`)
  await page.getByRole('button', { name: 'Settle completed games' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('alert')).not.toContainText('private exception')
  if (!status || status === 500) await expect(page.getByRole('alert')).toContainText('may have been saved')
  await page.getByRole('button', { name: 'Retry settlement safely' }).click()
  await expect(page.getByRole('status')).toContainText('No new Bets settled.')
  await page.getByRole('button', { name: 'Reload saved Run detail' }).click()
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Final bankroll99.50')
  expect(calls).toBe(2)
})

test('in-flight duplicate actions and late responses cannot corrupt another Run', async ({ page }) => {
  let calls = 0, release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  for (const runId of [id, nextId]) {
    await page.route(`**/api/runs/${runId}`, r => r.fulfill({ json: { ...run, id: runId, name: runId === id ? 'First' : 'Second' } }))
    await page.route(`**/api/runs/${runId}/bets`, r => r.fulfill({ json: bets }))
  }
  await page.route(`**/api/runs/${id}/settle`, async r => { calls++; await gate; await r.fulfill({ json: { run: final, bets: finalBets, settled_bet_ids: [], pending_games: [] } }).catch(() => {}) })
  await page.goto(`/#/runs/${id}`)
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeEnabled()
  await page.getByRole('button', { name: 'Settle completed games' }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect(page.getByRole('button', { name: 'Settling…' })).toBeDisabled()
  await page.evaluate(value => { location.hash = `/runs/${value}` }, nextId)
  await expect(page.getByRole('heading', { name: 'Second', exact: true })).toBeVisible()
  release()
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Pending results')
  await expect(page.getByRole('heading', { name: 'Mixed oracle' })).toHaveCount(0)
  expect(calls).toBe(1)
})

test('settled zero profit and ROI are distinct from pending nulls', async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: { ...partial, total_profit: '0.00', roi: '0.0000' } }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: resolved }))
  await page.goto(`/#/runs/${id}`)
  const summary = page.getByRole('region', { name: 'Run summary' })
  await expect(summary).toContainText('Partially settled')
  await expect(summary).toContainText('Realized profit0.00')
  await expect(summary).toContainText('Realized ROI0%')
  await expect(summary).not.toContainText('Not settled')
})

test('lost response can recover completed saved results by reload without resubmitting', async ({ page }) => {
  let saved = false, calls = 0
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: saved ? final : run }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: saved ? finalBets : bets }))
  await page.route(`**/api/runs/${id}/settle`, r => { saved = true; calls++; return r.abort('failed') })
  await page.goto(`/#/runs/${id}`)
  await page.getByRole('button', { name: 'Settle completed games' }).click()
  await expect(page.getByRole('alert')).toContainText('may have been saved')
  await page.getByRole('button', { name: 'Reload saved Run detail' }).click()
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Final bankroll99.50')
  await expect(page.getByRole('button', { name: 'Settle completed games' })).toBeDisabled()
  expect(calls).toBe(1)
})

test('settlement timeout offers safe recovery and ignores its late response', async ({ page }) => {
  test.setTimeout(25000)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: run }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: bets }))
  await page.route(`**/api/runs/${id}/settle`, async r => { await gate; await r.fulfill({ json: { run: final, bets: finalBets, settled_bet_ids: [], pending_games: [] } }).catch(() => {}) })
  await page.goto(`/#/runs/${id}`)
  await page.getByRole('button', { name: 'Settle completed games' }).click()
  await expect(page.getByRole('alert')).toContainText('may have been saved', { timeout: 18000 })
  await expect(page.getByRole('button', { name: 'Retry settlement safely' })).toBeEnabled()
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Pending results')
  release()
})
