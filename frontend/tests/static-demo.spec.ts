import { expect, test } from '@playwright/test'

test('static snapshot displays all audit screens with no backend requests', async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin
  const apiCalls: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.origin !== origin || url.pathname.startsWith('/api/')) apiCalls.push(url.pathname)
  })
  await page.goto('/')
  await expect(page.getByText('Static demo', { exact: true })).toBeVisible()
  await expect(page.getByText('Synthetic snapshot.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Recent stock movements' })).toBeVisible()
  for (const [screen, visible] of [
    ['Products', 'Grip Work Gloves'], ['Inventory', 'Central warehouse'],
    ['Orders', 'Demo customer 01'], ['Stock movements', 'Reservation'],
    ['Reconciliation', 'All inventory balances match the ledger.'],
  ]) {
    await page.getByRole('navigation').getByRole('button', { name: screen, exact: true }).click()
    await expect(page.getByText(visible, { exact: false }).first()).toBeVisible()
  }
  for (const name of ['Sign in', 'New order', 'Refresh data', 'Create order']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  expect(apiCalls).toEqual([])
})
