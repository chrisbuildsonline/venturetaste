import { expect, test, type Page } from "@playwright/test";

type Deal = { acquirer_label: string; target_label: string; year: number; bci: number; clash: number; churn: string; verdict: string; fit: { label: string; note: string } };

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

test("backtest panel shows every real deal with the API numbers", async ({ page, request }) => {
  const errors = watchErrors(page);
  const { deals } = (await (await request.get("/api/backtest")).json()) as { deals: Deal[] };
  expect(deals.length).toBeGreaterThanOrEqual(3);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const panel = page.getByTestId("backtest");
  await expect(panel.getByRole("heading", { name: "Backtest: real deals" })).toBeVisible();
  const rows = panel.getByTestId("backtest-row");
  await expect(rows).toHaveCount(deals.length);
  for (const [i, d] of deals.entries()) {
    const row = rows.nth(i);
    await expect(row).toContainText(`${d.acquirer_label} + ${d.target_label}`);
    await expect(row).toContainText(String(d.year));
    await expect(row.getByTestId("backtest-bci")).toHaveText(d.bci.toFixed(1));
    await expect(row.getByTestId("backtest-clash")).toHaveText(`${d.clash.toFixed(1)}%`);
    await expect(row).toContainText(d.churn, { ignoreCase: true });
    await expect(row).toContainText(d.verdict);
    await expect(row.getByTestId("backtest-fit")).toHaveText(d.fit.label);
    await expect(row.getByTestId("backtest-fit-note")).toHaveText(d.fit.note);
  }
  await expect(panel.getByRole("columnheader", { name: "Fit" })).toBeVisible();
  await expect(rows.first().getByTestId("backtest-fit")).toHaveText("Complementary");
  await expect(rows.first()).toContainText("Nike + Converse");
  await expect(panel.getByTestId("backtest-note")).toContainText("sanity check, not a calibration");
  await expect(panel.getByTestId("backtest-note")).toContainText("holding companies");
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/backtest-desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("backtest panel stacks into cards at 375px with no sideways scroll", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const panel = page.getByTestId("backtest");
  await expect(panel.getByTestId("backtest-card").first()).toBeVisible();
  await expect(panel.getByTestId("backtest-row").first()).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/backtest-mobile.png", fullPage: true });
  expect(errors).toEqual([]);
});
