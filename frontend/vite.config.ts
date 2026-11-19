import { resolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const { STOCKFLOW_API_TARGET } = loadEnv(mode, process.cwd(), 'STOCKFLOW_API_TARGET')
  const { API_PORT = '8000' } = loadEnv(mode, resolve(process.cwd(), '..'), 'API_PORT')
  const target = STOCKFLOW_API_TARGET || 'http://127.0.0.1:' + API_PORT
  const proxy = { '/api': { target, rewrite: (path: string) => path.replace(/^\/api/, '') } }
  return {
    plugins: [react(), tailwind()],
    build: { assetsDir: mode === 'static' ? '' : 'assets' },
    server: { proxy },
    preview: { proxy },
  }
})
