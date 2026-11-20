import { test, expect } from '@playwright/test'
const strategy = { id: '40000000-0000-4000-8000-000000000001', name: 'Random Strategy', type: 'random', is_active: true }
const game = (id: string) => ({ id, season: 2026, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: '2099-10-02T19:00:00Z', status: 'scheduled', home_score: null, away_score: null, markets: [{ id: 'm', type: 'spread', status: 'active', selections: [{ id: 'h', side: 'USC', line: '-3.50', price: '1.9091', is_active: true }, { id: 'a', side: 'UCLA', line: '3.50', price: '1.9091', is_active: true }] }] })
test.beforeEach(async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [game('one'), game('two'), { ...game('closed'), status: 'completed' }] }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
})
test('game selection never requests predictions before final creation', async ({ page }) => {
  const requests: string[] = []
  page.on('request', r => { if (r.method() === 'POST') requests.push(r.url()) })
  await page.goto('/')
  await expect(page.getByRole('checkbox').nth(2)).toBeDisabled()
  await page.getByRole('checkbox').first().focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await page.getByRole('checkbox').nth(1).check()
  await page.getByRole('checkbox').first().uncheck()
  await expect(page.getByRole('button', { name: 'Preview decisions' })).toHaveCount(0)
  expect(requests).toEqual([])
})
for (const kind of ['absent', 'inactive', 'error']) test(`strategy ${kind} prevents execution`, async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill(kind === 'error' ? { status: 503, json: {} } : { json: kind === 'absent' ? [] : [{ ...strategy, is_active: false }] }))
  await page.goto('/'); await page.getByRole('checkbox').first().check()
  await expect(page.getByRole('button', { name: 'Create Dry Run', exact: true })).toBeDisabled()
  await expect(page.getByText(kind === 'error' ? 'Strategies couldn’t be loaded.' : `Random Strategy ${kind === 'absent' ? 'unavailable' : 'inactive'}`, { exact: true })).toBeVisible()
})
test('cutoff, invalid pairs and inactive quotes disable selection', async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [
    { ...game('past'), start_time: '2000-01-01T00:00:00Z' },
    { ...game('missing'), markets: [] },
    { ...game('invalid'), markets: [{ ...game('invalid').markets[0], selections: [{ ...game('invalid').markets[0].selections[0], is_active: false }] }] },
  ] }))
  await page.goto('/'); await expect(page.getByRole('checkbox')).toHaveCount(3)
  for (const box of await page.getByRole('checkbox').all()) await expect(box).toBeDisabled()
  await expect(page.getByText('Kickoff reached', { exact: true })).toBeVisible()
})
