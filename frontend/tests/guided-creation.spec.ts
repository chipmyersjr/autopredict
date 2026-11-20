import { test, expect } from '@playwright/test'
import { finalize } from './support/guided'

const random = { id: '40000000-0000-4000-8000-000000000001', name: 'Random Strategy', type: 'random', description: 'Random eligible spread', is_active: true }
const agent = { ...random, id: '40000000-0000-4000-8000-000000000002', name: 'FootballAnalysisExpert', type: 'agent', description: 'Web research with saved reasoning', config: { profile: 'FootballAnalysisExpert' } }
const game = (id: string, roles = false) => ({
  id, season: 2099, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: '2099-10-02T19:00:00Z',
  status: 'scheduled', home_score: null, away_score: null,
  markets: [{ id: `market-${id}`, type: 'spread', status: 'active', selections: [
    { id: `home-${id}`, side: roles ? 'home' : 'USC', line: '-3.50', price: '1.9876', is_active: true,
      quote_provenance: { observation_id: 'saved', bookmaker: 'Saved Book', fetched_at: '2099-10-02T18:00:00Z', source_timestamp: null } },
    { id: `away-${id}`, side: roles ? 'away' : 'UCLA', line: '3.50', price: '1.9091', is_active: true },
  ] }],
})
const first = '10000000-0000-4000-8000-000000000001', second = '10000000-0000-4000-8000-000000000002'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill({ json: [random, agent] }))
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [game(first, true), game(second), { ...game('closed'), status: 'completed', home_score: 0, away_score: 21 }] }))
})

for (const width of [375, 1280]) for (const strategy of [random, agent]) test(`${strategy.type} guided keyboard flow at ${width}px`, async ({ page }) => {
  const posts: string[] = []
  page.on('request', r => { if (r.method() === 'POST') posts.push(r.url()) })
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/')
  const next = page.getByRole('button', { name: 'Continue to Games' })
  await expect(next).toBeDisabled()
  await expect(page.getByRole('radio', { checked: true })).toHaveCount(0)
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await expect(page.getByRole('checkbox').nth(1)).toBeChecked()
  await expect(page.getByRole('checkbox').last()).toBeDisabled()
  await expect(page.locator('.selection-team').first()).toHaveText('USC')
  await expect(page.getByRole('article').first()).toContainText('Saved Book')
  await expect(page.getByRole('article').first()).toContainText('1.9876')
  await expect(page.getByRole('article').last()).toContainText('Score: UCLA 21 · USC 0')
  const radio = page.getByRole('radio', { name: strategy.name })
  await radio.focus(); await page.keyboard.press('Space')
  await next.focus(); await page.keyboard.press('Enter')
  await page.getByRole('checkbox').nth(1).uncheck()
  await page.getByRole('button', { name: 'Continue to Finalize' }).click()
  const review = page.getByRole('region', { name: 'Finalize Run' })
  await expect(review).toContainText(strategy.name)
  await expect(review).toContainText('1 games selected')
  await page.getByLabel('Run name (optional)').fill('Keep my settings')
  await page.getByLabel('Stake per Bet').fill('0.01')
  await page.getByLabel('Starting bankroll').fill('0.01')
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
  await expect(review).toContainText('Maximum committed stake if every selected game produces a Bet: 0.01')
  await page.getByRole('button', { name: 'Back to Games' }).click()
  await expect(page.getByRole('checkbox').nth(1)).not.toBeChecked()
  await page.getByRole('button', { name: 'Back to Strategy' }).click()
  await expect(radio).toBeChecked()
  await next.click()
  await page.getByRole('button', { name: 'Select All eligible games' }).click()
  await page.getByRole('button', { name: 'Continue to Finalize' }).click()
  await expect(page.getByLabel('Run name (optional)')).toHaveValue('Keep my settings')
  await expect(review).toContainText('Maximum committed stake if every selected game produces a Bet: 0.02')
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  await page.getByLabel('Starting bankroll').fill('9999999999.99')
  await page.getByLabel('Stake per Bet').fill('4999999999.99')
  await expect(review).toContainText('9999999999.98')
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
  await page.getByLabel('Stake per Bet').fill('5000000000.00')
  await expect(review).toContainText('10000000000.00')
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  for (const value of ['0', '-1', 'NaN', '0.001', '10000000000.00']) {
    await page.getByLabel('Stake per Bet').fill(value)
    await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  }
  expect(posts).toEqual([])
  await expect(page.getByRole('button', { name: /preview/i })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('changed eligibility removes only unavailable selections after Refresh', async ({ page }) => {
  let changed = false
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [
    { ...game(first), status: changed ? 'canceled' : 'scheduled' }, game(second),
  ] }))
  await page.route('**/api/games/refresh', r => {
    changed = true
    return r.fulfill({ json: { success: true, reason: 'refreshed', message: 'Refresh successful.', remaining_refreshes: 17, reserved_for_sunday: 2, retry_at: null, data_changed: true, run_id: null } })
  })
  await page.goto('/')
  await finalize(page)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('checkbox').first()).toBeDisabled()
  await expect(page.getByRole('checkbox').first()).not.toBeChecked()
  await expect(page.getByRole('checkbox').nth(1)).toBeChecked()
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Review updated games' }).click()
  await page.getByRole('button', { name: 'Continue to Finalize' }).click()
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
})

