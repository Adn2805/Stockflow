import { defineConfig } from '@playwright/test'
import config from './playwright.config'

process.env.STOCKFLOW_E2E_DEMO = 'true'

export default defineConfig({
  ...config,
  testIgnore: [],
  testMatch: '**/public-demo.spec.ts',
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 55173 --strictPort',
    url: 'http://127.0.0.1:55173',
    env: {
      STOCKFLOW_API_TARGET: 'http://127.0.0.1:58081',
      VITE_PUBLIC_DEMO: 'true',
    },
  },
})
