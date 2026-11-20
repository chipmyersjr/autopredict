import { test, expect } from '@playwright/test'
import type { RunExecution, PendingRun } from '../src/api/runs'
import type { Strategy } from '../src/api/strategies'

const runId = '60000000-0000-4000-8000-000000000001'
const gameId = '10000000-0000-4000-8000-000000000001'
const strategy: Strategy = {
  id: '40000000-0000-4000-8000-000000000002', name: 'FootballAnalysisExpert', type: 'agent',
  config: { profile: 'FootballAnalysisExpert' }, description: 'Saved research', is_active: true,
  created_at: '2026-11-19T00:00:00Z', updated_at: '2026-11-19T00:00:00Z',
}
const intent: PendingRun = {
  key: '70000000-0000-4000-8000-000000000001',
  body: { strategy_id: strategy.id, game_ids: [gameId], starting_bankroll: '9999999999.99', stake_per_bet: '0.01', name: 'Agent run' },
}
const execution: RunExecution = {
  run_id: runId, status: 'running', total_games: 6, completed_games: 3,
  predicted_games: 2, skipped_games: 1, retrying_games: 1, queued_games: 1,
  games: [
    { game_id: 'queued', state: 'queued', attempts: 0, skip_reason: null },
    { game_id: 'analysing', state: 'analysing', attempts: 1, skip_reason: null },
    { game_id: 'retrying', state: 'retrying', attempts: 2, skip_reason: null },
    { game_id: 'predicted', state: 'predicted', attempts: 1, skip_reason: null },
    { game_id: 'saved', state: 'bet_created', attempts: 1, skip_reason: null },
    { game_id: 'skipped', state: 'skipped', attempts: 2, skip_reason: 'research_failed' },
  ], message: null,
}
const accepted = {
  run: { id: runId, status: 'open', execution_status: 'queued', execution_started_at: null,
    execution_finished_at: null, starting_bankroll: '9999999999.99', committed_stake: '0.00' },
  bets: [], skipped_games: [],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/games?window=current', r => r.fulfill({ json: [] }))
  await page.route('**/api/strategies', r => r.fulfill({ json: [strategy] }))
  await page.goto('/')
})

test('201 accepts empty Bets; 200 replay preserves exact saved key and body after response loss', async ({ page }) => {
  const requests: { key: string; body: string | null }[] = []
  await page.route('**/api/runs', r => {
    expect(r.request().method()).toBe('POST')
    requests.push({ key: r.request().headers()['idempotency-key'], body: r.request().postData() })
    if (requests.length === 1) return r.abort('failed')
    return r.fulfill({ status: requests.length === 2 ? 201 : 200, json: accepted })
  })
  const values = await page.evaluate(async saved => {
    const path = '/src/api/runs.ts'
    const api = await import(path)
    api.savePending(saved)
    try { await api.createRun(saved, new AbortController().signal) } catch { /* Lost acknowledgment. */ }
    const recovered = api.loadPending()
    const first = await api.createRun(recovered, new AbortController().signal)
    const replay = await api.createRun(api.loadPending(), new AbortController().signal)
    api.clearPending(saved.key)
    return { recovered, first, replay, cleared: api.loadPending() }
  }, intent)
  expect(values).toEqual({ recovered: intent, first: accepted, replay: accepted, cleared: null })
  expect(requests).toHaveLength(3)
  for (const request of requests) expect(request).toEqual({ key: intent.key, body: JSON.stringify(intent.body) })
})

test('progress is an abortable bodyless GET with ordered persisted counters, separate from accounting', async ({ page }) => {
  await page.route('**/api/runs/saved%2Frun/execution', r => {
    expect(r.request().method()).toBe('GET')
    expect(r.request().postData()).toBeNull()
    expect(r.request().headers()['idempotency-key']).toBeUndefined()
    return r.fulfill({ json: execution })
  })
  expect(await page.evaluate(async () => {
    const path = '/src/api/runs.ts'
    return (await import(path)).getRunExecution('saved/run', new AbortController().signal)
  })).toEqual(execution)
})

for (const status of ['queued', 'completed', 'failed'] as const) test(`persisted ${status} execution and nullable safe message survive reads`, async ({ page }) => {
  const progress: RunExecution = {
    run_id: runId, status, total_games: 1, completed_games: status === 'queued' ? 0 : 1,
    predicted_games: status === 'completed' ? 1 : 0, skipped_games: status === 'failed' ? 1 : 0,
    queued_games: status === 'queued' ? 1 : 0, retrying_games: 0,
    games: [{ game_id: gameId, state: status === 'queued' ? 'queued' : status === 'completed' ? 'bet_created' : 'skipped',
      attempts: status === 'queued' ? 0 : status === 'completed' ? 1 : 2,
      skip_reason: status === 'failed' ? 'agent_unavailable' : null }],
    message: status === 'failed' ? 'No predictions could be saved. Review the skipped games.' : null,
  }
  await page.route(`**/api/runs/${runId}/execution`, r => r.fulfill({ json: progress }))
  expect(await page.evaluate(async runId => {
    const path = '/src/api/runs.ts'
    return (await import(path)).getRunExecution(runId, new AbortController().signal)
  }, runId)).toEqual(progress)
})

