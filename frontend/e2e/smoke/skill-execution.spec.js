// Smoke #3: deterministic skill execution end-to-end:
// Browser → Frontend → HTTP API → SkillExecutionService → result → UI.
// Creates a minimal skill via API (no inputs/preconditions), executes it
// through the Execute dialog, and asserts the user-visible outcome.
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl, csrfHeaders } from '../helpers/api.js'

const TENANT_ID = 'ref-acme-technologies'
// Note: the skill name is PII-sanitized on render (e.g. words replaced),
// so UI locators below match the numeric suffix, which survives verbatim.
const SKILL_SUFFIX = `${Date.now()}`
const SKILL_NAME = `E2E Smoke Skill ${SKILL_SUFFIX}`

test('skill executes end to end with visible result', async ({ page, request, context }) => {
  const health = watchBrowserHealth(page)
  const headers = await csrfHeaders(context)

  const createResponse = await request.post(`${apiUrl()}/tenants/${TENANT_ID}/skills`, {
    headers,
    data: {
      name: SKILL_NAME,
      purpose: 'E2E smoke execution',
      allowed_tools: ['check_service_health'],
    },
  })
  expect(createResponse.ok(), `skill create failed: ${await createResponse.text()}`).toBeTruthy()
  const skillId = (await createResponse.json()).id
  expect(skillId, 'skill id returned').toBeTruthy()

  await page.goto(`/app/t/${TENANT_ID}/skills`)

  // Open the Execute dialog for our skill row (per-skill button title;
  // matched on the numeric suffix since names are PII-redacted in the UI).
  await page.getByTitle(new RegExp(`Execute.*${SKILL_SUFFIX}`)).click()

  // Fill tool calls and submit.
  const toolCalls = page.getByPlaceholder(/"tool_name"/)
  await expect(toolCalls).toBeVisible()
  await toolCalls.clear()
  await toolCalls.fill('[{"tool_name": "check_service_health", "input": {}}]')
  await page.getByRole('button', { name: 'Execute', exact: true }).click()

  // The user-visible terminal outcome.
  await expect(page.getByText('Succeeded')).toBeVisible({ timeout: 30000 })

  await expectHealthyBrowser(health)
})
