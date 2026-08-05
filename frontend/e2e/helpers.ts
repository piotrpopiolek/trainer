import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";

export type E2eSeedScenario =
  | "mini_progression"
  | "pending_regression"
  | "pending_config";

export type E2eSeedResult = {
  schema_version: number;
  scenario: E2eSeedScenario;
  satellite_id: string;
  name: string;
  current_step_number?: number;
  recommendation_id?: string;
  from_step?: number;
  to_step?: number;
};

/**
 * Mint a ready session via POST /api/auth/e2e-login (ENABLE_E2E_LOGIN).
 * Returns a page already on `/` with cookies applied.
 */
export async function loginE2e(
  browser: Browser,
  request: APIRequestContext,
): Promise<Page> {
  const res = await request.post("/api/auth/e2e-login", {
    data: { schema_version: 1 },
    maxRedirects: 0,
    failOnStatusCode: false,
  });
  expect(
    res.status(),
    "e2e-login must be enabled (ENABLE_E2E_LOGIN=1, non-prod)",
  ).toBe(302);

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
  });

  const base = process.env.PLAYWRIGHT_BASE_URL ?? "https://localhost";
  const setCookies = res
    .headersArray()
    .filter((h) => h.name.toLowerCase() === "set-cookie");
  for (const h of setCookies) {
    const raw = h.value;
    const [pair] = raw.split(";");
    const eq = pair.indexOf("=");
    if (eq < 0) continue;
    const name = pair.slice(0, eq).trim();
    const value = pair.slice(eq + 1).trim();
    // __Host- cookies must not set Domain — bind via url.
    await context.addCookies([
      {
        name,
        value,
        url: base,
        secure: true,
        httpOnly: true,
        sameSite: "Strict",
      },
    ]);
  }

  const page = await context.newPage();
  await page.goto("/");
  await expect(page.getByRole("navigation")).toBeVisible({ timeout: 15_000 });
  return page;
}

/** Seed multi-step / pending-regression fixtures for the logged-in E2E user. */
export async function seedE2e(
  page: Page,
  scenario: E2eSeedScenario,
): Promise<E2eSeedResult> {
  const res = await page.request.post("/api/auth/e2e-seed", {
    data: { schema_version: 1, scenario },
  });
  expect(res.ok(), `e2e-seed ${scenario} failed: ${res.status()}`).toBeTruthy();
  const body = (await res.json()) as E2eSeedResult;
  // Invalidate stale React Query /today from the post-login landing.
  await page.goto("/");
  await expect(page.getByRole("navigation")).toBeVisible({ timeout: 15_000 });
  return body;
}

export async function goSatellites(page: Page): Promise<void> {
  await page.getByRole("link", { name: /Satelit/i }).click();
  await expect(page.getByRole("heading", { name: /Satelit/i })).toBeVisible();
}

export async function goToday(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("navigation")).toBeVisible({ timeout: 15_000 });
}

/** Simulate offline for outbox writes without killing React Query GETs. */
export async function setAppOffline(page: Page, offline: boolean): Promise<void> {
  await page.evaluate((isOffline) => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => !isOffline,
    });
    window.dispatchEvent(new Event(isOffline ? "offline" : "online"));
  }, offline);
}

export function satelliteCard(page: Page, satName: string) {
  return page.locator("div.rounded-xl").filter({ hasText: satName }).first();
}
