import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { randomBytes, randomUUID } from 'node:crypto'
import { once } from 'node:events'
import { fileURLToPath } from 'node:url'
import { setTimeout } from 'node:timers/promises'

export default async function setup() {
  const raw = process.env.TEST_DATABASE_URL
  if (!raw) throw new Error('Set TEST_DATABASE_URL to run browser tests.')
  const schema = 'stockflow_e2e_' + randomUUID().replaceAll('-', '')
  const database = new URL(raw)
  database.searchParams.set('options', '-csearch_path=' + schema)
  const python = process.env.STOCKFLOW_TEST_PYTHON || 'python'
  const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
  process.env.STOCKFLOW_E2E_PASSWORD = randomBytes(24).toString('hex')
  const environment = { ...process.env, PYTHONPATH: '.', DATABASE_URL: database.toString(), WRITE_TOKEN: '' }

  function schemaCommand(action: 'prepare' | 'cleanup') {
    const result = spawnSync(python, ['tests/e2e_database.py', action, schema], {
      cwd: backend, env: environment, stdio: 'inherit',
    })
    if (result.error) throw result.error
    if (result.status !== 0) throw new Error('Browser test database ' + action + ' failed.')
  }

  let api: ChildProcess | undefined
  async function cleanup() {
    try {
      if (api?.pid && api.exitCode === null && api.signalCode === null) {
        const exited = once(api, 'exit')
        api.kill()
        await exited
      }
    } finally { schemaCommand('cleanup') }
  }
  try {
    schemaCommand('prepare')
    api = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '58081'], {
      cwd: backend, env: environment, stdio: 'inherit',
    })
    await once(api, 'spawn')
    for (let attempt = 0; attempt < 100; attempt++) {
      if (api.exitCode !== null) throw new Error('Browser test API stopped during startup.')
      const health = await fetch('http://127.0.0.1:58081/health', { signal: AbortSignal.timeout(1000) }).catch(() => null)
      if (health?.ok) return cleanup
      await setTimeout(200)
    }
    throw new Error('Browser test API did not become ready.')
  } catch (error) {
    await cleanup()
    throw error
  }
}
