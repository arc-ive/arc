# Playwright E2E (Phase 1 foundation)

## Installation

```bash
cd frontend
npm install            # pulls @playwright/test (devDependency)
npx playwright install chromium
```

Playwright 1.x, Chromium only. No other browsers yet by design.

## Configuration

`frontend/playwright.config.js`: `baseURL http://localhost:5173` (vite dev, which proxies `/api` → `:8000`), single `chromium` project + `setup` project for auth, `storageState: e2e/.auth/user.json`, trace/screenshot/video on failure (video retained on failure), 60s test / 10s expect timeouts, single worker. `webServer` starts `vite dev` automatically (reused when already running; set `CI=1` to forbid reuse).

## Structure

```text
frontend/e2e/
  playwright.config.js → ../playwright.config.js (repo root of config is frontend/)
  auth.setup.js        # dev reference login via API → storageState
  helpers/
    api.js             # apiUrl(), csrfHeaders() from stored cookies
    browser-health.js  # watchBrowserHealth() + expectHealthyBrowser()
  smoke/
    login.spec.js      # login page, invalid login, reference-user redirect
    ask-arc.spec.js    # seed doc → ask → grounded answer
    skill-execution.spec.js  # create skill → Execute dialog → Succeeded
```

Config lives at `frontend/playwright.config.js`; tests under `frontend/e2e/`.

## Authentication fixture

`auth.setup.js` POSTs `POST {API}/internal/dev/auth/login {user_id: ref-acme-technologies-company-admin}` (dev-only endpoint, `APP_ENV=development`, seeded reference data) and persists cookies to `e2e/.auth/user.json` (git-ignored). Specs reuse it; only login specs run stateless. No real credentials anywhere.

## Test data

- User/tenant: seeded reference records (`ref-acme-technologies-company-admin` / `ref-acme-technologies`).
- Knowledge/skill rows: created per-test via API with timestamped unique content, then exercised through the UI. Never personal, production, or manual records.
- Reset: per-test unique names; nothing shared to clean up.

## Local execution

```bash
# 1. Start ARC (postgres :5432, API :8000, APP_ENV=development,
#    APPLICATION_ROLE_ASSIGNMENTS set to the dev mapping in .env.example)
docker compose up -d --build

# 2. Frontend deps once
cd frontend && npm ci

# 3. Smoke tests (starts vite automatically)
npm run test:e2e

# Headed / UI mode / report
npm run test:e2e:headed
npm run test:e2e:ui
npm run test:e2e:report
```

## Debugging

Failures attach trace + video + screenshot + `error-context.md` under `frontend/test-results/`. Open with `npm run test:e2e:report` (writes `playwright-report/`, both git-ignored).

## Browser health

`watchBrowserHealth(page)` records page exceptions, console errors, and unexpected 4xx/5xx; `expectHealthyBrowser()` asserts emptiness. 401/403 resource loads and favicon/devtools noise are filtered (auth boundaries are asserted directly by tests).

## Adding new tests

1. Put journeys in `e2e/<area>/`, reuse `helpers/api.js` + `browser-health.js`.
2. Seed via API with unique content; assert user-visible outcomes with `getByRole`/`getByLabel`, never bare CSS/XPath/`nth()`.
3. No `waitForTimeout`; rely on auto-waiting. CSRF comes from stored cookies via `csrfHeaders()`.
4. UI text that passes through PII sanitization (e.g. skill names render redacted) must be located by stable fragments (IDs, numeric suffixes).

## CI expectations

Headless, single worker, artifacts retained on failure. Backend must run with `APP_ENV=development` and seeded reference data; `APPLICATION_ROLE_ASSIGNMENTS` must grant the reference roles (empty mapping yields 403s). Full CI pipeline wiring is out of scope for Phase 1.
