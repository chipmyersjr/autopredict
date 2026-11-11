import { test, expect } from '@playwright/test'
const strategy = { id: '40000000-0000-4000-8000-000000000001', name: 'Random Strategy', type: 'random', is_active: true }
const id = '10000000-0000-4000-8000-000000000001', second = '10000000-0000-4000-8000-000000000002', runId = '60000000-0000-4000-8000-000000000001'
const storageKey = 'autopredict.pending-run.v1'
const game = (gameId: string) => ({ id: gameId, season: 2026, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: '2099-10-02T19:00:00Z', status: 'scheduled', home_score: null, away_score: null, markets: [{ id: 'm', type: 'spread', status: 'active', selections: [{ id: 'h', side: 'USC', line: '-3.50', price: '1.9091', is_active: true }, { id: 'a', side: 'UCLA', line: '3.50', price: '1.9091', is_active: true }] }] })
const skips = [{ game_id: second, reason: 'kickoff_reached' }]
const run = { id: runId, user_id: '50000000-0000-4000-8000-000000000001', strategy_id: strategy.id, name: 'Saved simulation', notes: null, status: 'open', starting_bankroll: '1000.00', stake_per_bet: '10.00', start_time: '2026-10-02T18:00:00Z', end_time: null, final_bankroll: null, total_profit: null, roi: null, created_at: '2026-10-02T18:00:00Z', updated_at: '2026-10-02T18:00:00Z', game_ids: [id, second], bet_count: 1, committed_stake: '10.00', available_bankroll: '990.00', skipped_games: skips }
const bet = { id: '70000000-0000-4000-8000-000000000001', run_id: runId, selection_id: 'h', game_id: id, market_id: 'm', home_team: 'USC', away_team: 'UCLA', side: 'USC', line: '0.00', price: '1.9876', stake: '10.00', status: 'open', result: null, profit: null, placed_at: run.start_time, settled_at: null, kickoff_at_placement: '2099-10-02T19:00:00Z', quote_provenance: null, created_at: run.start_time, updated_at: run.start_time }
const result = { run, bets: [bet], skipped_games: skips }
test.beforeEach(async ({ page }) => {
  await page.route('**/api/games', r => r.fulfill({ json: [game(id), game(second)] }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
  await page.route('**/api/runs', r => r.fulfill({ json: r.request().method() === 'POST' ? result : [run] }))
  await page.route(`**/api/runs/${runId}`, r => r.fulfill({ json: run }))
  await page.route(`**/api/runs/${runId}/bets`, r => r.fulfill({ json: [bet] }))
})
test('creation sends IDs and strings once, saves identity first, then renders snapshots and reloads', async ({ page }) => {
  let calls = 0
  await page.route('**/api/runs', async r => {
    if (r.request().method() !== 'POST') return r.fulfill({ json: [run] })
    calls++
    const body = r.request().postDataJSON(), key = r.request().headers()['idempotency-key']
    expect(body).toEqual({ strategy_id: strategy.id, game_ids: [id, second], starting_bankroll: '1000.00', stake_per_bet: '10.00', name: 'My Run' })
    expect(key).toMatch(/^[0-9a-f-]{36}$/)
    expect(await page.evaluate(k => JSON.parse(sessionStorage.getItem(k)!), storageKey)).toEqual({ key, body })
    await new Promise(resolve => setTimeout(resolve, 100))
    return r.fulfill({ status: 201, json: result })
  })
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Create Dry Run', exact: true })).toBeDisabled()
  await page.getByRole('checkbox').nth(0).check(); await page.getByRole('checkbox').nth(1).check()
  await page.getByLabel('Run name (optional)').fill('My Run')
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Creating Dry Run…' })).toBeDisabled()
  await expect(page).toHaveURL(new RegExp(runId))
  await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toContainText('USC Pick’em')
  await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toContainText('1.9876')
  await expect(page.getByRole('region', { name: 'Requested games' })).toContainText('Kickoff reached')
  expect(calls).toBe(1)
  expect(await page.evaluate(k => sessionStorage.getItem(k), storageKey)).toBeNull()
  await page.reload(); await expect(page.getByRole('heading', { name: 'Saved simulation' })).toBeVisible()
  await page.getByRole('link', { name: 'All Runs' }).click()
  await expect(page.getByRole('link', { name: 'Saved simulation' })).toBeVisible()
  await page.goBack(); await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toBeVisible()
  await page.goForward(); await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible()
})
test('invalid money prevents creation, correction preserves exact submitted cents', async ({ page }) => {
  let payload: unknown
  await page.route('**/api/runs', r => { payload = r.request().postDataJSON(); return r.fulfill({ status: 201, json: result }) })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  for (const value of ['0','-1','NaN','10.001','10000000000.00']) {
    await page.getByLabel('Starting bankroll').fill(value)
    await expect(page.getByRole('button', { name: 'Create Dry Run', exact: true })).toBeDisabled()
  }
  await page.getByLabel('Starting bankroll').fill('100.01'); await page.getByLabel('Stake per Bet').fill('0.01')
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(runId))
  expect(payload).toMatchObject({ starting_bankroll: '100.01', stake_per_bet: '0.01' })
})
test('lost response restores pending identity after reload and replays with original body/key', async ({ page }) => {
  const sent: { key: string; body: unknown }[] = []
  await page.route('**/api/runs', r => {
    if (r.request().method() !== 'POST') return r.fulfill({ json: [] })
    sent.push({ key: r.request().headers()['idempotency-key'], body: r.request().postDataJSON() })
    return sent.length === 1 ? r.abort('failed') : r.fulfill({ status: 200, json: result })
  })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('may have succeeded')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Unresolved creation' })).toBeVisible()
  await page.getByRole('button', { name: 'Retry creation' }).click()
  await expect(page).toHaveURL(new RegExp(runId)); expect(sent).toHaveLength(2); expect(sent[0]).toEqual(sent[1])
})
for (const [status, detail, message] of [
  [404, 'secret internals', 'not found'], [409, 'No eligible games', 'No eligible games'],
  [409, 'Strategy inactive', 'inactive'], [409, 'Idempotency-Key already used with different input', 'different settings'],
  [422, 'Insufficient starting bankroll for eligible games', 'Insufficient starting bankroll'],
  [503, 'Local simulation User is not configured; run python -m app.seed_user', 'not configured'],
  [503, 'Database unavailable', 'database is unavailable'],
] as const) test(`${status}: ${detail} allows correction and a new intent`, async ({ page }) => {
  const keys: string[] = []
  await page.route('**/api/runs', r => { keys.push(r.request().headers()['idempotency-key']); return r.fulfill({ status, json: { detail } }) })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(message)
  await expect(page.getByText('secret internals')).toHaveCount(0)
  await page.getByLabel('Starting bankroll').fill('2000.00')
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect.poll(() => keys.length).toBe(2); expect(keys[0]).not.toBe(keys[1])
})
test('explicit discard explains duplicate risk; new creation uses new identity', async ({ page }) => {
  const keys: string[] = []
  await page.route('**/api/runs', r => { keys.push(r.request().headers()['idempotency-key']); return r.abort('failed') })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await page.getByRole('button', { name: 'Discard pending request' }).click()
  await expect(page.getByText('An earlier Run may already exist.', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Run history' })).toBeVisible()
  await page.getByRole('button', { name: 'Discard and edit settings' }).click()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect.poll(() => keys.length).toBe(2); expect(keys[0]).not.toBe(keys[1])
})
test('navigation aborts creation without implying rollback or allowing stale redirects', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/runs', async r => {
    if (r.request().method() !== 'POST') return r.fulfill({ json: [run] })
    await gate; await r.fulfill({ json: result }).catch(() => {})
  })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await page.getByRole('link', { name: 'Runs', exact: true }).click(); release()
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Games', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry creation' })).toBeVisible()
})
test('malformed saved intent is discarded and storage failure prevents sending', async ({ page }) => {
  await page.addInitScript(k => sessionStorage.setItem(k, JSON.stringify({ key: 'invalid', body: {} })), storageKey)
  await page.goto('/'); await expect(page.getByLabel('Starting bankroll')).toBeVisible()
  expect(await page.evaluate(k => sessionStorage.getItem(k), storageKey)).toBeNull()
  await page.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('disabled') } })
  let calls = 0; await page.route('**/api/runs', r => { calls++; return r.fulfill({ json: result }) })
  await page.getByRole('checkbox').first().check(); await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Enable browser session storage'); expect(calls).toBe(0)
})
test('history has empty, error/retry and unknown or malformed route states', async ({ page }) => {
  await page.route('**/api/runs', r => r.fulfill({ status: 503, json: { detail: 'Database unavailable' } }))
  await page.goto('/#/runs'); await expect(page.getByRole('alert')).toContainText('database is unavailable')
  await page.route('**/api/runs', r => r.fulfill({ json: [] }))
  await page.getByRole('button', { name: 'Retry', exact: true }).click(); await expect(page.getByText('No Runs yet')).toBeVisible()
  await page.goto('/#/runs/invalid'); await expect(page.getByRole('alert')).toContainText('Invalid Run ID')
  await page.route(`**/api/runs/${runId}*`, r => r.fulfill({ status: 404, json: { detail: 'Run not found' } }))
  await page.goto(`/#/runs/${runId}`); await expect(page.getByRole('alert')).toContainText('Run not found')
})
for (const width of [375, 1280]) test(`snapshot detail at ${width}px preserves exact values, saved provenance and keyboard links`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await page.route(`**/api/runs/${runId}/bets`, r => r.fulfill({ json: [bet, { ...bet, id: 'other-bet', side: 'UCLA', line: '3.50', quote_provenance: { observation_id: 'saved-observation', bookmaker: 'Saved Book', fetched_at: run.start_time, source_timestamp: run.start_time } }] }))
  await page.goto(`/#/runs/${runId}`)
  const saved = page.getByRole('region', { name: 'Saved Bets', exact: true })
  await expect(saved).toContainText('USC Pick’em'); await expect(saved).toContainText('UCLA +3.5'); await expect(saved).toContainText('1.9876'); await expect(saved).toContainText('Saved Book'); await expect(saved).toContainText('Demo data')
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('990.00')
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Not settled')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/runs-detail-${width}.png`, fullPage: true })
  await page.getByRole('link', { name: 'All Runs' }).focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible()
})

