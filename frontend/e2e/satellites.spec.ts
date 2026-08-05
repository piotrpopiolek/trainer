import { expect, test } from "@playwright/test";

import { loginE2e } from "./helpers";

test.describe("satellite goal-only path", () => {
  test("create type C satellite, log completed, soft-delete shows no-rewind CTAs", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const satName = `E2E Stretch ${Date.now()}`;

    await page.getByRole("link", { name: /Satelit/i }).click();
    await expect(page.getByRole("heading", { name: /Satelit/i })).toBeVisible();

    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("C");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: /Dziś|Today/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    const satCard = page
      .locator("div.rounded-xl")
      .filter({ hasText: satName })
      .first();
    await satCard.getByRole("button", { name: /^Zapisz$/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel(/Wykonane/i).check();
    await page.getByRole("button", { name: /Zapisz wynik/i }).click();
    await expect(page.getByText(/Sesja zapisana|zapisana/i)).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: /^Usuń$/i }).first().click();
    await expect(
      page.getByRole("heading", { name: /Usunięcie nie cofa progresji/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Usuń tylko wpis/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Usuń i dostosuj krok/i }),
    ).toBeVisible();

    await page.getByRole("button", { name: /Usuń tylko wpis/i }).click();
    await expect(
      page.getByRole("heading", { name: /Usunięcie nie cofa progresji/i }),
    ).toBeHidden({ timeout: 10_000 });
  });

  test("create type B satellite and log goal-met reps online", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const satName = `E2E Hip ${Date.now()}`;

    await page.getByRole("link", { name: /Satelit/i }).click();
    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("B");
    await page.getByLabel(/Serie w celu/i).selectOption("3");
    await page.getByLabel(/Min\. powtórzeń/i).fill("10");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: /Dziś|Today/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    const satCard = page
      .locator("div.rounded-xl")
      .filter({ hasText: satName })
      .first();
    await satCard.getByRole("button", { name: /^Zapisz$/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    for (const n of [1, 2, 3]) {
      await page.getByLabel(new RegExp(`Seria ${n}`, "i")).fill("10");
    }
    await page.getByRole("button", { name: /Zapisz wynik/i }).click();
    await expect(page.getByText(/Sesja zapisana|zapisana/i)).toBeVisible({
      timeout: 15_000,
    });
  });
});
