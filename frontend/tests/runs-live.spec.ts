import { test, expect } from '@playwright/test'
import { finalize, completedRun } from './support/guided'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import type { RunResult } from '../src/api/runs'
import type { Game } from '../src/api/games'
import { formatLine } from '../src/format'

test.describe('isolated PostgreSQL saved-run flow', () => {
  test.describe.configure({ mode: 'serial' })
  for (const width of [375, 1280]) test(`create, lose response, recover, mutate quotes and reload at ${width}px`, async ({ page, request }) => {
    test.setTimeout(60000)
    test.skip(!process.env.LIVE_RUN_DB_FILE, 'Requires disposable live_backend.py server and metadata file')
    const base = process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8017'
    const games: Game[] = await (await request.get(`${base}/api/games?window=current`)).json()
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/')
    const boxes = page.getByRole('checkbox')
    await expect(boxes).toHaveCount(games.length)
    const selected: string[] = []
    // Two eligible fixtures per width; mutations remain confined to those games.
    for (let i = 0; i < games.length && selected.length < 2; i++) if (await boxes.nth(i).isEnabled()) {
      selected.push(games[i].id)
    }
    expect(selected).toHaveLength(2)
    for (let i = 0; i < games.length; i++) if (!selected.includes(games[i].id) && await boxes.nth(i).isEnabled()) await boxes.nth(i).uncheck()
    await finalize(page)
    await page.getByLabel('Run name (optional)').fill(`Browser Run ${width}`)
    await page.getByLabel('Starting bankroll').fill('20.00')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/runs-create-live-${width}.png`, fullPage: true })
    let created: RunResult | undefined
    const identities: { key: string; body: unknown }[] = []
    await page.route('**/api/runs', async route => {
      if (route.request().method() !== 'POST') return route.continue()
      identities.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() })
      const response = await route.fetch()
      if (identities.length === 1) {
        expect(response.status()).toBe(201)
        created = await response.json()
        await route.abort('failed') // Commit succeeded; response is intentionally lost.
      } else {
        expect(response.status()).toBe(200)
        expect((await response.json()).run.id).toBe(created!.run.id)
        await route.fulfill({ response })
      }
    })
    await page.getByRole('button', { name: 'Create Run', exact: true }).focus(); await page.keyboard.press('Enter')
    await expect(page.getByRole('alert')).toContainText('may have succeeded')
    await page.reload()
    await expect(page.getByRole('button', { name: 'Retry creation' })).toBeVisible()
    await page.getByRole('button', { name: 'Retry creation' }).click()
    await expect(page).toHaveURL(new RegExp(created!.run.id))
    expect(identities).toHaveLength(2); expect(identities[0]).toEqual(identities[1])
    created = await completedRun(request, base, created!.run.id)
    await page.reload()
    expect(created!.run.committed_stake).toBe('20.00'); expect(created!.run.available_bankroll).toBe('0.00')
    expect(created!.bets).toHaveLength(2)
    const saved = page.getByRole('region', { name: 'Saved Bets', exact: true })
    for (const bet of created!.bets) {
      const source = games.find(g => g.id === bet.game_id)!.markets.find(m => m.id === bet.market_id)!.selections.find(s => s.id === bet.selection_id)!
      expect(bet.line).toBe(source.line); expect(bet.price).toBe(source.price); expect(bet.stake).toBe('10.00')
      await expect(saved).toContainText(`${bet.side} ${formatLine(bet.line)}`)
      await expect(saved).toContainText(bet.price)
    }
    const before = await saved.innerText()
    execFileSync(resolve('../backend/.venv/bin/python'), [resolve('tests/support/live_backend.py'), '--metadata', process.env.LIVE_RUN_DB_FILE!, '--mutate-run', created!.run.id])
    await page.reload(); await expect(saved).toContainText('Saved Bets')
    expect(await saved.innerText()).toBe(before)
    expect(await (await request.get(`${base}/api/runs/${created!.run.id}/bets`)).json()).toEqual(created!.bets)
    const current: Game[] = await (await request.get(`${base}/api/games`)).json()
    expect(current.filter(g => selected.includes(g.id)).every(g => g.home_team === 'Changed current home')).toBe(true)
    await expect(saved).not.toContainText('Changed current home'); await expect(saved).not.toContainText('3.1234')
    await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Pending results')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/runs-live-${width}.png`, fullPage: true })
    await page.getByRole('link', { name: 'All Runs' }).click()
    const history = await (await request.get(`${base}/api/runs`)).json()
    expect(history.filter((r: { id: string }) => r.id === created!.run.id)).toHaveLength(1)
    await page.getByRole('link', { name: `Browser Run ${width}` }).click()
    await expect(saved).toContainText('Saved Bets')
    execFileSync(resolve('../backend/.venv/bin/python'), [resolve('tests/support/live_backend.py'), '--metadata', process.env.LIVE_RUN_DB_FILE!, '--restore-run', created!.run.id])
  })
})
