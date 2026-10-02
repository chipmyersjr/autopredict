import { defineConfig } from '@playwright/test'

const port = process.env.TEST_FRONTEND_PORT ?? '5175'

export default defineConfig({
  timeout: 15000,
  testDir: './tests',
  fullyParallel: true,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    timezoneId: 'America/Los_Angeles',
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome',
  },
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8001' },
  },
})
