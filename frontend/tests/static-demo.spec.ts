import { expect, test } from '@playwright/test'

const legacyDeployment = Boolean(process.env.STOCKFLOW_STATIC_ORIGIN) && process.env.STOCKFLOW_REQUIRE_ENGINEERING !== '1'

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
    ['Orders', 'Demo customer'], ['Stock movements', 'Reservation'],
    ['Reconciliation', 'All inventory balances match the ledger.'],
  ]) {
    await page.getByRole('navigation').getByRole('button', { name: screen, exact: true }).click()
    await expect(page.getByText(visible, { exact: false }).first()).toBeVisible()
  }
  for (const name of ['Sign in', 'New order', 'Refresh data', 'Create order', 'Replenishment']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  expect(apiCalls).toEqual([])
})

test('expanded local dataset paginates orders and stock movements', async ({ page }) => {
  test.skip(legacyDeployment, 'The expanded snapshot is pending publication.')
  await page.goto('/')
  const navigation = page.getByRole('navigation')
  await navigation.getByRole('button', { name: 'Orders', exact: true }).click()
  await expect(page.getByText('Demo customer 320', { exact: false })).toBeVisible()
  await expect(page.getByText('of 320', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Next page' }).click()
  await expect(page.getByText('Demo customer 310', { exact: false })).toBeVisible()
  await navigation.getByRole('button', { name: 'Stock movements' }).click()
  await expect(page.getByRole('button', { name: 'Next page' })).toBeEnabled()
})

test('engineering overview demonstrates benchmark, reorder math and outbox without network calls', async ({ page, baseURL }) => {
  test.skip(legacyDeployment, 'The engineering overview is pending publication.')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Warehouse operations under load' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Recent stock movements' })).toBeVisible()
  await page.getByRole('link', { name: 'Explore warehouse data' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Warehouse overview' })).toBeFocused()
  await expect(page.getByText('Recorded PostgreSQL benchmark.', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Raw benchmark results' })).toHaveAttribute(
    'href', /^https:\/\/github\.com\/Adn2805\/Stockflow\/blob\/[a-f0-9]{40}\/benchmarks\/results\/concurrency\.json$/,
  )
  const requests: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.origin !== new URL(baseURL!).origin || url.pathname.startsWith('/api/')) requests.push(request.url())
  })
  const results = page.locator('.simulation-results dd')
  await expect(results).toHaveText(['100', '400', '0'])
  await page.getByRole('button', { name: 'Reset replay' }).click()
  await page.getByRole('slider', { name: 'Requests replayed' }).press('ArrowRight')
  await expect(results).toHaveText(['1', '0', '0'])
  await page.getByRole('button', { name: 'Replay all 500' }).click()
  await expect(results).toHaveText(['100', '400', '0'])

  await page.getByRole('button', { name: /Automated replenishment/ }).click()
  const reorderStatus = page.getByRole('region', { name: 'Automated replenishment' }).getByRole('status')
  await expect(page.getByText('Browser simulation. Adjust sample quantities', { exact: false })).toBeVisible()
  await expect(reorderStatus).toContainText('108 units')
  await page.getByLabel('Available units').fill('100')
  await expect(reorderStatus).toContainText('No recommendation')
  await page.getByLabel('Reorder threshold').fill('160')
  await expect(reorderStatus).toContainText('set the target above the threshold')

  await page.getByRole('button', { name: /Reliable Telegram alerts/ }).click()
  const telegramStatus = page.getByRole('region', { name: 'Reliable Telegram alerts' }).getByRole('status')
  await page.getByRole('button', { name: 'Process the outbox' }).click()
  await expect(telegramStatus).toContainText('Pending')
  await page.getByRole('button', { name: 'Record delivery' }).click()
  await expect(telegramStatus).toContainText('Sent')
  await expect(page.getByText('This demo sends no messages.', { exact: false })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  expect(requests).toEqual([])
})
