import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  globalSetup: './tests/global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:55173',
    channel: process.env.STOCKFLOW_BROWSER || undefined,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 55173 --strictPort',
    url: 'http://127.0.0.1:55173',
    env: { STOCKFLOW_API_TARGET: 'http://127.0.0.1:58081' },
  },
})
