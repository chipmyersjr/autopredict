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
