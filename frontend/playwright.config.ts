import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against Compose same-origin (https://localhost via Caddy).
 * Smoke covers unauthenticated login gate; full suite (auth mock, today, account)
 * lands with frontend-online / F1.1 offline work.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "https://localhost",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
