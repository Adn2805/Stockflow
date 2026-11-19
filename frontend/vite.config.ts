import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, process.cwd(), '').STOCKFLOW_API_TARGET || 'http://127.0.0.1:8000'
  const proxy = { '/api': { target, rewrite: (path: string) => path.replace(/^\/api/, '') } }
  return {
    plugins: [react(), tailwind()],
    build: { assetsDir: mode === 'static' ? '' : 'assets' },
    server: { proxy },
    preview: { proxy },
  }
})
