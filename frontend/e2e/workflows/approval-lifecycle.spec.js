// Phase 3A: approval lifecycle end to end.
// Requester (ops-user) triggers a gated tool via the Skills UI → pending
// approval → decider (company-admin) approves in the approvals queue →
// requester resumes via API → executes → replay refused. Reject path too.
// Four-eyes is real: requester and decider are different principals in
// isolated browser contexts.
import { test, expect } from '@playwright/test'
import { watchBrowserHealth, expectHealthyBrowser } from '../helpers/browser-health.js'
import { apiUrl, csrfHeaders } from '../helpers/api.js'
import { requesterContext, deciderContext } from '../helpers/two-users.js'

const TENANT_ID = 'ref-acme-technologies'
const STAMP = `${Date.now()}`
const JUSTIFICATION = `e2e approval ${STAMP}`

async function createGatedSkill(api, headers) {
  // Created as company-admin: ops-user holds skill:execute but not
  // skill:create, mirroring the real separation of duties.
  const response = await api.post(`${apiUrl()}/tenants/${TENANT_ID}/skills`, {
    headers,
    data: {
      name: `E2E Approval Skill ${STAMP}`,
      purpose: 'E2E approval lifecycle',
      allowed_tools: ['grant_temporary_access'],
    },
  })
  expect(response.ok(), `skill create failed: ${await response.text()}`).toBeTruthy()
  return (await response.json()).id
}

async function triggerApproval(page, skillId) {
  await page.goto(`/app/t/${TENANT_ID}/skills`)
  await page.getByTitle(new RegExp(`Execute.*${STAMP}`)).click()
  const toolCalls = page.getByPlaceholder(/"tool_name"/)
  await expect(toolCalls).toBeVisible()
  await toolCalls.clear()
  await toolCalls.fill(
    `[{"tool_name": "grant_temporary_access", "input": {"justification": "${JUSTIFICATION}"}}]`,
  )
  const submitted = page.waitForResponse(
    (response) =>
      response.url().includes(`/skills/${skillId}/execute`) && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Execute', exact: true }).click()
  const result = await (await submitted).json()
  expect(result.status).toBe('approval_required')
  expect(result.approval_id, 'approval id returned').toBeTruthy()
  return result.approval_id
}

test('approve → resume executes → replay refused; reject path refused', async ({ browser }) => {
  const requester = await requesterContext(browser)
  const decider = await deciderContext(browser)
  const requesterPage = await requester.newPage()
  const deciderPage = await decider.newPage()
  const health = watchBrowserHealth(requesterPage)

  const requesterApi = requester.request
  const deciderApi = decider.request
  const headers = await csrfHeaders(requester)
  const deciderHeaders = await csrfHeaders(decider)
  const skillId = await createGatedSkill(deciderApi, deciderHeaders)

  // 1. Requester triggers gated tool through the real UI.
  const approvalId = await triggerApproval(requesterPage, skillId)

  // 2. Decider sees the pending approval with its metadata.
  await deciderPage.goto(`/app/t/${TENANT_ID}/approvals`)
  const row = deciderPage.locator('li', { hasText: JUSTIFICATION })
  await expect(row).toBeVisible({ timeout: 15000 })
  await expect(row.getByText('Grant temporary access')).toBeVisible()

  // 3. Decider approves; decision column vanishes, status badge flips.
  await row.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(row.getByRole('button', { name: 'Approve', exact: true })).toBeHidden({
    timeout: 15000,
  })
  await expect(row.getByText('approved', { exact: true })).toBeVisible()

  // 4. Requester resumes via API → executes.
  const resume = await requesterApi.post(
    `${apiUrl()}/tenants/${TENANT_ID}/skills/${skillId}/resume`,
    {
      headers,
      data: {
        approval_id: approvalId,
        tool_calls: [
          {
            tool_name: 'grant_temporary_access',
            input: { justification: JUSTIFICATION },
          },
        ],
        resume_from_step: 0,
        previous_steps: [],
        satisfied_preconditions: [],
      },
    },
  )
  expect(resume.ok(), `resume failed: ${await resume.text()}`).toBeTruthy()
  expect((await resume.json()).status).toBe('succeeded')

  // 5. Replay of the consumed approval is refused with zero re-execution.
  const replay = await requesterApi.post(
    `${apiUrl()}/tenants/${TENANT_ID}/skills/${skillId}/resume`,
    {
      headers,
      data: {
        approval_id: approvalId,
        tool_calls: [
          {
            tool_name: 'grant_temporary_access',
            input: { justification: JUSTIFICATION },
          },
        ],
        resume_from_step: 0,
        previous_steps: [],
        satisfied_preconditions: [],
      },
    },
  )
  expect(replay.ok(), `replay call failed: ${await replay.text()}`).toBeTruthy()
  expect((await replay.json()).status).toBe('failed')

  // 6. Reject path: second approval, decider rejects, resume refused.
  const justification2 = `e2e reject ${STAMP}`
  const trigger2 = await requesterApi.post(
    `${apiUrl()}/tenants/${TENANT_ID}/skills/${skillId}/execute`,
    {
      headers,
      data: {
        tool_calls: [
          { tool_name: 'grant_temporary_access', input: { justification: justification2 } },
        ],
        satisfied_preconditions: [],
      },
    },
  )
  const approvalId2 = (await trigger2.json()).approval_id
  expect(approvalId2, 'second approval id').toBeTruthy()

  await deciderPage.goto(`/app/t/${TENANT_ID}/approvals`)
  const row2 = deciderPage.locator('li', { hasText: justification2 })
  await expect(row2).toBeVisible({ timeout: 15000 })
  await row2.getByRole('button', { name: 'Reject', exact: true }).click()
  await expect(row2.getByRole('button', { name: 'Reject', exact: true })).toBeHidden({
    timeout: 15000,
  })
  await expect(row2.getByText('rejected', { exact: true })).toBeVisible()

  const resumeRejected = await requesterApi.post(
    `${apiUrl()}/tenants/${TENANT_ID}/skills/${skillId}/resume`,
    {
      headers,
      data: {
        approval_id: approvalId2,
        tool_calls: [
          { tool_name: 'grant_temporary_access', input: { justification: justification2 } },
        ],
        resume_from_step: 0,
        previous_steps: [],
        satisfied_preconditions: [],
      },
    },
  )
  expect((await resumeRejected.json()).status).toBe('failed')

  await expectHealthyBrowser(health)
  await requester.close()
  await decider.close()
})
