import { test, expect } from '@playwright/test'

const empty = {
  run_count: 0, active_run_count: 0, completed_run_count: 0,
  starting_bankroll_total: '0.00', current_bankroll_total: '0.00',
  available_bankroll_total: '0.00', committed_stake_total: '0.00', realized_profit: '0.00', roi: null,
  bet_count: 0, open_bet_count: 0, win_count: 0, loss_count: 0, push_count: 0, void_count: 0,
  recent_results: [], performance: [],
}
const runId = '60000000-0000-4000-8000-000000000001'
const mixed = {
  ...empty, run_count: 3, active_run_count: 1, completed_run_count: 2,
  starting_bankroll_total: '300.00', current_bankroll_total: '299.50',
  available_bankroll_total: '289.50', committed_stake_total: '10.00', realized_profit: '-0.50', roi: '-0.0017',
  bet_count: 11, open_bet_count: 1, win_count: 3, loss_count: 3, push_count: 2, void_count: 2,
  recent_results: Array.from({ length: 10 }, (_, index) => ({
    id: `bet-${index}`, run_id: runId, home_team: `Home ${index}`, away_team: `Away ${index}`,
    side: `Home ${index}`, line: '0.00', price: '1.9500', stake: '10.00',
    status: ['won', 'lost', 'pushed', 'void'][index % 4], profit: ['9.50', '-10.00', '0.00', '0.00'][index % 4],
    settled_at: '2026-10-03T00:00:00Z',
  })),
  performance: [
    { date: '2026-10-01', profit: '9.50', cumulative_profit: '9.50' },
    { date: '2026-10-02', profit: '-10.00', cumulative_profit: '-0.50' },
    { date: '2026-10-03', profit: '0.00', cumulative_profit: '-0.50' },
  ],
}

test('dashboard loading, bounded error, retry and empty states', async ({ page }) => {
  let calls = 0, release!: () => void
  let retry = false
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/dashboard', async route => {
    expect(route.request().method()).toBe('GET')
    calls++
    // Strict Mode can replay the initial read. Keep every initial request gated
    // so replay cannot bypass the loading/error states under test.
    if (!retry) { await gate; await route.fulfill({ status: 503, json: { detail: 'private exception' } }) }
    else await route.fulfill({ json: empty })
  })
  await page.goto('/#/dashboard')
  await expect(page.getByRole('status')).toHaveText('Loading dashboard…')
  release()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('alert')).not.toContainText('private exception')
  const initialCalls = calls
  retry = true
  await page.getByRole('button', { name: 'Retry dashboard' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toContainText('No simulations yet.')
  await expect(page.getByRole('region', { name: 'Simulation totals' })).toContainText('Realized ROI—')
  await expect(page.getByRole('region', { name: 'Cumulative realized profit' })).toContainText('No settled results yet.')
  await expect(page.getByRole('region', { name: 'Recent results' })).toContainText('No settled results yet.')
  expect(calls).toBe(initialCalls + 1)
})

for (const width of [375, 1280]) test(`multiple simulations, exact results, navigation and chart at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await page.route('**/api/dashboard', route => route.fulfill({ json: mixed }))
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ status: 404, json: {} }))
  await page.route(`**/api/runs/${runId}/bets`, route => route.fulfill({ json: [] }))
  await page.goto('/#/dashboard')
  const totals = page.getByRole('region', { name: 'Simulation totals' })
  for (const text of ['independent simulations', 'Simulations3', 'Active Runs1', 'Completed Runs2', 'Starting bankroll total300.00', 'Current bankroll total299.50', 'Available bankroll total289.50', 'Committed open stake10.00', 'Realized profit-0.50', 'Realized ROI-0.17%', 'Bets11', 'Open Bets1', 'Wins3', 'Losses3', 'Pushes2', 'Voids2']) await expect(totals).toContainText(text)
  await expect(page.getByRole('img', { name: 'Cumulative realized profit' })).toBeVisible()
  const table = page.getByRole('table')
  await expect(table).toHaveAccessibleName('Realized profit by UTC settlement date')
  await expect(table.getByRole('row')).toHaveCount(4)
  await expect(table.getByRole('row').nth(1)).toHaveText('2026-10-019.509.50')
  await expect(table.getByRole('row').nth(2)).toHaveText('2026-10-02-10.00-0.50')
  await expect(table.getByRole('row').nth(3)).toHaveText('2026-10-030.00-0.50')
  await page.getByRole('region', { name: 'Performance values' }).focus()
  await expect(page.getByRole('region', { name: 'Performance values' })).toBeFocused()
  const recent = page.getByRole('region', { name: 'Recent results' })
  await expect(recent.getByRole('listitem')).toHaveCount(10)
  for (const text of ['won', 'lost', 'pushed', 'void', 'Profit: 0.00', 'Pick’em', '1.9500', '2026-10-03T00:00:00Z']) await expect(recent).toContainText(text)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/dashboard-${width}.png`, fullPage: true })
  await recent.getByRole('link').first().click()
  await expect(page).toHaveURL(new RegExp(`#/runs/${runId}$`))
  await page.goBack(); await expect(totals).toBeVisible()
  await page.goForward(); await expect(page).toHaveURL(new RegExp(`#/runs/${runId}$`))
  await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
  await page.reload(); await expect(totals).toContainText('Realized profit-0.50')
  await expect(page.getByRole('link', { name: 'Dashboard', exact: true })).toHaveAttribute('aria-current', 'page')
})

for (const profit of ['0.00', '-10.00', '9.50']) test(`single completed performance point ${profit}`, async ({ page }) => {
  await page.route('**/api/dashboard', route => route.fulfill({ json: {
    ...empty, run_count: 1, completed_run_count: 1, starting_bankroll_total: '100.00',
    realized_profit: profit, roi: profit === '0.00' ? '0.0000' : profit === '-10.00' ? '-0.1000' : '0.0950',
    performance: [{ date: '2026-10-03', profit, cumulative_profit: profit }],
  } }))
  await page.goto('/#/dashboard')
  await expect(page.getByRole('img')).toBeVisible()
  await expect(page.getByRole('table').getByRole('row').nth(1)).toHaveText(`2026-10-03${profit}${profit}`)
  await expect(page.getByRole('region', { name: 'Simulation totals' })).toContainText(`Realized ROI${profit === '0.00' ? '0%' : profit === '-10.00' ? '-10%' : '9.5%'}`)
  expect(await page.locator('svg circle').getAttribute('cx')).toBe('300')
})

test('pending simulation has zero realized profit and ROI but no performance', async ({ page }) => {
  await page.route('**/api/dashboard', route => route.fulfill({ json: {
    ...empty, run_count: 1, active_run_count: 1, starting_bankroll_total: '100.00', current_bankroll_total: '100.00',
    available_bankroll_total: '90.00', committed_stake_total: '10.00', roi: '0.0000', bet_count: 1, open_bet_count: 1,
  } }))
  await page.goto('/#/dashboard')
  await expect(page.getByRole('region', { name: 'Simulation totals' })).toContainText('Realized profit0.00')
  await expect(page.getByRole('region', { name: 'Simulation totals' })).toContainText('Realized ROI0%')
  await expect(page.getByRole('img')).toHaveCount(0)
})
