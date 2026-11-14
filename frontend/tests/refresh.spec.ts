import { test, expect } from '@playwright/test'

const envelope = {
  success: true, reason: 'refreshed', message: 'Refresh successful. 17 refreshes remaining this week. 2 are reserved until Sunday.',
  remaining_refreshes: 17, reserved_for_sunday: 2, retry_at: null, data_changed: true, run_id: null,
}
const completed = {
  id: 'completed', season: 2026, week: 5, home_team: 'USC', away_team: 'UCLA',
  start_time: '2026-10-04T19:00:00Z', status: 'completed', home_score: 0, away_score: 21,
  notes: null, markets: [],
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
})

for (const outcome of [
  { status: 200, body: envelope },
  { status: 200, body: { ...envelope, success: false, reason: 'partial_failure', message: 'Refresh failed to update odds; games/results were updated. Saved odds were kept. 17 refreshes remaining this week.' } },
  { status: 200, body: { ...envelope, reason: 'no_games', message: 'Refresh successful. 17 refreshes remaining this week. No FBS games this week.' }, empty: true },
  ...[429, 409, 503, 422].map(status => ({ status, body: { ...envelope, success: false, data_changed: false, reason: 'configuration_error', message: `Refresh failed: safe backend explanation for ${status}. 17 refreshes remaining this week.` } })),
]) test(`refresh ${outcome.status} ${outcome.body.reason} respects envelope, request guard and dialog focus`, async ({ page }) => {
  let reads = 0, posts = 0, changed = false
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/games?window=current', r => {
    reads++
    return r.fulfill({ json: changed && !('empty' in outcome) ? [completed] : [] })
  })
  await page.route('**/api/games/refresh', async r => {
    posts++
    expect(r.request().method()).toBe('POST')
    expect(r.request().postData()).toBeNull()
    expect(new URL(r.request().url()).search).toBe('')
    await gate
    changed = true
    await r.fulfill({ status: outcome.status, json: outcome.body })
  })
  await page.goto('/')
  await expect(page.getByText('No games stored for this week.', { exact: false })).toBeVisible()
  expect(posts).toBe(0)
  const initialReads = reads
  const refresh = page.getByRole('button', { name: 'Refresh', exact: true })
  // Dispatch two synchronous clicks to exercise the ref guard as well as disabled state.
  await refresh.evaluate(el => { (el as HTMLButtonElement).click(); (el as HTMLButtonElement).click() })
  await expect(page.getByRole('button', { name: 'Refreshing…' })).toBeDisabled()
  await expect.poll(() => posts).toBe(1)
  release()
  const dialog = page.getByRole('dialog', { name: 'Refresh result' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(outcome.body.message)
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(refresh).toBeEnabled()
  await expect(refresh).toBeFocused()
  if (outcome.body.data_changed) {
    await expect.poll(() => reads).toBe(initialReads + 1)
    if (!('empty' in outcome)) {
      await expect(page.locator('.scores')).toHaveText('Score: UCLA 21 · USC 0')
      await expect(page.getByText('Demo data', { exact: true })).toHaveCount(0)
    }
  } else expect(reads).toBe(initialReads)
  expect(posts).toBe(1)
  // Reopening must focus Close again and support explicit dismissal as well.
  await refresh.click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(refresh).toBeFocused()
  expect(posts).toBe(2)
})

for (const failure of ['network', 'json', 'missing', 'malformed']) test(`generic ${failure} error releases request state`, async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [] }))
  let posts = 0
  await page.route('**/api/games/refresh', r => {
    posts++
    if (posts > 1) return r.fulfill({ json: { ...envelope, data_changed: false } })
    if (failure === 'network') return r.abort('failed')
    if (failure === 'json') return r.fulfill({ body: '<html>error</html>' })
    return r.fulfill({ json: failure === 'missing' ? {} : { ...envelope, data_changed: 'yes' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Refresh failed. Unable to refresh games. Please try again.')
  await page.getByRole('button', { name: 'Close' }).click()
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(envelope.message)
  expect(posts).toBe(2)
})

test('changed-data reload failure uses games error without replacing the refresh popup', async ({ page }) => {
  let changed = false
  await page.route('**/api/games?window=current', r => r.fulfill(changed ? { status: 503, json: {} } : { json: [] }))
  await page.route('**/api/games/refresh', r => { changed = true; return r.fulfill({ json: envelope }) })
  await page.goto('/')
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(envelope.message)
  await page.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByRole('alert')).toContainText('Games couldn’t be loaded')
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled()
})

test('keeps source status distinct from kickoff and labels only demo fixtures', async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [
    { ...completed, id: 'past', status: 'scheduled', home_score: null, away_score: null },
    { ...completed, id: 'demo', notes: 'Demo data: fictional matchup and odds' },
  ] }))
  await page.goto('/')
  const cards = page.getByRole('article')
  await expect(cards.nth(0).locator('.badge')).toHaveText('scheduled')
  await expect(cards.nth(0)).toContainText('Kickoff reached · Awaiting provider status update')
  await expect(cards.nth(0).getByRole('checkbox')).toBeDisabled()
  await expect(cards.nth(0).getByText('Demo data', { exact: true })).toHaveCount(0)
  await expect(cards.nth(1).getByText('Demo data', { exact: true })).toBeVisible()
  await expect(page.getByText('Odds are saved observations, not guaranteed live prices.')).toBeVisible()
})

