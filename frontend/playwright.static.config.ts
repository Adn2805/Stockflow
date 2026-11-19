import { defineConfig } from '@playwright/test'

const liveOrigin = process.env.STOCKFLOW_STATIC_ORIGIN

export default defineConfig({
  testDir: './tests',
  testMatch: '**/static-demo.spec.ts',
  use: { baseURL: liveOrigin || 'http://127.0.0.1:55174', channel: process.env.STOCKFLOW_BROWSER || undefined },
  webServer: liveOrigin ? undefined : {
    command: 'npm run preview -- --host 127.0.0.1 --port 55174 --strictPort',
    url: 'http://127.0.0.1:55174',
  },
})
