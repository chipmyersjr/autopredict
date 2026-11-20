import { test, expect } from '@playwright/test'

const strategy = { id: '40000000-0000-4000-8000-000000000001', name: 'Random Strategy', type: 'random', is_active: true }
const gameId = '10000000-0000-4000-8000-000000000001'
const runId = '60000000-0000-4000-8000-000000000001'
const kickoff = '2099-10-02T19:00:00Z'
const quote = (side: string, line: string | null, id: string) => ({ id, side, line, price: '1.9091', is_active: true })
const pair = [quote('home', '-3.50', 'h'), quote('away', '3.50', 'a')]
const market = { id: 'm', type: 'spread', status: 'active', selections: pair }
const game = { id: gameId, season: 2099, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: kickoff, status: 'scheduled', home_score: null, away_score: null, markets: [market] }

for (const format of ['roles', 'team names']) test(`${format} support team labels and accepted empty-Bet creation`, async ({ page }) => {
  const selections = format === 'roles' ? pair : [quote('USC', '-3.50', 'h'), quote('UCLA', '3.50', 'a')]
  // Exercise imported roles through the complete click -> stored read -> run path.
  // Team-name fixtures continue to cover the existing preloaded-data path.
  let stored = format === 'team names', refreshes = 0
  await page.route('**/api/games?window=current', r => r.fulfill({ json: stored ? [{ ...game, markets: [{ ...market, selections }] }] : [] }))
  await page.route('**/api/games/refresh', r => {
    refreshes++
    expect(r.request().method()).toBe('POST')
    stored = true
    return r.fulfill({ json: {
      success: true, reason: 'refreshed', message: 'Refresh successful. 17 refreshes remaining this week. 2 are reserved until Sunday.',
      remaining_refreshes: 17, reserved_for_sunday: 2, retry_at: null, data_changed: true, run_id: null,
    } })
  })
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
  let previews = 0, creations = 0
  await page.route('**/decisions', r => {
    previews++
    return r.abort()
  })
  const run = { id: runId, name: 'Imported simulation', game_ids: [gameId], skipped_games: [], starting_bankroll: '1000.00', stake_per_bet: '10.00', status: 'open', execution_status: 'queued', execution_started_at: null, execution_finished_at: null, bet_count: 0, committed_stake: '0.00', available_bankroll: '1000.00', start_time: '2099-10-02T18:00:00Z' }
  await page.route('**/api/runs', r => {
    creations++
    expect(r.request().method()).toBe('POST')
    expect(r.request().postDataJSON()).toEqual({ strategy_id: strategy.id, game_ids: [gameId], starting_bankroll: '1000.00', stake_per_bet: '10.00' })
    return r.fulfill({ status: 201, json: { run, bets: [], skipped_games: [] } })
  })
  await page.route(`**/api/runs/${runId}`, r => r.fulfill({ json: run }))
  await page.route(`**/api/runs/${runId}/bets`, r => r.fulfill({ json: [] }))
  await page.goto('/')
  if (format === 'roles') {
    await expect(page.getByText('No games stored for this week.', { exact: false })).toBeVisible()
    expect(refreshes).toBe(0)
    await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Refresh successful. 17 refreshes remaining this week. 2 are reserved until Sunday.')
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    expect(refreshes).toBe(1)
  }
  await expect(page.locator('.selection-team')).toHaveText(['USC', 'UCLA'])
  await page.getByRole('checkbox').check()
  await expect(page.getByRole('button', { name: 'Preview decisions' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(runId))
  expect(previews).toBe(0)
  expect(creations).toBe(1)
})

test('rejects malformed pairs and retains market, status and kickoff guards', async ({ page }) => {
  await page.clock.install({ time: new Date('2099-10-02T18:59:59Z') })
  const invalidPairs = [
    [pair[0], { ...pair[1], side: 'unknown' }],
    [pair[0], { ...pair[1], side: 'home' }],
    [pair[0], { ...pair[1], side: 'UCLA' }],
    [pair[0]],
    [pair[0], { ...pair[1], is_active: false }],
    [...pair, quote('away', '3.50', 'extra')],
    [pair[0], { ...pair[1], line: null }],
    [pair[0], { ...pair[1], line: 'NaN' }],
    [pair[0], { ...pair[1], line: '' }],
    [pair[0], { ...pair[1], line: '4.50' }],
    [pair[0], { ...pair[1], price: '1.00' }],
    [pair[0], { ...pair[1], price: 'Infinity' }],
  ].map(selections => ({ ...game, markets: [{ ...market, selections }] }))
  const games = [
    ...invalidPairs,
    ...['closed', 'inactive'].map(status => ({ ...game, markets: [{ ...market, status }] })),
    { ...game, markets: [{ ...market, type: 'total' }] },
    ...['completed', 'in_progress', 'canceled', 'postponed'].map(status => ({ ...game, status })),
    { ...game, start_time: 'unknown' },
    { ...game, start_time: '2099-10-02T18:59:59Z' },
    { ...game, home_team: game.away_team },
    game,
    { ...game, markets: [{ ...market, selections: [quote('home', '0.00', 'h'), quote('away', '0.00', 'a')] }] },
  ].map((g, i) => ({ ...g, id: `game-${i}` }))
  await page.route('**/api/games?window=current', r => r.fulfill({ json: games }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
  await page.goto('/')
  const boxes = page.getByRole('checkbox')
  await expect(boxes).toHaveCount(games.length)
  for (let i = 0; i < games.length - 2; i++) await expect(boxes.nth(i)).toBeDisabled()
  await expect(boxes.nth(games.length - 2)).toBeEnabled()
  await expect(boxes.last()).toBeEnabled()
  await page.clock.fastForward(1000)
  await expect(boxes.nth(games.length - 2)).toBeDisabled()
  await expect(boxes.last()).toBeDisabled()
})
