import { expect, test, type Page } from '@playwright/test'

async function signIn(page: Page, username: string) {
  await page.getByRole('button', { name: 'Sign in' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Username').fill(username)
  await dialog.getByLabel('Password').fill(process.env.STOCKFLOW_E2E_PASSWORD!)
  await dialog.getByRole('button', { name: 'Sign in' }).click()
  await expect(dialog).toBeHidden()
}

test('administrator reserves and fulfills stock through the dashboard', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Warehouse overview' })).toBeVisible()
  await signIn(page, 'admin')

  await page.getByRole('button', { name: 'Create order', exact: true }).click()
  await page.getByLabel('Customer reference').fill('browser-smoke')
  await page.getByLabel('Warehouse', { exact: true }).selectOption({ label: 'Central warehouse' })
  await page.getByLabel('Product 1', { exact: true }).selectOption({ label: 'Work gloves (E2E-GLOVE)' })
  await page.getByLabel('Quantity 1').fill('7')
  await page.getByRole('button', { name: 'Reserve stock' }).click()
  await expect(page.getByRole('alert')).toHaveText('Insufficient available stock')
  await page.getByLabel('Quantity 1').fill('2')
  await page.getByRole('button', { name: 'Reserve stock' }).click()

  const order = page.getByRole('row', { name: /browser-smoke/ })
  await expect(order.getByText('Reserved', { exact: true })).toBeVisible()
  await order.getByRole('button', { name: 'Fulfill' }).click()
  await expect(order.getByText('Fulfilled', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Stock movements', exact: true }).click()
  await expect(page.getByText('Fulfillment', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Reconciliation', exact: true }).click()
  await expect(page.getByText('All inventory balances match the ledger.')).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create order', exact: true })).toHaveCount(0)
})

test('guest can browse inventory on mobile and cannot access order actions', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await signIn(page, 'guest')
  await expect(page.getByRole('button', { name: 'Create order', exact: true })).toHaveCount(0)
  await page.getByRole('navigation').getByRole('button', { name: 'Inventory', exact: true }).click()
  await expect(page.getByText('Work gloves')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Receive stock' })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