test('timeout retains identity and offers recovery rather than a fresh submission', async ({ page }) => {
  test.setTimeout(25000)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/runs', async r => { await gate; await r.fulfill({ json: result }).catch(() => {}) })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('may have succeeded', { timeout: 18000 })
  await expect(page.getByRole('button', { name: 'Retry creation' })).toBeEnabled()
  expect(await page.evaluate(k => JSON.parse(sessionStorage.getItem(k)!).body.game_ids, storageKey)).toEqual([id])
  release()
})
test('server errors with unknown outcome retain the original intent', async ({ page }) => {
  await page.route('**/api/runs', r => r.fulfill({ status: 500, json: { detail: 'private exception' } }))
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('may have succeeded')
  await expect(page.getByRole('button', { name: 'Retry creation' })).toBeVisible()
  await expect(page.getByText('private exception')).toHaveCount(0)
})
test('stale detail reads cannot overwrite a newer view, and detail error can retry', async ({ page }) => {
  const nextId = '60000000-0000-4000-8000-000000000002'
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route(`**/api/runs/${runId}`, async r => { await gate; await r.fulfill({ json: run }).catch(() => {}) })
  await page.route(`**/api/runs/${nextId}`, r => r.fulfill({ json: { ...run, id: nextId, name: 'Newer Run' } }))
  let fail = true
  await page.route(`**/api/runs/${nextId}/bets`, r => r.fulfill(fail ? { status: 503, json: { detail: 'Database unavailable' } } : { json: [] }))
  await page.goto(`/#/runs/${runId}`); await expect(page.getByRole('status')).toContainText('Loading Run')
  await page.evaluate(id => { location.hash = `/runs/${id}` }, nextId)
  await expect(page.getByRole('alert')).toContainText('database is unavailable')
  fail = false; await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Newer Run' })).toBeVisible()
  release()
  await expect(page.getByRole('region', { name: 'Saved Bets', exact: true })).toContainText('No Bets recorded')
  await expect(page.getByRole('heading', { name: 'Saved simulation' })).toHaveCount(0)
})
test('selection changes during creation preserve the submitted intent and preview remains usable', async ({ page }) => {
  let submitted: unknown, release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/runs', async r => { submitted = r.request().postDataJSON(); await gate; await r.fulfill({ json: result }) })
  await page.route('**/decisions', r => r.fulfill({ json: { strategy_id: strategy.id, generated_at: run.start_time, decisions: [], skipped_games: [{ game_id: second, reason: 'spread_unavailable' }] } }))
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await page.getByRole('checkbox').first().uncheck(); await page.getByRole('checkbox').nth(1).check()
  await page.getByRole('button', { name: 'Preview decisions' }).click()
  await expect(page.getByRole('region', { name: 'Decision preview', exact: true })).toContainText('all selected games were skipped')
  expect(submitted).toMatchObject({ game_ids: [id] })
  expect(await page.evaluate(k => JSON.parse(sessionStorage.getItem(k)!).body.game_ids, storageKey)).toEqual([id])
  release(); await expect(page).toHaveURL(new RegExp(runId))
})
