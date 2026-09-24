// Phase 2: tenant isolation at browser + API level.
// Principal: ref-acme-technologies-company-admin (member of Acme only).
// Foreign tenant: ref-nova-systems (no membership, never granted).
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl } from '../helpers/api.js'

const OWN_TENANT = 'ref-acme-technologies'
const FOREIGN_TENANT = 'ref-nova-systems'

test('foreign workspace URL is blocked, own workspace loads', async ({ page }) => {
  const health = watchBrowserHealth(page)

  await page.goto(`/app/t/${FOREIGN_TENANT}/skills`)
  await expect(
    page.getByRole('heading', { name: "You don't have access to this workspace" }),
  ).toBeVisible()

  await page.goto(`/app/t/${OWN_TENANT}/skills`)
  await expect(page.getByRole('heading', { name: 'Skills' })).toBeVisible()

  await expectHealthyBrowser(health)
})

test('foreign tenant API is denied and reveals nothing', async ({ request }) => {
  const ownSkills = await request.get(`${apiUrl()}/tenants/${OWN_TENANT}/skills`)
  expect(ownSkills.ok(), 'own skills list must succeed').toBeTruthy()

  const foreignSkills = await request.get(`${apiUrl()}/tenants/${FOREIGN_TENANT}/skills`)
  expect(foreignSkills.status()).toBe(403)

  const foreignDoc = await request.get(
    `${apiUrl()}/tenants/${FOREIGN_TENANT}/knowledge/nonexistent-doc`,
  )
  expect([403, 404]).toContain(foreignDoc.status())
})