for (const status of [404, 409, 422, 503, 500]) test(`creation and progress ${status} use bounded safe errors`, async ({ page }) => {
  await page.route('**/api/runs', r => r.fulfill({ status, json: { detail: 'PRIVATE service traceback' } }))
  await page.route(`**/api/runs/${runId}/execution`, r => r.fulfill({ status, json: { detail: 'PRIVATE service traceback' } }))
  const errors = await page.evaluate(async ({ intent, runId }) => {
    const path = '/src/api/runs.ts'
    const api = await import(path)
    const errors = []
    for (const action of [() => api.createRun(intent, new AbortController().signal), () => api.getRunExecution(runId, new AbortController().signal)]) {
      try { await action() } catch (e) {
        const error = e as Error & { status: number; definite: boolean }
        errors.push({ message: error.message, status: error.status, definite: error.definite })
      }
    }
    return errors
  }, { intent, runId })
  expect(errors).toHaveLength(2)
  for (const error of errors) {
    expect(error.status).toBe(status)
    expect(error.definite).toBe(status !== 500)
    expect(error.message).not.toContain('PRIVATE')
  }
  expect(errors[1].message).toMatch(/Run|Progress/)
})

test('inactive strategy and request-key conflicts have readable creation errors', async ({ page }) => {
  for (const detail of ['Strategy inactive', 'Idempotency-Key already used with different input']) {
    await page.route('**/api/runs', r => r.fulfill({ status: 409, json: { detail } }))
    const message = await page.evaluate(async intent => {
      const path = '/src/api/runs.ts'
      try { await (await import(path)).createRun(intent, new AbortController().signal) }
      catch (error) { return (error as Error).message }
    }, intent)
    expect(message).toContain(detail === 'Strategy inactive' ? 'Choose an active strategy' : 'Review Run history')
  }
})

for (const mode of ['abort', 'network', 'timeout', 'invalid-json']) test(`progress ${mode} never claims execution failed or retries creation`, async ({ page }) => {
  const posts: string[] = []
  page.on('request', r => { if (r.method() === 'POST') posts.push(r.url()) })
  await page.route(`**/api/runs/${runId}/execution`, async r => {
    if (mode === 'network') return r.abort('failed')
    if (mode === 'invalid-json') return r.fulfill({ body: '{' })
    await new Promise(resolve => setTimeout(resolve, 100))
    await r.fulfill({ json: execution }).catch(() => {})
  })
  const error = await page.evaluate(async ({ mode, runId }) => {
    const path = '/src/api/runs.ts'
    const api = await import(path), controller = new AbortController()
    const timeout = AbortSignal.timeout
    if (mode === 'timeout') AbortSignal.timeout = () => timeout(10)
    if (mode === 'abort') setTimeout(() => controller.abort(), 10)
    try { await api.getRunExecution(runId, controller.signal) }
    catch (e) { const error = e as Error & { definite?: boolean }; return { name: error.name, message: error.message, definite: error.definite } }
    finally { AbortSignal.timeout = timeout }
  }, { mode, runId })
  if (mode === 'abort') expect(error?.name).toBe('AbortError')
  else {
    expect(error?.definite).toBe(false)
    expect(error?.message).toContain('Run may still be processing')
  }
  expect(posts).toEqual([])
})

test('saved reasoning, nulls, exact quote strings and every skip survive client reads', async ({ page }) => {
  const bets = [null, '<script>plain saved text</script>'].map((reasoning, i) => ({
    id: String(i), reasoning, line: '0.00', price: '1.9876', stake: '0.01', profit: null,
    settlement_home_score: 0, settlement_away_score: null,
  }))
  await page.route(`**/api/runs/${runId}/bets`, r => r.fulfill({ json: bets }))
  const result = await page.evaluate(async runId => {
    const path = '/src/api/runs.ts'
    const api = await import(path)
    return { bets: await api.getRunBets(runId, new AbortController().signal), labels: api.skipReasonLabels }
  }, runId)
  expect(result.bets).toEqual(bets)
  expect(Object.keys(result.labels)).toEqual(['game_not_scheduled', 'kickoff_reached', 'spread_unavailable', 'agent_unavailable', 'research_failed', 'invalid_agent_decision', 'quote_changed'])
  expect(Object.values(result.labels).every(label => typeof label === 'string' && label.length > 0)).toBe(true)
})
