import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

/**
 * Every page renders.
 *
 * This exists because `/platform/dashboard` shipped as a blank white
 * screen. `HealthPill` referenced `useQuery` and `queryKeys` after an
 * import prune removed both, and the page threw `ReferenceError: Can't
 * find variable: useQuery` on mount.
 *
 * Nothing caught it. Lint had no `no-undef` rule, the bundler does not
 * resolve free identifiers at build time, and — the actual gap — no test
 * rendered that page. 338 tests passed against a white screen.
 *
 * Two guards went in. `no-undef` is now an error in .oxlintrc.json, which
 * catches this exact shape statically. This is the other half: it mounts
 * every page component, so a crash on mount fails the suite regardless of
 * what caused it — a bad import, a hook order, a null deref in a default
 * branch.
 *
 * It asserts one thing only: the component mounts without throwing. Page
 * behaviour belongs in each page's own test; this is a floor, not a
 * substitute.
 */

// Auth, capability and tenant context are mocked permissively: the point
// is to exercise the render path, and a page gated to nothing renders
// nothing and proves little. Authorization itself is covered by the
// RequirePermission and capabilities tests.
vi.mock('../auth/useAuth.js', () => ({
  useAuth: () => ({
    principal: { sub: 'smoke-user' },
    signOut: vi.fn(),
    isLoaded: true,
  }),
}))

vi.mock('../auth/useMe.js', () => ({
  useMe: () => ({ data: undefined, isPending: false, isError: false, refetch: vi.fn() }),
}))

vi.mock('../auth/capabilities.js', () => ({
  useCapabilities: () => ({
    can: () => true,
    isMemberOf: () => true,
    isPlatformAdministrator: true,
    isEmployee: false,
    isPending: false,
    isLoaded: true,
    // WorkspaceDispatch reads the raw query off the hook, so the mock has
    // to carry it or the page throws on a shape this test invented.
    me: { isPending: false, isError: false, data: { memberships: [] } },
  }),
}))

vi.mock('../tenant/useTenant.js', () => ({
  useTenant: () => ({ tenantId: 'smoke-tenant', setTenantId: vi.fn() }),
}))

// Every network call resolves empty. A page that only renders with data
// is a page with a broken empty state, which this should surface too.
vi.mock('../api/client.js', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// Test files must be excluded in the PATTERN, not filtered afterwards:
// an eager glob IMPORTS every match, and importing a test module
// registers its suites into this one.
const PAGES = import.meta.glob(['./**/*.jsx', '!./**/*.test.jsx'], {
  eager: true,
})

/**
 * Route elements, not every component that lives under pages/.
 *
 * `*Page.jsx` is the convention, plus the two route elements that predate
 * it. Sub-components such as DocumentRow and ApprovalTimeline take
 * required props and are covered by their own tests; mounting them
 * propless here would assert nothing except that this file guessed their
 * signature wrong.
 */
const EXTRA_ROUTE_ELEMENTS = new Set(['WorkspaceDispatch', 'TenantLayout'])

function pageComponents() {
  const found = []
  for (const [path, mod] of Object.entries(PAGES)) {
    const isPageFile = /Page\.jsx$/.test(path)
    for (const [name, value] of Object.entries(mod)) {
      if (typeof value !== 'function' || !/^[A-Z]/.test(name)) continue
      if (!isPageFile && !EXTRA_ROUTE_ELEMENTS.has(name)) continue
      if (isPageFile && !/Page$/.test(name)) continue
      found.push({ path: path.replace('./', 'src/pages/'), name, Component: value })
    }
  }
  return found
}

function renderPage(Component) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, networkMode: 'always' } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/app/t/smoke-tenant/overview']}>
        <Routes>
          <Route path="/app/t/:tenantId/*" element={<Component />} />
          <Route path="*" element={<Component />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('every page mounts', () => {
  let consoleError

  beforeEach(() => {
    // React logs a render throw to console.error before rethrowing. Keep
    // the suite output readable without swallowing the failure itself.
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleError.mockRestore()
    cleanup()
  })

  it('finds the page components to check', () => {
    // A glob that matches nothing would make every assertion below pass
    // without testing anything — the same shape of bug as a source scan
    // over an empty file list.
    expect(pageComponents().length).toBeGreaterThan(20)
  })

  for (const { path, name, Component } of pageComponents()) {
    it(`${name} (${path})`, () => {
      expect(() => renderPage(Component)).not.toThrow()
    })
  }
})