test('Refresh preserves deliberate deselection, removes missing games and requires review', async ({ page }) => {
  let stored = [game(first), game(second)]
  await page.route('**/api/games?window=current', r => r.fulfill({ json: stored }))
  await page.route('**/api/games/refresh', r => {
    stored = [game(second), game('new')]
    return r.fulfill({ json: { success: true, reason: 'refreshed', message: 'Refresh successful.', remaining_refreshes: 17, reserved_for_sunday: 2, retry_at: null, data_changed: true, run_id: null } })
  })
  await page.goto('/')
  await page.getByRole('checkbox').nth(1).uncheck()
  await finalize(page)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  await expect(page.getByText('Saved games or odds changed.', { exact: false })).toBeVisible()
  await expect(page.getByRole('checkbox')).toHaveCount(2)
  for (const box of await page.getByRole('checkbox').all()) await expect(box).not.toBeChecked()
  await page.getByRole('button', { name: 'Review updated games' }).click()
  await page.getByRole('checkbox').first().check()
  await page.getByRole('button', { name: 'Continue to Finalize' }).click()
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
})

test('kickoff transition invalidates final review without predictions', async ({ page }) => {
  await page.clock.install({ time: new Date('2099-10-02T18:59:59Z') })
  await page.goto('/')
  await finalize(page)
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
  await page.clock.fastForward(1000)
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeDisabled()
  await expect(page.getByRole('checkbox').first()).not.toBeChecked()
  await expect(page.getByRole('checkbox').first()).toBeDisabled()
})

test('retrying a failed strategy read still requires explicit choice', async ({ page }) => {
  let failed = true
  await page.route('**/api/strategies', r => r.fulfill(failed ? { status: 503 } : { json: [agent] }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Strategies couldn’t be loaded')
  failed = false
  await page.getByRole('button', { name: 'Retry strategies' }).click()
  await expect(page.getByRole('radio')).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Continue to Games' })).toBeDisabled()
  await finalize(page, agent.name)
  await expect(page.getByRole('button', { name: 'Create Run', exact: true })).toBeEnabled()
})

test('double final click sends one durable Agent intent and accepts empty Bets', async ({ page }) => {
  let calls = 0, release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const runId = '60000000-0000-4000-8000-000000000001'
  await page.route('**/api/runs', async r => {
    calls++
    expect(r.request().postDataJSON()).toMatchObject({ strategy_id: agent.id, game_ids: [first, second] })
    const key = r.request().headers()['idempotency-key']
    expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('autopredict.pending-run.v1')!))).toEqual({ key, body: r.request().postDataJSON() })
    await gate
    await r.fulfill({ status: 201, json: { run: { id: runId, execution_status: 'queued' }, bets: [], skipped_games: [] } })
  })
  await page.route(`**/api/runs/${runId}*`, r => r.fulfill({ status: 503 }))
  await page.goto('/')
  await finalize(page, agent.name)
  await page.getByRole('button', { name: 'Create Run', exact: true }).evaluate(el => { (el as HTMLButtonElement).click(); (el as HTMLButtonElement).click() })
  await expect.poll(() => calls).toBe(1)
  await expect(page.getByRole('checkbox').first()).toBeDisabled()
  release()
  await expect(page).toHaveURL(new RegExp(runId))
  expect(calls).toBe(1)
  expect(await page.evaluate(() => sessionStorage.getItem('autopredict.pending-run.v1'))).toBeNull()
})
