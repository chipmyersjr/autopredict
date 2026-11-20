import { test, expect } from '@playwright/test'

const id = '60000000-0000-4000-8000-000000000001'
const time = '2026-10-02T18:00:00Z'
const special = '<img src=x onerror="window.reasoningExecuted=true"> & <script>alert(1)</script>\nSaved evidence.'
const explanations = [special, 'x'.repeat(1000), null, '  \n ', null]
const bets = explanations.map((reasoning, i) => ({
  id: `bet-${i}`, run_id: id, game_id: `game-${i}`, home_team: `Home ${i}`, away_team: `Away ${i}`,
  side: i === 0 ? 'home' : i === 1 ? 'away' : `Home ${i}`, line: '-3.50', price: '1.9500', stake: '10.00',
  status: 'open', result: null, profit: null, reasoning, placed_at: time, settled_at: null,
  kickoff_at_placement: time, settlement_home_score: null, settlement_away_score: null,
  settlement_game_status: null,
  quote_provenance: { bookmaker: 'Original Book', fetched_at: time, source_timestamp: time, observation_id: 'original-quote' },
}))
const run = {
  id, strategy_id: 'agent', name: 'Saved Agent', status: 'open', execution_status: 'completed',
  start_time: time, starting_bankroll: '100.00', stake_per_bet: '10.00', committed_stake: '50.00',
  available_bankroll: '50.00', current_bankroll: '100.00', settled_stake: '0.00', total_profit: null,
  roi: null, bet_count: 5, open_bet_count: 5, settled_bet_count: 0, win_count: 0, loss_count: 0,
  push_count: 0, void_count: 0, game_ids: bets.map(b => b.game_id), skipped_games: [],
}

for (const width of [375, 1280]) test(`saved reasoning is accessible plain text and survives settlement at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  let settled = false, settlementCalls = 0
  const savedRun = () => settled ? { ...run, status: 'completed', total_profit: '47.50', roi: '0.4750',
    committed_stake: '0.00', available_bankroll: '147.50', current_bankroll: '147.50', settled_stake: '50.00',
    open_bet_count: 0, settled_bet_count: 5, win_count: 5, final_bankroll: '147.50', end_time: time } : run
  const savedBets = () => settled ? bets.map(b => ({ ...b, status: 'won', result: 'won', profit: '9.50',
    settled_at: time, settlement_game_status: 'completed', settlement_home_score: 7, settlement_away_score: 0 })) : bets
  await page.route('**/api/strategies', r => r.fulfill({ json: [
    { id: 'agent', name: 'FootballAnalysisExpert', type: 'agent', is_active: true, description: null, created_at: time, updated_at: time, config: { profile: 'FootballAnalysisExpert' } },
    { id: 'random', name: 'Random Strategy', type: 'random', is_active: true, description: null, created_at: time, updated_at: time, config: {} },
  ] }))
  await page.route('**/api/runs', r => r.fulfill({ json: [savedRun(), { ...run, id: '60000000-0000-4000-8000-000000000002', name: 'Saved Random', strategy_id: 'random' }] }))
  await page.route(`**/api/runs/${id}`, r => r.fulfill({ json: savedRun() }))
  await page.route(`**/api/runs/${id}/bets`, r => r.fulfill({ json: savedBets() }))
  await page.route(`**/api/runs/${id}/execution`, r => r.fulfill({ json: {
    run_id: id, status: 'completed', total_games: 5, completed_games: 5, predicted_games: 5,
    skipped_games: 0, queued_games: 0, retrying_games: 0,
    games: bets.map(b => ({ game_id: b.game_id, state: 'bet_created', attempts: 1, skip_reason: null })),
  } }))
  await page.route('**/api/games/*', r => r.fulfill({ status: 503 }))
  await page.route(`**/api/runs/${id}/settle`, r => {
    settled = true; settlementCalls++
    return r.fulfill({ json: { run: savedRun(), bets: savedBets(), settled_bet_ids: bets.map(b => b.id), pending_games: [] } })
  })
  await page.goto(`/#/runs/${id}`)
  const region = page.getByRole('region', { name: 'Saved Bets', exact: true })
  await expect(region.locator('details')).toHaveCount(2)
  const disclosure = region.locator('summary').filter({ hasText: 'Agent reasoning for Away 0 at Home 0' })
  await expect(disclosure).toHaveAccessibleName('Agent reasoning for Away 0 at Home 0')
  await expect(region.getByText(special, { exact: true })).not.toBeVisible()
  await disclosure.focus(); await page.keyboard.press('Enter')
  await expect(region.getByText(special, { exact: true })).toBeVisible()
  await expect(region.locator('details img, details script')).toHaveCount(0)
  expect(await page.evaluate(() => 'reasoningExecuted' in window)).toBe(false)
  await page.keyboard.press('Space')
  await expect(region.getByText(special, { exact: true })).not.toBeVisible()
  await region.locator('summary').nth(1).click()
  await expect(region.getByText('x'.repeat(1000), { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Settle completed games' }).click()
  await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Final bankroll147.50')
  await page.reload()
  await expect(region.locator('details')).toHaveCount(2)
  await region.locator('summary').first().click()
  await expect(region.getByText(special, { exact: true })).toBeVisible()
  for (const value of ['Home 0 -3.5', 'Away 1 -3.5', 'Home 2 -3.5', '1.9500', 'Original Book', 'original-quote', '11:00 AM PDT', 'Away 0 0', 'Home 0 7', 'Profit: 9.50']) {
    await expect(region).toContainText(value)
  }
  expect(settlementCalls).toBe(1)
  await page.getByRole('link', { name: 'All Runs' }).click()
  await expect(page.getByRole('main')).toContainText('Strategy: FootballAnalysisExpert')
  await expect(page.getByRole('main')).toContainText('Strategy: Random Strategy')
  await expect(page.getByRole('main')).toContainText('Realized profit: 47.50 · ROI: 47.5%')
})
