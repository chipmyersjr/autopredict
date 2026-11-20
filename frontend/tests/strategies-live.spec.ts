import { test, expect } from '@playwright/test'
import type { Strategy } from '../src/api/strategies'

for (const width of [375, 1280]) test(`live shared strategies and retired preview at ${width}px`, async ({ page, request }) => {
  test.skip(!process.env.LIVE_API, 'Requires seeded PostgreSQL backend')
  const base = process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8003'
  const response = await request.get(`${base}/api/strategies`)
  expect(response.ok()).toBe(true)
  const strategies: Strategy[] = await response.json()
  expect(strategies.some(s => s.type === 'random' && s.is_active)).toBe(true)
  const agent = strategies.find(s => s.type === 'agent' && s.is_active)
  expect(agent?.config).toEqual({ profile: 'FootballAnalysisExpert' })
  const retired = await request.post(`${base}/api/strategies/${strategies[0].id}/decisions`, { data: { game_ids: [] } })
  expect(retired.status()).toBe(410)
  const predictions: string[] = []
  page.on('request', r => { if (r.url().includes('/decisions')) predictions.push(r.url()) })
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Games', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preview decisions' })).toHaveCount(0)
  expect(predictions).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
