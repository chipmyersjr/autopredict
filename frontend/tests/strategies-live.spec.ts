import { test, expect } from '@playwright/test'
import type { Preview } from '../src/api/strategies'
import type { Game } from '../src/api/games'
function formatLine(line: string) {
  if (Number(line) === 0) return 'Pick’em'
  const trimmed = line.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
  return trimmed.startsWith('-') ? trimmed : `+${trimmed}`
}
for (const width of [375, 1280]) test(`live decision preview at ${width}px`, async ({ page, request }) => {
  test.skip(!process.env.LIVE_API, 'Requires seeded PostgreSQL backend')
  const base = process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8003'
  const games: Game[] = await (await request.get(`${base}/api/games`)).json()
  await page.setViewportSize({ width, height: 1000 }); await page.goto('/')
  const boxes = page.getByRole('checkbox')
  await expect(boxes).toHaveCount(games.length)
  let count = 0
  for (let i = 0; i < games.length; i++) if (await boxes.nth(i).isEnabled()) { await boxes.nth(i).check(); count++ }
  expect(count).toBeGreaterThan(0)
  const response = page.waitForResponse(r => r.url().endsWith('/decisions') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Execute Random Strategy' }).click()
  const result: Preview = await (await response).json()
  expect(result.decisions.length).toBe(count)
  const region = page.getByRole('region', { name: 'Decision preview', exact: true })
  for (const decision of result.decisions) {
    const selection = games.find(g => g.id === decision.game_id)!.markets.find(m => m.id === decision.market_id)!.selections.find(s => s.id === decision.selection_id)!
    expect(decision.line).toBe(selection.line); expect(decision.price).toBe(selection.price)
    await expect(region).toContainText(`${decision.side} ${formatLine(decision.line)}`)
    await expect(region).toContainText(decision.price)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/strategies-live-${width}.png`, fullPage: true })
})
