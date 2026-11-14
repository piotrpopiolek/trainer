import { expect, test } from "@playwright/test";

/**
 * Unauthenticated smoke: `/` is behind RequireAuth → redirect to login.
 * Full auth/today E2E lands with Google mock harness (testing.mdc mandatory suite).
 */
test.describe("auth gate", () => {
  test("home redirects to login", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Zaloguj się" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByRole("button", { name: "Zaloguj przez Google" }),
    ).toBeVisible();
  });
});
