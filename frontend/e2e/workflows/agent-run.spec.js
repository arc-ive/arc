// Phase 3B: agent run → trace end to end.
// Uses the deterministic provider (no script): the run fails closed with
// no_decision and persists a trace. Asserts the terminal outcome, the
// persisted trace with tenant attribution, and zero tool executions.
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl, csrfHeaders } from '../helpers/api.js'

const TENANT_ID = 'ref-acme-technologies'
const GOAL = `e2e agent goal ${Date.now()}`

test('agent run fails closed with persisted trace', async ({ page, request, context }) => {
  const health = watchBrowserHealth(page)
  const headers = await csrfHeaders(context)

  await page.goto(`/app/t/${TENANT_ID}/agents`)

  const goal = page.getByLabel(/goal/i)
  await expect(goal).toBeVisible()
  await goal.fill(GOAL)

  const submitted = page.waitForResponse(
    (response) =>
      response.url().includes('/agent/runs') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /start agent run/i }).click()
  const runBody = await (await submitted).json()
  expect(runBody.status).toBe('failed')

  // Terminal outcome visible with tenant attribution.
  await expect(page.getByText(GOAL)).toBeVisible({ timeout: 15000 })

  // Trace persisted: same run id, same tenant, no tool activity.
  const traces = await request.get(`${apiUrl()}/tenants/${TENANT_ID}/observability/agent-runs`, {
    headers,
  })
  expect(traces.ok(), `trace list failed: ${await traces.text()}`).toBeTruthy()
  const items = (await traces.json()).items
  const trace = items.find((item) => item.id === runBody.id)
  expect(trace, 'run trace persisted').toBeTruthy()
  expect(trace.tenant_id).toBe(TENANT_ID)
  expect(trace.goal).toBe(GOAL)
  expect(trace.status).toBe('failed')
  expect(trace.steps, 'no skill executed on fail-closed run').toEqual([])

  await expectHealthyBrowser(health)
})
