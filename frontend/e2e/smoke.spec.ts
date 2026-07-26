import { expect, test } from "@playwright/test";

test.describe("scaffold", () => {
  test("home loads and shows API status", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Trainer" })).toBeVisible();
    await expect(page.getByText("API działa")).toBeVisible({ timeout: 15_000 });
  });
});
