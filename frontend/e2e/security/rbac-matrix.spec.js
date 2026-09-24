// Phase 3C: high-risk RBAC combinations at UI + API level.
// Roles: employee (knowledge:read + agent:execute only), ops-user
// (execute, no create/decide), company-admin (broad tenant rights).
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl, csrfHeaders } from '../helpers/api.js'
import { employeeContext, requesterContext } from '../helpers/two-users.js'

const TENANT_ID = 'ref-acme-technologies'

test('employee sees no skill execution surface and cannot execute via API', async ({
  browser,
}) => {
  const employee = await employeeContext(browser)
  const page = await employee.newPage()
  const health = watchBrowserHealth(page)

  // UI: skills route requires skill:read → redirected away.
  await page.goto(`/app/t/${TENANT_ID}/skills`)
  await expect(page).not.toHaveURL(new RegExp(`/app/t/${TENANT_ID}/skills$`), {
    timeout: 15000,
  })

  // API: direct execute attempt denied (with CSRF header so the 403
  // comes from RBAC, not the CSRF middleware).
  const denied = await employee.request.post(
    `${apiUrl()}/tenants/${TENANT_ID}/skills/any-skill/execute`,
    {
      headers: await csrfHeaders(employee),
      data: { tool_calls: [], satisfied_preconditions: [] },
    },
  )
  expect(denied.status()).toBe(403)

  await expectHealthyBrowser(health)
  await employee.close()
})

test('ops user sees execute but no create surface; create denied via API', async ({
  browser,
}) => {
  const ops = await requesterContext(browser)
  const page = await ops.newPage()
  const health = watchBrowserHealth(page)

  await page.goto(`/app/t/${TENANT_ID}/skills`)
  await expect(page.getByRole('heading', { name: 'Skills' })).toBeVisible({ timeout: 15000 })
  await expect(page.getByRole('link', { name: 'New Skill' })).toHaveCount(0)

  // With CSRF header so the 403 comes from RBAC, not the CSRF middleware.
  const denied = await ops.request.post(`${apiUrl()}/tenants/${TENANT_ID}/skills`, {
    headers: await csrfHeaders(ops),
    data: { name: 'x', purpose: 'y', allowed_tools: [] },
  })
  expect(denied.status()).toBe(403)

  await expectHealthyBrowser(health)
  await ops.close()
})
