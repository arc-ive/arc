// Smoke #1: login journey through the real UI (no stored state here).
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'

test.use({ storageState: { cookies: [], origins: [] } })

test('login page loads with required fields', async ({ page }) => {
  const health = watchBrowserHealth(page)

  await page.goto('/login')

  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in with Google' })).toBeVisible()
  await expect(page.getByText('Development Login')).toBeVisible()

  await expectHealthyBrowser(health)
})

test('invalid login is rejected without a session', async ({ request }) => {
  const apiUrl = process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'

  const response = await request.post(`${apiUrl}/internal/dev/auth/login`, {
    data: { user_id: 'no-such-user' },
  })

  expect(response.status()).toBe(403)
})

test('reference user login redirects to the app', async ({ page }) => {
  const health = watchBrowserHealth(page)

  await page.goto('/login')
  await page.getByRole('combobox').selectOption({ index: 1 })
  await page.getByRole('button', { name: 'Sign in as reference user' }).click()

  await expect(page).toHaveURL(/\/app(\/|$)/, { timeout: 15000 })
  await expectHealthyBrowser(health)
})
