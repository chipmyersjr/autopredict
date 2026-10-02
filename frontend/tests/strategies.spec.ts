import { test, expect } from '@playwright/test'
const strategy = { id: '40000000-0000-4000-8000-000000000001', name: 'Random Strategy', type: 'random', is_active: true }
const game = (id: string) => ({ id, season: 2026, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: '2099-10-02T19:00:00Z', status: 'scheduled', home_score: null, away_score: null, markets: [{ id: 'm', type: 'spread', status: 'active', selections: [{ id: 'h', side: 'USC', line: '-3.50', price: '1.9091', is_active: true }, { id: 'a', side: 'UCLA', line: '3.50', price: '1.9091', is_active: true }] }] })
test.beforeEach(async ({ page }) => {
  await page.route('**/api/games', r => r.fulfill({ json: [game('one'), game('two'), { ...game('closed'), status: 'completed' }] }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
})
test('selects games, submits once, displays exact decisions and skips, clears old results', async ({ page }) => {
  let calls = 0
  await page.route('**/decisions', async r => {
    calls++; expect(r.request().method()).toBe('POST'); expect(r.request().postDataJSON()).toEqual({ game_ids: ['one', 'two'] })
    await r.fulfill({ json: { strategy_id: strategy.id, generated_at: '2026-10-01T12:00:00Z', requested_game_ids: ['one', 'two'], decisions: [{ game_id: 'one', market_id: 'm', selection_id: 'h', side: 'USC', line: '-3.50', price: '1.9091', quote_provenance: null }], skipped_games: [{ game_id: 'two', reason: 'kickoff_reached' }] } })
  })
  await page.goto('/')
  const boxes = page.getByRole('checkbox')
  await expect(boxes.nth(2)).toBeDisabled()
  const execute = page.getByRole('button', { name: 'Execute Random Strategy' })
  await expect(execute).toBeDisabled()
  await boxes.nth(0).check(); await boxes.nth(1).check(); await execute.click()
  const results = page.getByRole('region', { name: 'Decision preview', exact: true })
  await expect(results).toContainText('USC -3.5'); await expect(results).toContainText('1.9091'); await expect(results).toContainText('Kickoff reached')
  expect(calls).toBe(1)
  await boxes.nth(0).uncheck(); await expect(results).toHaveCount(0)
})
for (const status of [404, 409, 422, 503]) test(`safe ${status} error recovers to all-skipped preview`, async ({ page }) => {
  let fail = true
  await page.route('**/decisions', r => r.fulfill(fail ? { status, json: { detail: 'sensitive internal error' } } : { json: { strategy_id: strategy.id, generated_at: '2026-10-01T12:00:00Z', requested_game_ids: ['one'], decisions: [], skipped_games: [{ game_id: 'one', reason: 'spread_unavailable' }] } }))
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Execute Random Strategy' }).click()
  await expect(page.getByRole('alert')).toBeVisible(); await expect(page.getByText('sensitive internal error')).toHaveCount(0)
  fail = false; await page.getByRole('button', { name: 'Execute Random Strategy' }).click()
  await expect(page.getByText(/all selected games were skipped/)).toBeVisible()
})
test('changing selection aborts a pending request and prevents stale results', async ({ page }) => {
  await page.route('**/decisions', async r => { await new Promise(resolve => setTimeout(resolve, 500)); await r.fulfill({ json: { generated_at: '2026-10-01T12:00:00Z', decisions: [], skipped_games: [] } }).catch(() => {}) })
  await page.goto('/'); await page.getByRole('checkbox').first().check(); await page.getByRole('button', { name: 'Execute Random Strategy' }).click()
  await expect(page.getByRole('button', { name: 'Generating decisions…' })).toBeDisabled()
  await page.getByRole('checkbox').first().uncheck(); await page.waitForTimeout(600)
  await expect(page.getByRole('region', { name: 'Decision preview', exact: true })).toHaveCount(0)
})
for (const kind of ['absent', 'inactive', 'error']) test(`strategy ${kind} prevents execution`, async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill(kind === 'error' ? { status: 503, json: {} } : { json: kind === 'absent' ? [] : [{ ...strategy, is_active: false }] }))
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await expect(page.getByRole('button', { name: 'Execute Random Strategy' })).toBeDisabled()
  await expect(page.getByText(kind === 'error' ? 'Strategies couldn’t be loaded.' : `Random Strategy ${kind === 'absent' ? 'unavailable' : 'inactive'}`, { exact: true })).toBeVisible()
})
test('cutoff, invalid pairs and inactive quotes disable selection', async ({ page }) => {
  await page.route('**/api/games', r => r.fulfill({ json: [
    { ...game('past'), start_time: '2000-01-01T00:00:00Z' },
    { ...game('missing'), markets: [] },
    { ...game('invalid'), markets: [{ ...game('invalid').markets[0], selections: [{ ...game('invalid').markets[0].selections[0], is_active: false }] }] },
  ] }))
  await page.goto('/'); await expect(page.getByRole('checkbox')).toHaveCount(3)
  for (const box of await page.getByRole('checkbox').all()) await expect(box).toBeDisabled()
  await expect(page.getByText('Kickoff reached', { exact: true })).toBeVisible()
})
test('network failure recovers with keyboard execution and preserves zero lines', async ({ page }) => {
  let fail = true
  await page.route('**/decisions', r => fail ? r.abort('failed') : r.fulfill({ json: { generated_at: '2026-10-01T12:00:00Z', decisions: [{ game_id: 'one', side: 'USC', line: '0.00', price: '1.9876', quote_provenance: { bookmaker: 'Saved book', fetched_at: '2026-10-01T00:00:00Z', source_timestamp: null } }], skipped_games: [] } }))
  await page.goto('/'); await page.getByRole('checkbox').first().focus(); await page.keyboard.press('Space')
  const action = page.getByRole('button', { name: 'Execute Random Strategy' })
  await action.focus(); await page.keyboard.press('Enter'); await expect(page.getByRole('alert')).toBeVisible()
  fail = false; await expect(action).toBeEnabled(); await action.focus(); await page.keyboard.press('Enter')
  const results = page.getByRole('region', { name: 'Decision preview', exact: true })
  await expect(results).toContainText('Pick’em'); await expect(results).toContainText('1.9876'); await expect(results).toContainText('Saved book')
})
test('server skip remains authoritative after client cutoff and duplicate submissions are blocked', async ({ page }) => {
  await page.clock.install({ time: new Date('2099-10-02T18:59:59Z') })
  let calls = 0
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/decisions', async r => { calls++; await pending; await r.fulfill({ json: { generated_at: '2099-10-02T19:00:00Z', decisions: [], skipped_games: [{ game_id: 'one', reason: 'kickoff_reached' }] } }) })
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await page.clock.fastForward(2000)
  await expect(page.getByRole('checkbox').first()).toBeDisabled()
  await page.getByRole('button', { name: 'Execute Random Strategy' }).click()
  await expect(page.getByRole('button', { name: 'Generating decisions…' })).toBeDisabled()
  release()
  await expect(page.getByRole('region', { name: 'Decision preview', exact: true })).toContainText('Kickoff reached')
  expect(calls).toBe(1)
})
