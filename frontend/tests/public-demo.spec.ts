import { expect, test } from '@playwright/test'

test('public demo shows synthetic audit data without write controls', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Read-only demo', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Recent stock movements' })).toBeVisible()
  await expect(page.getByText('Synthetic warehouse data.', { exact: false })).toBeVisible()
  for (const label of ['Sign in', 'New order', 'Create order', 'Receive stock', 'Replenishment']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toHaveCount(0)
  }
  const screenshot = process.env.STOCKFLOW_DEMO_SCREENSHOT
  if (screenshot) await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' })

  await page.getByRole('navigation').getByRole('button', { name: 'Orders', exact: true }).click()
  await expect(page.getByText('Demo customer 01', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Fulfill', exact: true })).toHaveCount(0)
  await page.getByRole('navigation').getByRole('button', { name: 'Stock movements' }).click()
  await expect(page.getByRole('table')).toBeVisible()
  await page.getByRole('navigation').getByRole('button', { name: 'Reconciliation' }).click()
  await expect(page.getByText('All inventory balances match the ledger.')).toBeVisible()
  const denied = await page.request.post('/api/orders', { data: {} })
  expect(denied.status()).toBe(403)
})

test('public demo explains an unavailable or waking API', async ({ page }) => {
  await page.route('**/api/products?*', route => route.fulfill({ status: 503, body: 'Waking up' }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('still waking up')
  await expect(page.getByRole('button', { name: 'Refresh data' })).toBeEnabled()
})
