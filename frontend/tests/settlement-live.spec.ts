import { test, expect } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { createServer } from 'node:net'
import type { RunResult, SettlementResult } from '../src/api/runs'
import type { Dashboard } from '../src/api/dashboard'

// Each viewport owns a generated database. No production result endpoints,
// provider requests, or shared development data are involved.
for (const width of [375, 1280]) test(`PostgreSQL resolution oracle and recovery at ${width}px`, async ({ page, request }) => {
  test.skip(!process.env.LIVE_API || !process.env.LIVE_RUN_DB_FILE, 'Opt-in disposable PostgreSQL acceptance')
  test.setTimeout(90000)
  const directory = mkdtempSync(join(tmpdir(), 'settlement-browser-'))
  const metadata = join(directory, 'backend.json'), results = join(directory, 'results.json')
  const python = resolve('../backend/.venv/bin/python'), helper = resolve('tests/support/live_backend.py')
  const socket = createServer()
  await new Promise<void>(done => socket.listen(0, '127.0.0.1', done))
  const address = socket.address()
  if (!address || typeof address === 'string') throw new Error('Missing fixture port')
  const port = address.port
  await new Promise<void>(done => socket.close(() => done()))
  const base = `http://127.0.0.1:${port}`
  const env = { ...process.env, CFBD_API_KEY: '', ODDS_API_KEY: '', PYTHONDONTWRITEBYTECODE: '1' }
  const origin = new URL(test.info().project.use.baseURL!).origin
  const child = spawn(python, [helper, '--metadata', metadata, '--port', String(port), '--origin', origin], { env })
  let logs = ''
  child.stdout.on('data', data => { logs += data }); child.stderr.on('data', data => { logs += data })
  try {
    await expect.poll(async () => {
      if (child.exitCode !== null) throw new Error(logs)
      try { return existsSync(metadata) && (await request.get(`${base}/api/ready`)).ok() } catch { return false }
    }, { timeout: 45000 }).toBe(true)
    const gamesResponse = await request.get(`${base}/api/games?window=current`)
    expect(gamesResponse.ok()).toBe(true)
    expect(await gamesResponse.json()).toHaveLength(5)
    // Forward every browser API call to this real server; no fabricated responses.
    // Use a fresh API request so Host and CORS headers refer to the isolated
    // server, rather than retaining the shared server's authority.
    // Vite also serves modules under /src/api/. Only application endpoints
    // belong on FastAPI; source modules must continue to the frontend server.
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const url = new URL(route.request().url())
      const headers = { ...route.request().headers() }
      delete headers.host
      headers.origin = origin
      const response = await request.fetch(`${base}${url.pathname}${url.search}`, {
        method: route.request().method(), headers,
        data: route.request().postDataBuffer() ?? undefined,
      })
      expect(response.ok(), `${url.pathname}: ${await response.text()}`).toBe(true)
      await route.fulfill({ response })
    })
    await page.setViewportSize({ width, height: 1000 })
    const gamesLoaded = page.waitForResponse(r => new URL(r.url()).pathname === '/api/games')
    await page.goto('/')
    const browserGames = await gamesLoaded
    expect(browserGames.ok()).toBe(true)
    expect(await browserGames.json()).toEqual(await gamesResponse.json())
    await expect(page.getByRole('checkbox')).toHaveCount(5)
    for (const box of await page.getByRole('checkbox').all()) if (await box.isEnabled()) {
      await box.focus(); await page.keyboard.press('Space')
    }
    await page.getByLabel('Run name (optional)').fill(`Resolution ${width}`)
    await page.getByLabel('Starting bankroll').fill('100.00')
    await page.getByLabel('Stake per Bet', { exact: false }).fill('10.00')
    const creation = page.waitForResponse(r => r.url().endsWith('/api/runs') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create Dry Run', exact: true }).click()
    const created: RunResult = await (await creation).json()
    expect(created.bets).toHaveLength(4)
    expect(created.run).toMatchObject({ starting_bankroll: '100.00', committed_stake: '40.00', available_bankroll: '60.00', total_profit: null, roi: null, final_bankroll: null })
    expect(created.bets.every(b => b.line === '0.00' && b.price === '1.9500' && b.stake === '10.00' && b.result === null)).toBe(true)
    const path = `/api/runs/${created.run.id}`
    const summary = page.getByRole('region', { name: 'Run summary' })
    const saved = page.getByRole('region', { name: 'Saved Bets', exact: true })
    const metric = async (label: string, value: string) => {
      await expect(summary.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) }).locator('dd')).toHaveText(value)
    }
    const settle = async () => {
      const response = page.waitForResponse(r => r.url().endsWith(`${path}/settle`))
      await page.getByRole('button', { name: 'Settle completed games', exact: true }).focus()
      await page.keyboard.press('Enter')
      return await (await response).json() as SettlementResult
    }
    const pending = await settle()
    expect(pending.settled_bet_ids).toEqual([])
    expect(pending.pending_games.map(g => g.reason)).toEqual(Array(4).fill('game_not_final'))
    await expect(summary).toContainText('No new Bets settled.')
    await metric('Realized profit', 'Not settled')
    const finalize = (values: Record<string, { status: string; home_score: number | null; away_score: number | null }>) => {
      writeFileSync(results, JSON.stringify(values))
      execFileSync(python, [helper, '--metadata', metadata, '--finalize-run', created.run.id, '--results', results], { env })
    }
    const finals: Parameters<typeof finalize>[0] = {}
    created.bets.slice(0, 3).forEach((bet, index) => {
      const homeWins = index === 0 ? bet.side === bet.home_team : bet.side !== bet.home_team
      finals[bet.game_id] = { status: 'completed', home_score: index === 2 ? 7 : homeWins ? 21 : 14, away_score: index === 2 ? 7 : homeWins ? 14 : 21 }
    })
    finalize(finals)
    execFileSync(python, [helper, '--metadata', metadata, '--mutate-run', created.run.id], { env })
    expect(await (await request.get(`${base}${path}/bets`)).json()).toEqual(created.bets)
    let lost: SettlementResult | undefined
    await page.route(`**${path}/settle`, async route => {
      expect(route.request().method()).toBe('POST')
      expect(route.request().postData()).toBeNull()
      expect(route.request().headers()['idempotency-key']).toBeUndefined()
      const response = await request.post(`${base}${path}/settle`)
      expect(response.ok()).toBe(true)
      lost = await response.json()
      await route.abort('failed')
    }, { times: 1 })
    await page.getByRole('button', { name: 'Settle completed games', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('may have been saved')
    expect(lost!.bets.map(b => b.result)).toEqual(['won', 'lost', 'pushed', null])
    expect(lost!.bets.map(b => b.profit)).toEqual(['9.50', '-10.00', '0.00', null])
    expect(lost!.run).toMatchObject({ total_profit: '-0.50', roi: '-0.0050', current_bankroll: '99.50', available_bankroll: '89.50', committed_stake: '10.00', final_bankroll: null, end_time: null })
    const retryResponse = page.waitForResponse(r => r.url().endsWith(`${path}/settle`))
    await page.getByRole('button', { name: 'Retry settlement safely' }).click()
    expect(await (await retryResponse).json()).toEqual({ ...lost, settled_bet_ids: [] })
    await expect(page.getByLabel('Settlement feedback')).toBeFocused()
    await page.reload()
    await expect(summary).toContainText('Partially settled')
    for (const [label, value] of [['Realized profit', '-0.50'], ['Realized ROI', '-0.5%'], ['Current bankroll', '99.50'], ['Available bankroll', '89.50'], ['Open committed stake', '10.00']]) await metric(label, value)
    await expect(summary.getByText('Final bankroll', { exact: true })).toHaveCount(0)
    const remaining = created.bets[3].game_id
    finalize({ [remaining]: { status: 'completed', home_score: null, away_score: null } })
    const missing = await settle()
    expect(missing.pending_games).toEqual([{ game_id: remaining, reason: 'final_scores_missing' }])
    await expect(summary).toContainText('Final scores missing')
    finalize({ [remaining]: { status: 'canceled', home_score: null, away_score: null } })
    const complete = await settle()
    expect(complete.run).toMatchObject({ status: 'completed', final_bankroll: '99.50', available_bankroll: '99.50', committed_stake: '0.00', total_profit: '-0.50', roi: '-0.0050', win_count: 1, loss_count: 1, push_count: 1, void_count: 1, open_bet_count: 0 })
    expect(complete.run.end_time).not.toBeNull()
    expect(complete.bets.map(b => b.profit)).toEqual(['9.50', '-10.00', '0.00', '0.00'])
    expect(complete.bets.map(b => b.result)).toEqual(['won', 'lost', 'pushed', 'void'])
    for (let i = 0; i < 4; i++) {
      const original = created.bets[i], persisted = complete.bets[i]
      for (const key of ['side', 'line', 'price', 'stake', 'home_team', 'away_team', 'kickoff_at_placement', 'quote_provenance', 'placed_at'] as const) expect(persisted[key]).toEqual(original[key])
      expect(persisted.settled_at).not.toBeNull()
      expect(persisted.settlement_game_status).toBe(i === 3 ? 'canceled' : 'completed')
      expect(persisted.settlement_home_score).toBe(i === 3 ? null : finals[original.game_id].home_score)
      expect(persisted.settlement_away_score).toBe(i === 3 ? null : finals[original.game_id].away_score)
    }
    expect(await (await request.post(`${base}${path}/settle`)).json()).toEqual({ ...complete, settled_bet_ids: [] })
    expect(await (await request.get(`${base}${path}`)).json()).toEqual(complete.run)
    expect(await (await request.get(`${base}${path}/bets`)).json()).toEqual(complete.bets)
    const database = JSON.parse(execFileSync(python, [helper, '--metadata', metadata, '--inspect-run', created.run.id], { env, encoding: 'utf8' }))
    expect(database.run).toMatchObject({ final_bankroll: '99.50', total_profit: '-0.50', roi: '-0.0050', status: 'completed' })
    for (const bet of complete.bets) {
      const row = database.bets.find((value: { id: string }) => value.id === bet.id)
      expect(row).toMatchObject({ side: bet.side, line: bet.line, price: bet.price, stake: bet.stake, profit: bet.profit, result: bet.result, settlement_game_status: bet.settlement_game_status, settlement_home_score: bet.settlement_home_score, settlement_away_score: bet.settlement_away_score })
      expect(new Date(row.settled_at).toISOString()).toBe(new Date(bet.settled_at!).toISOString())
    }
    await page.reload()
    await metric('Final bankroll', '99.50')
    await expect(page.getByRole('button', { name: 'Settle completed games', exact: true })).toBeDisabled()
    await expect(saved).toContainText('Push · Stake returned · Zero profit')
    await expect(saved).toContainText('Canceled · Void · Stake returned · Zero profit')
    await expect(saved).not.toContainText('Changed current home')
    await expect(saved).not.toContainText('3.1234')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/settlement-live-${width}.png`, fullPage: true })
    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await page.reload()
    const dashboard: Dashboard = await (await request.get(`${base}/api/dashboard`)).json()
    expect(dashboard).toMatchObject({ run_count: 1, completed_run_count: 1, realized_profit: '-0.50', roi: '-0.0050', current_bankroll_total: '99.50', available_bankroll_total: '99.50', committed_stake_total: '0.00', win_count: 1, loss_count: 1, push_count: 1, void_count: 1 })
    expect(dashboard.performance).toEqual([{ date: complete.bets[0].settled_at!.slice(0, 10), profit: '-0.50', cumulative_profit: '-0.50' }])
    expect(dashboard.recent_results.map(b => b.id).sort()).toEqual(complete.bets.map(b => b.id).sort())
    const totals = page.getByRole('region', { name: 'Simulation totals' })
    for (const [label, value] of [['Realized profit', '-0.50'], ['Realized ROI', '-0.5%'], ['Current bankroll total', '99.50']]) await expect(totals.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) }).locator('dd')).toHaveText(value)
    await expect(page.getByRole('table')).toContainText(dashboard.performance[0].date)
    await expect(page.getByRole('table').locator('tbody td')).toHaveText(['-0.50', '-0.50'])
    await page.getByRole('region', { name: 'Performance values' }).focus()
    await expect(page.getByRole('region', { name: 'Performance values' })).toBeFocused()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/settlement-dashboard-live-${width}.png`, fullPage: true })
    await page.getByRole('link', { name: /View saved Run/ }).first().click()
    await metric('Final bankroll', '99.50')
    await page.getByRole('link', { name: 'All Runs' }).click()
    await expect(page.getByRole('main')).toContainText('Final bankroll: 99.50')
  } finally {
    const exited = new Promise<void>((done, reject) => {
      child.once('exit', () => done())
      child.once('error', reject)
    })
    if (child.exitCode === null) { child.kill('SIGTERM'); await exited }
    expect(existsSync(metadata), logs).toBe(false)
    rmSync(directory, { recursive: true, force: true })
  }
})
