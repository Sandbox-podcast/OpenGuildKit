import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end checks of the critical journeys. They use the locally installed Chrome
 * (channel "chrome") so no browser download is needed; set PW_CHANNEL=chromium to use
 * Playwright's bundled browser instead (after `npx playwright install chromium`).
 */
const channel = process.env.PW_CHANNEL ?? 'chrome';
const port = Number(process.env.PW_PORT ?? 5201);
const preview = process.env.PW_BASE_URL;

export default defineConfig({
  testDir: 'tests/e2e',
  // The project interface has its own server and config: playwright.project.config.ts.
  testIgnore: ['**/project*.spec.ts'],
  timeout: 180_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: preview ?? `http://localhost:${port}`,
    channel: channel === 'chromium' ? undefined : channel,
    viewport: { width: 1440, height: 900 },
    locale: 'fr-FR',
    trace: 'retain-on-failure',
  },
  webServer: preview ? undefined : {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
  projects: [{ name: 'chrome', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, channel: channel === 'chromium' ? undefined : channel } }],
});
