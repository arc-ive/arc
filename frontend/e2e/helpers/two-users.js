// Two-principal helper for four-eyes workflows (e.g. approvals).
// Creates isolated browser contexts from stored auth states so the
// requester and the decider never share cookies or storage.
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const authDir = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '.auth',
);

export async function requesterContext(browser) {
  return browser.newContext({ storageState: path.join(authDir, 'ops.json') })
}

export async function deciderContext(browser) {
  return browser.newContext({ storageState: path.join(authDir, 'user.json') })
}

export async function employeeContext(browser) {
  return browser.newContext({ storageState: path.join(authDir, 'employee.json') })
}
