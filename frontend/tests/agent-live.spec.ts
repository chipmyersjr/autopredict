import { test, expect } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createServer } from 'node:net'
import { finalize, completedRun } from './support/guided'
import type { RunCreate, RunExecution, RunResult, SettlementResult } from '../src/api/runs'
import type { Game } from '../src/api/games'

// These tests are discovered by the standard --live --backend-arg=--agent-worker
// command. Only the external transports are controlled; every API response,
// progress transition, retry, Bet and financial result is produced by the app.
for (const width of [375, 1280]) test(`guided Agent PostgreSQL lifecycle at ${width}px`, async ({ page, request, context }) => {
  test.skip(!process.env.LIVE_API, 'Requires the opt-in disposable PostgreSQL browser invocation')
  test.setTimeout(180000)
  expect(process.env.LIVE_RUN_DB_FILE, 'Live invocation must provide database metadata').toBeTruthy()
  const shared = JSON.parse(readFileSync(process.env.LIVE_RUN_DB_FILE!, 'utf8'))
  expect(shared.worker_pid, 'Run live acceptance with --backend-arg=--agent-worker').toBeTruthy()
  const directory = mkdtempSync(join(tmpdir(), 'agent-browser-'))
  const metadata = join(directory, 'backend.json')
  const python = resolve('../backend/.venv/bin/python'), helper = resolve('tests/support/live_backend.py')
  const socket = createServer()
  await new Promise<void>(done => socket.listen(0, '127.0.0.1', done))
  const address = socket.address()
  if (!address || typeof address === 'string') throw new Error('No fixture port')
  const port = address.port
  await new Promise<void>(done => socket.close(() => done()))
  const base = `http://127.0.0.1:${port}`
  const origin = new URL(test.info().project.use.baseURL!).origin
  const env = { ...process.env, CFBD_API_KEY: '', ODDS_API_KEY: '', OLLAMA_API_KEY: '', PYTHONDONTWRITEBYTECODE: '1' }
  const child = spawn(python, [helper, '--metadata', metadata, '--port', String(port), '--origin', origin, '--agent-worker'], { env })
  let logs = ''
  child.stdout.on('data', data => { logs += data }); child.stderr.on('data', data => { logs += data })
  const fixture = (...args: string[]) => execFileSync(python, [helper, '--metadata', metadata, ...args], { env, encoding: 'utf8' })
  const control = (values: Record<string, { mode?: string; hold_attempt?: number }>) => fixture('--control', JSON.stringify(values))
  const inspect = (id: string) => JSON.parse(fixture('--inspect-run', id))
  const execution = async (id: string): Promise<RunExecution> => {
    const response = await request.get(`${base}/api/runs/${id}/execution`)
    expect(response.ok()).toBe(true)
    return response.json()
  }
  let posts = 0, lost = false, accepted: RunResult | undefined
  const identities: { key: string; body: RunCreate }[] = []
  try {
    await expect.poll(async () => {
      if (child.exitCode !== null) throw new Error(logs)
      try { return existsSync(metadata) && (await request.get(`${base}/api/ready`)).ok() } catch { return false }
    }, { timeout: 45000 }).toBe(true)
    // Context routing also covers a genuinely new page after closing the first.
    await context.route(url => url.pathname.startsWith('/api/'), async route => {
      const incoming = route.request(), url = new URL(incoming.url())
      expect(url.pathname).not.toContain('/decisions')
      const headers = { ...incoming.headers(), origin }
      delete headers.host
      const response = await request.fetch(`${base}${url.pathname}${url.search}`, {
        method: incoming.method(), headers, data: incoming.postDataBuffer() ?? undefined,
      })
      if (incoming.method() === 'POST' && url.pathname === '/api/runs') {
        posts++
        identities.push({ key: headers['idempotency-key'], body: incoming.postDataJSON() })
        accepted = await response.json()
        expect(response.status()).toBe(lost ? 201 : identities.length === 2 ? 200 : 201)
        if (lost) { lost = false; return route.abort('failed') }
      }
      await route.fulfill({ response })
    })
    await page.setViewportSize({ width, height: 1000 })
    const games: Game[] = await (await request.get(`${base}/api/games?window=current`)).json()
    const eligible = games.filter(g => g.status === 'scheduled' && g.markets.some(m => m.selections.length === 2))
    expect(eligible).toHaveLength(4)
    const ids = eligible.map(g => g.id)
    const prepare = async (name: string) => {
      const count = posts
      await page.goto('/#/games')
      await expect(page.getByRole('radio', { name: 'FootballAnalysisExpert' })).not.toBeChecked()
      await finalize(page, 'FootballAnalysisExpert')
      await page.getByLabel('Starting bankroll').fill('1.00')
      await page.getByLabel('Stake per Bet', { exact: false }).fill('0.11')
      await page.getByLabel('Run name (optional)').fill(name)
      await expect(page.getByRole('main')).toContainText('0.44')
      expect(posts).toBe(count)
    }
    const submit = async () => {
      const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/runs' && r.request().method() === 'POST')
      await page.getByRole('button', { name: 'Create Run', exact: true }).focus()
      await page.keyboard.press('Enter')
      const result: RunResult = await (await response).json()
      expect(result.bets).toEqual([])
      expect(result.run.execution_status).toBe('queued')
      await expect(page).toHaveURL(new RegExp(result.run.id))
      return result.run.id
    }

    // Hold the first actual model call so response loss/replay and restart are
    // deterministic and persisted progress can be inspected without timers.
    control(Object.fromEntries(ids.map(id => [id, { hold_attempt: 1 }])))
    await prepare(`Agent recovery ${width}`)
    lost = true
    await page.getByRole('button', { name: 'Create Run', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('may have succeeded')
    const id = accepted!.run.id
    await page.reload()
    await page.getByRole('button', { name: 'Retry creation' }).click()
    await expect(page).toHaveURL(new RegExp(id))
    expect(identities).toHaveLength(2)
    expect(identities[0]).toEqual(identities[1])
    await expect.poll(async () => (await execution(id)).games.filter(g => g.state === 'analysing').length).toBe(1)
    const beforeRestart = inspect(id)
    expect(beforeRestart.bets).toEqual([])
    const heldProgress = await execution(id)
    expect(heldProgress.status).toBe('running')
    expect(heldProgress.total_games).toBe(4)
    expect(heldProgress.completed_games).toBe(0)
    expect(heldProgress.games.map(g => g.game_id).sort()).toEqual([...ids].sort())
    expect(beforeRestart.run).toMatchObject({ status: 'open', total_profit: null, roi: null, final_bankroll: null })
    await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Processing predictions')
    await expect(page.getByRole('button', { name: 'Settle completed games', exact: true })).toBeDisabled()
    await page.screenshot({ path: `test-results/agent-processing-${width}.png`, fullPage: true })
    await page.close()
    fixture('--restart-worker')
    await expect.poll(() => inspect(id).run.execution_generation, { timeout: 20000 }).toBeGreaterThan(beforeRestart.run.execution_generation)
    // Retry budget survives the process boundary; release held research.
    control({})
    page = await context.newPage()
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/#/runs')
    await page.getByRole('link', { name: `Agent recovery ${width}` }).click()
    const completed = await completedRun(request, base, id)
    await page.reload()
    expect(completed.bets).toHaveLength(4)
    expect(new Set(completed.bets.map(b => b.game_id)).size).toBe(4)
    expect((await execution(id)).games.every(g => g.attempts <= 2)).toBe(true)
    expect((await execution(id)).games.some(g => g.attempts === 2)).toBe(true)
    const durable = inspect(id)
    // Ordinary reads and reopening a finished Run must never repeat research
    // or alter persisted execution/accounting evidence.
    await request.get(`${base}/api/runs`)
    await request.get(`${base}/api/dashboard`)
    await execution(id)
    const replay = await request.post(`${base}/api/runs`, {
      headers: { 'Idempotency-Key': identities[0].key }, data: identities[0].body,
    })
    expect(replay.status()).toBe(200)
    expect((await replay.json()).bets).toEqual(completed.bets)
    expect(inspect(id)).toEqual(durable)
    const saved = page.getByRole('region', { name: 'Saved Bets', exact: true })
    await expect(saved.locator('summary')).toHaveCount(4)
    await saved.locator('summary').first().focus(); await page.keyboard.press('Enter')
    await expect(saved).toContainText('Controlled fictional research supports this saved spread selection.')
    for (const bet of completed.bets) {
      expect(bet).toMatchObject({ stake: '0.11', price: '1.9500', line: '0.00', reasoning: 'Controlled fictional research supports this saved spread selection.' })
      expect(bet.side === bet.home_team || bet.side === bet.away_team).toBe(true)
    }
    const results = join(directory, 'results.json')
    writeFileSync(results, JSON.stringify(Object.fromEntries(completed.bets.map((b, i) => [b.game_id, {
      status: 'completed', home_score: i === 0 ? b.side === b.home_team ? 7 : 0 : 0,
      away_score: i === 0 ? b.side === b.away_team ? 7 : 0 : 0,
    }]))))
    fixture('--finalize-run', id, '--results', results)
    const settlement = page.waitForResponse(r => r.url().endsWith(`/runs/${id}/settle`))
    await page.getByRole('button', { name: 'Settle completed games', exact: true }).click()
    const settled: SettlementResult = await (await settlement).json()
    expect(settled.run).toMatchObject({ total_profit: '0.10', roi: '0.1000', final_bankroll: '1.10', committed_stake: '0.00' })
    for (const bet of settled.bets) {
      const original = completed.bets.find(b => b.id === bet.id)!
      for (const key of ['reasoning', 'side', 'line', 'price', 'stake', 'quote_provenance', 'kickoff_at_placement'] as const) expect(bet[key]).toEqual(original[key])
    }
    await page.reload()
    await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('1.10')
    expect(inspect(id).run.total_profit).toBe('0.10')
    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Simulation totals' })).toContainText('0.10')
    await page.screenshot({ path: `test-results/agent-dashboard-${width}.png`, fullPage: true })

    // Restore only fictional fixture data before further independent Runs.
    fixture('--restore-run', id)
    control({ [ids[0]]: { mode: 'research_failed' }, [ids[1]]: { mode: 'invalid' }, [ids[2]]: { mode: 'unavailable' }, [ids[3]]: { mode: 'retry_once' } })
    await prepare(`Agent partial ${width}`)
    const partialId = await submit()
    const partial = await completedRun(request, base, partialId)
    expect(partial.bets).toHaveLength(1)
    expect(partial.skipped_games.map(g => g.reason).sort()).toEqual(['agent_unavailable', 'invalid_agent_decision', 'research_failed'])
    expect((await execution(partialId)).games.every(g => g.attempts === 2)).toBe(true)
    await page.reload()
    for (const label of ['Research failed after retry', 'Agent decision could not be validated', 'Agent unavailable after retry']) await expect(page.getByRole('main')).toContainText(label)
    await page.screenshot({ path: `test-results/agent-partial-${width}.png`, fullPage: true })

    control(Object.fromEntries(ids.map(id => [id, { mode: 'research_failed' }])))
    await prepare(`Agent all failed ${width}`)
    const failedId = await submit()
    await expect.poll(async () => (await execution(failedId)).status, { timeout: 30000 }).toBe('failed')
    await page.reload()
    await expect(page.getByRole('region', { name: 'Run summary' })).toContainText('Prediction execution failed')
    await expect(page.getByRole('button', { name: 'Settle completed games', exact: true })).toBeDisabled()
    const failed = inspect(failedId)
    expect(failed.bets).toEqual([])
    expect(failed.run).toMatchObject({ starting_bankroll: '1.00', total_profit: null, roi: null, final_bankroll: null, status: 'open' })
    const failedProgress = await execution(failedId)
    expect(failedProgress.completed_games).toBe(4)
    expect(failedProgress.games.every(g => g.state === 'skipped' && g.attempts === 2)).toBe(true)
    const failedResponse = await request.get(`${base}/api/runs/${failedId}`)
    expect(failedResponse.ok()).toBe(true)
    expect((await failedResponse.json()).skipped_games.map((g: { reason: string }) => g.reason)).toEqual(Array(4).fill('research_failed'))

    // Change quotes at both research boundaries. The second commit must skip
    // rather than silently use stale odds or exceed the two-attempt budget.
    control(Object.fromEntries(ids.map(id => [id, { hold_attempt: 1 }])))
    await prepare(`Agent quote changes ${width}`)
    const quoteId = await submit()
    await expect.poll(async () => (await execution(quoteId)).games.some(g => g.state === 'analysing')).toBe(true)
    fixture('--quote-run', quoteId)
    control(Object.fromEntries(ids.map(id => [id, { hold_attempt: 2 }])))
    await expect.poll(async () => (await execution(quoteId)).games.some(g => g.attempts === 2), { timeout: 20000 }).toBe(true)
    fixture('--quote-run', quoteId)
    control({})
    const quote = await completedRun(request, base, quoteId)
    expect(quote.skipped_games.some(g => g.reason === 'quote_changed')).toBe(true)
    expect(quote.bets).toHaveLength(3)
    expect(quote.bets.every(b => b.price === '1.9700')).toBe(true)
    expect((await execution(quoteId)).games.every(g => g.attempts <= 2)).toBe(true)
    expect(new Set(quote.bets.map(b => b.game_id)).size).toBe(quote.bets.length)
    await page.reload()
    await expect(page.getByRole('main')).toContainText('Saved quote changed')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/agent-quotes-${width}.png`, fullPage: true })
  } finally {
    // Always let fixture shutdown release leases and drop its database.
    if (child.exitCode === null) {
      const exited = new Promise<void>(done => child.once('exit', () => done()))
      child.kill('SIGTERM')
      await exited
    }
    expect(existsSync(metadata), logs).toBe(false)
    rmSync(directory, { recursive: true, force: true })
  }
})
