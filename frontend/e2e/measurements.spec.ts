import { expect, test } from "@playwright/test";

import { loginE2e } from "./helpers";

test.describe("measurement trends", () => {
  test.describe.configure({ timeout: 60_000 });

  test("shows range toggle on measurements page", async ({ browser, request }) => {
    const page = await loginE2e(browser, request);

    await page.getByRole("navigation").getByRole("link", { name: /Pomiary/i }).click();
    await expect(page.getByRole("heading", { name: /Pomiary sylwetki/i })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("heading", { name: /^Trendy$/i })).toBeVisible();
    await expect(page.getByRole("group", { name: /Zakres wykresu/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /30 dni/i })).toBeVisible();
    await page.getByRole("button", { name: /7 dni/i }).click();
    await expect(page.getByRole("button", { name: /7 dni/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
