import { expect } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import type { RunResult } from '../../src/api/runs'

/** Navigate deliberately; default eligible selections remain untouched. */
export async function finalize(page: Page, strategy = 'Random Strategy') {
  await page.getByRole('radio', { name: strategy }).check()
  await page.getByRole('button', { name: 'Continue to Games' }).click()
  const review = page.getByRole('button', { name: 'Review updated games' })
  if (await review.isVisible()) await review.click()
  await page.getByRole('button', { name: 'Continue to Finalize' }).click()
}

/** Legacy snapshot/settlement regressions now wait for durable worker output. */
export async function completedRun(request: APIRequestContext, base: string, id: string): Promise<RunResult> {
  await expect.poll(async () => {
    const response = await request.get(`${base}/api/runs/${id}/execution`)
    expect(response.ok()).toBe(true)
    return (await response.json()).status
  }, { timeout: 30000 }).toBe('completed')
  const runResponse = await request.get(`${base}/api/runs/${id}`)
  const betsResponse = await request.get(`${base}/api/runs/${id}/bets`)
  expect(runResponse.ok()).toBe(true)
  expect(betsResponse.ok()).toBe(true)
  const run = await runResponse.json()
  return { run, bets: await betsResponse.json(), skipped_games: run.skipped_games }
}