// These messages mirror RefreshService.result, including provider reset wording.
// Controlled browser evidence only: no provider or quota-enforcement integration.
for (const outcome of [
  { reason: 'weekly_limit', remaining: 0, reserved: 0, retry: '2026-10-05T07:00:00+00:00', message: 'Refresh failed: all 20 weekly refreshes have been used. Provider availability follows separate limits. 0 refreshes remaining this week.' },
  { reason: 'sunday_reserve', remaining: 2, reserved: 2, retry: '2026-10-04T07:00:00+00:00', message: 'Refresh failed: the remaining 2 refreshes are reserved until Sunday. 2 refreshes remaining this week. 2 are reserved until Sunday.' },
  { reason: 'cooldown', remaining: 17, reserved: 2, retry: '2026-10-03T18:01:00+00:00', message: 'Refresh failed: refreshed recently. Wait until the retry time. 17 refreshes remaining this week. 2 are reserved until Sunday.' },
  { reason: 'provider_budget', remaining: 17, reserved: 2, retry: null, message: "Refresh failed: a provider's free allowance safety limit was reached. External key use can exhaust it earlier. 17 refreshes remaining this week. 2 are reserved until Sunday. Provider retry/reset time: not yet known." },
  { reason: 'provider_rate_limit', remaining: 17, reserved: 2, retry: '2026-10-03T19:00:00+00:00', message: 'Refresh failed: a provider temporarily limited requests. 17 refreshes remaining this week. 2 are reserved until Sunday. Provider retry/reset time: 2026-10-03T19:00:00+00:00.' },
]) test(`${outcome.reason} preserves backend text and saved data without retrying`, async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-03T18:00:00Z') })
  const requests: string[] = []
  // Match backend paths only: Vite also serves modules under /src/api/.
  await page.route(url => url.pathname.startsWith('/api/'), r => {
    const url = new URL(r.request().url())
    const key = `${r.request().method()} ${url.pathname}${url.search}`
    requests.push(key)
    if (key === 'GET /api/strategies') return r.fulfill({ json: [] })
    if (key === 'GET /api/games?window=current') return r.fulfill({ json: [completed] })
    if (key === 'POST /api/games/refresh') return r.fulfill({ status: 429, json: {
      ...envelope, success: false, reason: outcome.reason, message: outcome.message,
      remaining_refreshes: outcome.remaining, reserved_for_sunday: outcome.reserved,
      retry_at: outcome.retry, data_changed: false,
    } })
    throw new Error(`Unexpected API request: ${key}`)
  })
  await page.goto('/')
  await expect(page.locator('.scores')).toHaveText('Score: UCLA 21 · USC 0')
  const readsBefore = requests.filter(r => r === 'GET /api/games?window=current').length
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(page.locator('#refresh-message')).toHaveText(outcome.message)
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await page.clock.fastForward(120_000)
  await expect(page.locator('.scores')).toHaveText('Score: UCLA 21 · USC 0')
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled()
  expect(requests.filter(r => r === 'POST /api/games/refresh')).toHaveLength(1)
  expect(requests.filter(r => r === 'GET /api/games?window=current')).toHaveLength(readsBefore)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  await expect(page.getByLabel(/API key|provider credentials/i)).toHaveCount(0)
})

for (const partial of [false, true]) test(`Sunday ${partial ? 'partial' : 'full'} refresh retains finals and reloads committed results`, async ({ page }) => {
  // Sunday evening Pacific: both kickoffs have passed, but the server's current
  // Monday-Sunday window still includes them. The UI must not filter them out.
  await page.clock.install({ time: new Date('2026-10-05T04:00:00Z') })
  let stored = [completed], posts = 0, reads = 0
  const sundayFinal = { ...completed, id: 'sunday-final', home_team: 'Oregon', away_team: 'Washington', start_time: '2026-10-05T02:00:00Z', home_score: 28, away_score: 24 }
  const message = partial
    ? "Refresh failed to update all data. Successful updates were saved; failed stages kept saved data. 1 refreshes remaining this week. Games/results updated. Spreads: Refresh failed: a provider's free allowance safety limit was reached. External key use can exhaust it earlier. Provider retry/reset time: not yet known."
    : 'Refresh successful. 1 refreshes remaining this week.'
  await page.route('**/api/games?window=current', r => { reads++; return r.fulfill({ json: stored }) })
  await page.route('**/api/games/refresh', r => {
    posts++
    stored = [sundayFinal, completed]
    return r.fulfill({ json: { ...envelope, success: !partial, reason: partial ? 'partial_failure' : 'refreshed', message, remaining_refreshes: 1, reserved_for_sunday: 0 } })
  })
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(1)
  const initialReads = reads
  expect(posts).toBe(0)
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.locator('#refresh-message')).toHaveText(message)
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.locator('.scores')).toHaveText(['Score: Washington 24 · Oregon 28', 'Score: UCLA 21 · USC 0'])
  for (const box of await page.getByRole('checkbox').all()) await expect(box).toBeDisabled()
  expect(reads).toBe(initialReads + 1)
  // A new page load reads the same stored results without another refresh.
  await page.reload()
  await expect(page.locator('.scores')).toHaveText(['Score: Washington 24 · Oregon 28', 'Score: UCLA 21 · USC 0'])
  expect(posts).toBe(1)
})
