// Shared browser-health listeners for E2E specs.
//
// Attach at the start of a test, assert at the end. Filters the known
// harmless noise (React act warnings in dev, favicon 404s); everything
// else — page exceptions, console errors, unexpected 4xx/5xx — fails.
import { expect } from '@playwright/test'

const IGNORED_CONSOLE = [
  /favicon\.ico/,
  /Download the React DevTools/,
  // Mirrors the badResponses filter below: 401/403 resource loads are
  // auth boundaries the app exercises deliberately (e.g. session probes
  // on public pages). Tests assert those boundaries directly.
  /Failed to load resource:.*status of 40[13]/,
]

const IGNORED_URLS = [/\/health$/, /favicon\.ico/]

export function watchBrowserHealth(page) {
  const state = { pageErrors: [], consoleErrors: [], badResponses: [] }

  page.on('pageerror', (error) => state.pageErrors.push(error))

  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const text = message.text()
    if (IGNORED_CONSOLE.some((pattern) => pattern.test(text))) return
    state.consoleErrors.push(text)
  })

  page.on('response', (response) => {
    const status = response.status()
    if (status < 400) return
    const url = response.url()
    if (IGNORED_URLS.some((pattern) => pattern.test(url))) return
    // Auth boundaries are behavior, not breakage: tests assert them directly.
    if (status === 401 || status === 403) return
    state.badResponses.push(`${status} ${url}`)
  })

  return state
}

export async function expectHealthyBrowser(state) {
  expect(state.pageErrors, `page errors: ${state.pageErrors.join('; ')}`).toEqual([])
  expect(state.consoleErrors, `console errors: ${state.consoleErrors.join('; ')}`).toEqual([])
  expect(state.badResponses, `bad responses: ${state.badResponses.join('; ')}`).toEqual([])
}
