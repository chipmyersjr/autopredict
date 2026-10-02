import { defineConfig } from '@playwright/test'

export default defineConfig({
  timeout: 15000,
  testDir: './tests',
  fullyParallel: true,
  use: {
    baseURL: 'http://127.0.0.1:5175',
    timezoneId: 'America/Los_Angeles',
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome',
  },
  webServer: {
    command: 'npm run dev -- --port 5175 --strictPort',
    url: 'http://127.0.0.1:5175',
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: process.env.TEST_API_BASE_URL ?? 'http://127.0.0.1:8001' },
  },
})
