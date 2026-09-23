import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import * as token from './token.js'

const SRC = dirname(dirname(fileURLToPath(import.meta.url)))

/**
 * PR-2 replaced this file's previous subject.
 *
 * It used to cover Demo Mode: `isDemoMode`, `enterDemoMode`, `exitDemoMode`
 * and a `clearAuthState` that removed the demo flag. Demo Mode is gone —
 * it had no UI entry point (`enterDemo` was exported and never called), was
 * referenced by no V2 or product document, and existed mainly as two
 * fail-open escape hatches in the route guards:
 *
 *     if (isEmployee && !isDemo)                 // RequireWorkspaceRole
 *     if (!isPlatformAdministrator && !isDemo)   // RequirePlatformAdmin
 *
 * Those tests are not deleted silently: they are replaced with assertions
 * that the behaviour stays gone, so a reintroduction has to be deliberate.
 */

describe('client-side auth state', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('exposes no demo-mode API', () => {
    expect(token.isDemoMode).toBeUndefined()
    expect(token.enterDemoMode).toBeUndefined()
    expect(token.exitDemoMode).toBeUndefined()
  })

  it('clearAuthState runs without touching browser storage', () => {
    sessionStorage.setItem('unrelated', 'keep-me')
    expect(() => token.clearAuthState()).not.toThrow()
    // The session lives in an HttpOnly cookie; the client holds no
    // credential of its own, so sign-out has nothing of its own to clear.
    expect(sessionStorage.getItem('unrelated')).toBe('keep-me')
  })

  it('no longer persists a demo flag anywhere', () => {
    token.clearAuthState()
    expect(sessionStorage.getItem('arc.demoMode')).toBeNull()
    expect(localStorage.getItem('arc.demoMode')).toBeNull()
  })
})

describe('Demo Mode stays removed (PR-2 decision D4)', () => {
  it('no source file references a demo escape hatch', () => {
    // A guard that reads `!isDemo` is a client-controlled authorization
    // bypass in UX terms: a value the browser owns widening what the UI
    // offers. Grepping the shipped source is the cheapest way to keep it
    // from coming back by accident.
    const files = [
      'auth/AuthContext.jsx',
      'auth/capabilities.js',
      'auth/useMe.js',
      'auth/token.js',
      'auth/RequirePlatformAdmin.jsx',
      'auth/RequirePermission.jsx',
      'components/shell/Sidebar.jsx',
      'components/shell/navigation.js',
    ]
    for (const file of files) {
      const body = readFileSync(join(SRC, file), 'utf8')
      expect(body, `${file} still references demo mode`).not.toMatch(/isDemo|demoMode|enterDemo/)
    }
  })
})
