import { expect, test } from "@playwright/test";

import { goSatProgress, goSatellites, goToday, loginE2e } from "../helpers";

test.describe("satellite progress results tab", () => {
  test.describe.configure({ timeout: 60_000 });

  test("nav tab lists satellite and opens detail with range toggle", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const satName = `E2E Wyniki ${Date.now()}`;

    await goSatellites(page);
    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("B");
    await page.getByLabel(/Serie w celu/i).selectOption("3");
    await page.getByLabel(/Min\. powtórzeń/i).fill("10");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await goSatProgress(page);
    const card = page.getByRole("link", { name: new RegExp(satName, "i") });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByRole("heading", { name: /Siła\s*\/\s*serie/i }),
    ).toBeVisible();
    await card.click();

    await expect(page.getByRole("heading", { name: satName })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("heading", { name: /Trendy/i })).toBeVisible();
    await expect(
      page.getByRole("group", { name: /Zakres wykresu/i }),
    ).toBeVisible();

    await page.getByRole("button", { name: /7 dni/i }).click();
    await expect(page.getByRole("button", { name: /7 dni/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.getByRole("button", { name: /90 dni/i }).click();
    await expect(page.getByRole("button", { name: /90 dni/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await goToday(page);
  });
});
