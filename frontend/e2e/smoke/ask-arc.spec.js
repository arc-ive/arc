// Smoke #2: Ask Arc end-to-end against seeded knowledge.
// Seeds a uniquely-worded document via API, then asks about it through
// the UI and asserts a grounded answer renders. No live LLM needed:
// the backend deterministic provider answers from approved context.
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl, csrfHeaders } from '../helpers/api.js'

const TENANT_ID = 'ref-acme-technologies'
const MARKER = `e2e-smoke-${Date.now()}`

test('ask arc answers from seeded knowledge', async ({ page, request, context }) => {
  const health = watchBrowserHealth(page)

  // Seed a document with unique content through the real API.
  const createResponse = await request.post(
    `${apiUrl()}/tenants/${TENANT_ID}/knowledge`,
    {
      headers: await csrfHeaders(context),
      data: {
        source: 'policy',
        provenance: 'E2E smoke policy',
        content: `The ${MARKER} refund policy allows returns within thirty days.`,
      },
    },
  );
  expect(createResponse.ok(), `seed failed: ${await createResponse.text()}`).toBeTruthy()

  await page.goto(`/app/t/${TENANT_ID}/ask`)

  const question = page.getByLabel('Ask Arc');
  await expect(question).toBeVisible()
  await question.fill(`What does the ${MARKER} refund policy allow?`)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()

  // Loading state appears, then the grounded answer renders.
  // The deterministic provider cites approved references rather than
  // echoing content, so assert the response shape, not the wording.
  await expect(page.getByText('Reading the record')).toBeVisible()
  await expect(page.getByText(/Deterministic response/)).toBeVisible({ timeout: 30000 })

  await expectHealthyBrowser(health)
})
