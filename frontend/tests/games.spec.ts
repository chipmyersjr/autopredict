import { test, expect } from '@playwright/test'
import type { Game, Market, Selection } from '../src/api/games'

test.beforeEach(async ({ page }) => {
  if (!process.env.LIVE_API) await page.route('**/api/strategies', r => r.fulfill({ json: [] }))
})

const timestamps = { created_at: '2026-10-01T00:00:00+00:00', updated_at: '2026-10-01T00:00:00+00:00' }
function selection(id: string, side: string, line: string | null, extra: Partial<Selection> = {}): Selection {
  return { ...timestamps, id, market_id: 'market', side, line, price: '1.9091', is_active: true, notes: null, ...extra }
}
function market(id: string, selections: Selection[], extra: Partial<Market> = {}): Market {
  return { ...timestamps, id, game_id: 'game', type: 'spread', status: 'active', description: null, selections, ...extra }
}
function game(extra: Partial<Game> = {}): Game {
  return { ...timestamps, id: 'game', season: 2026, week: 5, home_team: 'USC', away_team: 'UCLA', start_time: '2026-10-02T19:00:00+00:00', status: 'scheduled', home_score: null, away_score: null, venue: null, notes: null, markets: [market('market', [selection('home', 'USC', '-3.50'), selection('away', 'UCLA', '3.50')])], ...extra }
}

test('renders paired signed spreads, exact odds and local kickoff', async ({ page }) => {
  const requests: string[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    if (route.request().url().endsWith('/api/strategies')) { await route.fulfill({ json: [] }); return }
    requests.push(route.request().url())
    await route.fulfill({ json: [game()] })
  })
  await page.goto('/')
  const card = page.getByRole('article')
  await expect(card).toHaveCount(1)
  await expect(card.locator('time')).toContainText('12:00 PM PDT')
  await expect(page.getByRole('status')).toContainText('America/Los_Angeles')
  await expect(card.locator('.line')).toHaveText(['-3.5', '+3.5'])
  await expect(card.locator('.price strong')).toHaveText(['1.9091', '1.9091'])
  await expect(card.getByText('Score:')).toHaveCount(0)
  await expect(page.getByText(/Fictional games and odds/)).toBeVisible()
  expect(requests.every(url => url.endsWith('/api/games'))).toBeTruthy()
})

test('keeps markets separate, excludes closed/inactive/null lines and preserves zero scores', async ({ page }) => {
  await page.route('**/api/games', route => route.fulfill({ json: [game({ status: 'completed', home_score: 0, away_score: null, markets: [
    market('zero', [selection('z', 'USC', '0.00'), selection('null', 'UCLA', null)]),
    market('second', [selection('s', 'UCLA', '1234567890.25', { price: '1.9876' })]),
    market('closed', [selection('c', 'Hidden closed', '-7.00')], { status: 'closed' }),
    market('inactive', [selection('i', 'Hidden inactive', '7.00', { is_active: false })]),
  ] }), game({ id: 'empty', markets: [] })] }))
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'Spread market 1' })).toContainText('Pick’em')
  await expect(page.getByRole('region', { name: 'Spread market 2' })).toContainText('+1234567890.25')
  await expect(page.locator('.price strong')).toHaveText(['1.9091', '1.9876'])
  await expect(page.getByText('Hidden closed')).toHaveCount(0)
  await expect(page.getByText('Hidden inactive')).toHaveCount(0)
  await expect(page.getByText('Spread unavailable')).toBeVisible()
  await expect(page.locator('.scores')).toHaveText('Score: UCLA — · USC 0')
})

test('empty database is different from missing spreads', async ({ page }) => {
  await page.route('**/api/games', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'No games stored yet' })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const failure of ['503', 'network', 'invalid-json']) {
  test(`${failure} can recover using keyboard Retry with loading protection`, async ({ page }) => {
    let recover = false
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    await page.route('**/api/games', async route => {
      if (recover) { await pending; await route.fulfill({ json: [game()] }); return }
      if (failure === 'network') await route.abort('failed')
      else if (failure === 'invalid-json') await route.fulfill({ body: 'not json', contentType: 'application/json' })
      else await route.fulfill({ status: 503, json: { detail: 'Database unavailable' } })
    })
    await page.goto('/')
    await expect(page.getByRole('alert')).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Retry' })).toBeFocused()
    expect(await page.getByRole('button').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid')
    recover = true
    await page.keyboard.press('Enter')
    await expect(page.getByRole('status')).toContainText('Loading games…')
    await expect(page.getByRole('button', { name: 'Retry' })).toHaveCount(0)
    release()
    await expect(page.getByRole('article')).toHaveCount(1)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}

test('StrictMode cleanup aborts stale fetch and cannot overwrite latest state', async ({ page }) => {
  await page.addInitScript(() => {
    let calls = 0
    const original = window.fetch
    window.fetch = async (input, init) => {
      if (!String(input).endsWith('/api/games')) return original(input, init)
      calls++
      if (calls === 1) {
        await new Promise(resolve => setTimeout(resolve, 500))
        ;(window as unknown as { staleAborted: boolean }).staleAborted = Boolean(init?.signal?.aborted)
        return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } })
      }
      return original(input, init)
    }
  })
  await page.route('**/api/games', route => route.fulfill({ json: [game()] }))
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect.poll(() => page.evaluate(() => (window as unknown as { staleAborted: boolean }).staleAborted)).toBe(true)
  await expect(page.getByRole('article')).toHaveCount(1)
})

for (const width of [375, 1280]) {
  test(`long teams fit at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const longName = 'A very long college football team name with many words'
    await page.route('**/api/games', route => route.fulfill({ json: [game({ home_team: longName, markets: [market('long', [selection('long', longName, '-3.50')])] })] }))
    await page.goto('/')
    await expect(page.getByRole('article')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const clipped = await page.locator('h2, .selection-team, .line, .price').evaluateAll(els => els.some(el => el.scrollWidth > el.clientWidth + 1))
    expect(clipped).toBe(false)
    await page.screenshot({ path: `test-results/games-${width}.png`, fullPage: true })
  })
}

test('real seeded backend renders every game and exact stored spreads', async ({ page, request }) => {
  test.skip(!process.env.LIVE_API, 'Set LIVE_API=1 to verify the seeded development backend')
  const base = process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8001'
  const response = await request.get(`${base}/api/games`)
  expect(response.ok()).toBeTruthy()
  const games: Game[] = await response.json()
  expect(games).toHaveLength(5)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(games.length)
  for (const [index, item] of games.entries()) {
    const card = page.getByRole('article').nth(index)
    await expect(card.getByRole('heading', { level: 2 })).toHaveText(`${item.away_team} at ${item.home_team}`)
    for (const m of item.markets) for (const s of m.selections) {
      const row = card.locator('.selections li').filter({ has: page.getByText(s.side, { exact: true }) })
      await expect(row.locator('.price strong')).toHaveText(s.price)
      const formatted = s.line === '0.00' ? 'Pick’em' : s.line!.replace(/\.00$/, '').replace(/0$/, '')
      await expect(row.locator('.line')).toHaveText(formatted.startsWith('-') || formatted === 'Pick’em' ? formatted : `+${formatted}`)
    }
  }
  await expect(page.getByText('Spread unavailable')).toHaveCount(1)
  await expect(page.getByText('Pick’em', { exact: true })).toHaveCount(2)
  expect(errors).toEqual([])
  await page.screenshot({ path: 'test-results/games-live.png', fullPage: true })
})
