import { createHash, randomBytes } from 'node:crypto';
import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end checks of the project interface: `openguildkit ui` on a sample project built for the run
 * (scripts/serve-sample.mjs). Run `npm run build` first; the server serves web/dist.
 */
const channel = process.env.PW_CHANNEL ?? 'chrome';
const port = Number(process.env.PW_PROJECT_PORT ?? 7322);
// The server opens its session only to a browser that holds the key of its printed address, on the host name of the
// run under .localhost (drawn from the key, as webui.session_name does). The run picks the key, the servers inherit
// it, and each browser starts with the cookie the printed address would set. The workers read this file again: the
// key set here, in the runner, reaches them through the environment.
process.env.OPENGUILDKIT_UI_KEY ??= randomBytes(32).toString('hex');
const key = process.env.OPENGUILDKIT_UI_KEY;
const host = `ogk-${createHash('sha256').update(key).digest('hex').slice(0, 24)}.localhost`;
process.env.PW_PROJECT_HOST = host;
const opened = (serverPort: number) => ({ name: `ogk-${serverPort}`, value: key, domain: host, path: '/', expires: -1, httpOnly: true, secure: false, sameSite: 'Strict' as const });

export default defineConfig({
  testDir: 'tests/e2e',
  testMatch: 'project*.spec.ts',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://${host}:${port}`,
    viewport: { width: 1440, height: 900 },
    locale: 'fr-FR',
    trace: 'retain-on-failure',
    storageState: { cookies: [opened(port), opened(port + 1), opened(port + 2)], origins: [] },
  },
  webServer: [
    {
      command: 'node scripts/serve-sample.mjs',
      url: `http://127.0.0.1:${port}/api/session`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { PW_PROJECT_PORT: String(port) },
    },
    {
      // A folder without OpenGuildKit: the page opens the setup.
      command: 'node scripts/serve-sample.mjs --empty',
      url: `http://127.0.0.1:${port + 1}/api/session`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { PW_PROJECT_PORT: String(port + 1) },
    },
    {
      // A folder with Stripe in its stack: the setup proposes PCI DSS, which a person accepts or declines.
      command: 'node scripts/serve-sample.mjs --empty --stripe',
      url: `http://127.0.0.1:${port + 2}/api/session`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { PW_PROJECT_PORT: String(port + 2) },
    },
  ],
  projects: [{ name: 'chrome', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, channel: channel === 'chromium' ? undefined : channel } }],
});
