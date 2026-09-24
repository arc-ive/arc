// Playwright E2E configuration (Phase 1: Chromium only).
//
// Backend must be up first:
//   docker compose up -d            # postgres + arc API on :8000
// The config starts `vite dev` itself (reuses it if already running).
// Auth state comes from e2e/auth.setup.js (dev reference login via API),
// so specs never log in through the UI unless testing login itself.
import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173'
const API_URL = process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  timeout: 60 * 1000,
  expect: { timeout: 10 * 1000 },
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15 * 1000,
    navigationTimeout: 30 * 1000,
  },
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
    env: { VITE_API_BASE_URL: '/api' },
  },
  projects: [
    {
      name: 'setup',
      testMatch: /.*\.setup\.js/,
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'e2e/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],
  // Shared by specs and global setup.
  metadata: { apiUrl: API_URL },
})
