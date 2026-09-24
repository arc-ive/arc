// Global auth setup: authenticate once via the dev reference login API
// and persist browser state for all specs. Runs before the chromium
// project (see playwright.config.js dependencies).
//
// Requires APP_ENV=development backend with seeded reference data:
//   POST {API}/internal/dev/auth/login { user_id: ref-acme-technologies-company-admin }
// No real credentials exist anywhere in this flow.
import { test as setup, expect } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const authDir = path.dirname(fileURLToPath(import.meta.url))

async function loginAs(request, userId, filename) {
  const apiUrl = process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'

  const response = await request.post(`${apiUrl}/internal/dev/auth/login`, {
    data: { user_id: userId },
  })
  expect(response.ok(), `dev login failed: ${response.status()} ${await response.text()}`).toBeTruthy()

  await request.storageState({ path: path.join(authDir, '.auth', filename) })
}

setup('authenticate as company admin', async ({ request }) => {
  await loginAs(request, 'ref-acme-technologies-company-admin', 'user.json')
})

setup('authenticate as operations user', async ({ request }) => {
  await loginAs(request, 'ref-acme-technologies-ops-user', 'ops.json')
})

setup('authenticate as employee', async ({ request }) => {
  await loginAs(request, 'ref-acme-technologies-employee-1', 'employee.json')
})
