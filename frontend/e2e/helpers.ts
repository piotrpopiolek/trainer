import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";

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
