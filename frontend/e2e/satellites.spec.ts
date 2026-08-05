import { expect, test } from "@playwright/test";

import {
  goSatellites,
  goToday,
  loginE2e,
  fillSatelliteSetValues,
  satelliteCard,
  seedE2e,
} from "./helpers";

test.describe("satellite goal-only path", () => {
  test.describe.configure({ timeout: 60_000 });
  test("create type C satellite, log completed, soft-delete shows no-rewind CTAs", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const satName = `E2E Stretch ${Date.now()}`;

    await goSatellites(page);
    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("C");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await goToday(page);
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await satelliteCard(page, satName).getByRole("button", { name: /^Zapisz$/i }).click();
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

    await goSatellites(page);
    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("B");
    await page.getByLabel(/Serie w celu/i).selectOption("3");
    await page.getByLabel(/Min\. powtórzeń/i).fill("10");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await goToday(page);
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await satelliteCard(page, satName).getByRole("button", { name: /^Zapisz$/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    await fillSatelliteSetValues(page, ["10", "10", "10"]);
    await page.getByRole("button", { name: /Zapisz wynik/i }).click();
    await expect(page.getByText(/Sesja zapisana|zapisana/i)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("network failure on session save enqueues outbox pending", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const satName = `E2E Offline ${Date.now()}`;

    await goSatellites(page);
    await page.getByLabel(/Nazwa/i).fill(satName);
    await page.getByLabel(/Typ/i).selectOption("C");
    await page.getByRole("button", { name: /Dodaj satelit/i }).click();
    await expect(page.getByText(satName)).toBeVisible({ timeout: 15_000 });

    await goToday(page);
    await expect(page.getByText(satName, { exact: true })).toBeVisible({
      timeout: 15_000,
    });

    await satelliteCard(page, satName).getByRole("button", { name: /^Zapisz$/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel(/Wykonane/i).check();

    // Abort POSTs so writes.ts falls through to IndexedDB outbox.
    // (Playwright context.setOffline hangs IDB in this stack.)
    await page.route("**/api/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.abort("failed");
        return;
      }
      await route.continue();
    });
    await page.route("**/api/sync/**", async (route) => {
      if (route.request().method() === "POST") {
        await route.abort("failed");
        return;
      }
      await route.continue();
    });

    const saveBtn = page.getByRole("button", { name: /Zapisz wynik/i });
    await expect(saveBtn).toBeEnabled();
    await saveBtn.click();

    await expect(
      page.getByText(/Zapisano lokalnie/i),
    ).toBeVisible({ timeout: 20_000 });
    await expect(
      page.getByText(/Oczekuje na synchronizację \(1\)/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("pending config banner after goal bump with history", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const seeded = await seedE2e(page, "pending_config");

    await goSatellites(page);
    await expect(page.getByText(seeded.name)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Nowa konfiguracja od/i)).toBeVisible({
      timeout: 15_000,
    });
  });
});

test.describe("satellite mini-progression", () => {
  test.describe.configure({ timeout: 60_000 });
  test("goal-met advances step and shows Awans modal", async ({
    browser,
    request,
  }) => {
    const page = await loginE2e(browser, request);
    const seeded = await seedE2e(page, "mini_progression");

    await goToday(page);
    await expect(page.getByText(seeded.name)).toBeVisible({ timeout: 15_000 });
    await expect(
      satelliteCard(page, seeded.name).getByText(/krok 1/i),
    ).toBeVisible();

    await satelliteCard(page, seeded.name)
      .getByRole("button", { name: /^Zapisz$/i })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel(/Seria 1/i).fill("5");
    await page.getByRole("button", { name: /Zapisz wynik/i }).click();

    await expect(page.getByRole("heading", { name: /^Awans!$/i })).toBeVisible({
      timeout: 15_000,
    });

    await page.reload();
    await expect(
      satelliteCard(page, seeded.name).getByText(/krok 2/i),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("pending regression accept lowers step", async ({ browser, request }) => {
    const page = await loginE2e(browser, request);
    const seeded = await seedE2e(page, "pending_regression");

    await goToday(page);
    await expect(page.getByText(seeded.name, { exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/Sugestia regresu/i)).toBeVisible();
    await expect(
      satelliteCard(page, seeded.name).getByText(/krok 2/i),
    ).toBeVisible();

    await page.getByRole("button", { name: /Obniż krok/i }).click();
    await expect(page.getByText("Decyzja zapisana.")).toBeVisible({
      timeout: 15_000,
    });
    const regressModal = page.getByRole("heading", { name: /Regres satelity/i });
    if (await regressModal.isVisible().catch(() => false)) {
      await page.getByRole("dialog").getByRole("button", { name: /^OK$/i }).click();
    }

    await page.reload();
    await expect(
      satelliteCard(page, seeded.name).getByText(/krok 1/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Sugestia regresu/i)).toBeHidden();
  });

  test("pending regression decline keeps step", async ({ browser, request }) => {
    const page = await loginE2e(browser, request);
    const seeded = await seedE2e(page, "pending_regression");

    await goToday(page);
    await expect(page.getByText(/Sugestia regresu/i)).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: /Zostaw krok/i }).click();
    await expect(page.getByText("Decyzja zapisana.")).toBeVisible({
      timeout: 15_000,
    });

    await page.reload();
    await expect(
      satelliteCard(page, seeded.name).getByText(/krok 2/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Sugestia regresu/i)).toBeHidden();
  });
});
