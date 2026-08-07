import { expect, test } from "@playwright/test";

import { goToday, loginE2e } from "./helpers";

test.describe("CC progress overview", () => {
  test.describe.configure({ timeout: 60_000 });

  test("lists Big Six and opens step detail", async ({ browser, request }) => {
    const page = await loginE2e(browser, request);
    await goToday(page);

    await page.getByRole("navigation").getByRole("link", { name: /Progres/i }).click();
    await expect(page.getByRole("heading", { name: /Mój progres/i })).toBeVisible({
      timeout: 15_000,
    });

    const rows = page.locator("ul li").filter({ has: page.getByRole("link") });
    await expect(rows).toHaveCount(6, { timeout: 15_000 });

    const firstLink = page.locator('a[href^="/progress/"]').first();
    await expect(firstLink).toBeVisible();
    const name = (await firstLink.textContent())?.trim() ?? "";
    await firstLink.click();

    await expect(page.getByRole("heading", { name: name })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/Kroki progresji/i)).toBeVisible();
    await expect(page.getByText(/aktualny/i).first()).toBeVisible();

    await page.getByRole("button", { name: /Dostosuj krok/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(
      page.getByText(/nie edytuje starych sesji/i),
    ).toBeVisible();
    await page.getByRole("button", { name: /Anuluj/i }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
  });
});
