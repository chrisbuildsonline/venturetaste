import { expect, test, type Page } from "@playwright/test";

const AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"];

// Next.js also renders its own role=alert route announcer, so skip it.
const inlineAlert = (page: Page) => page.locator("[role=alert]:not(#__next-route-announcer__)");

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

test("demo: Nike + Adidas preset runs the whole diligence", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  await expect(page.getByTestId("empty-state")).toBeVisible();
  await page.getByRole("button", { name: "Nike + Adidas" }).click();

  await expect(page.getByLabel("Acquirer")).toHaveValue("Nike");
  await expect(page.getByLabel("Target")).toHaveValue("Adidas");
  await expect(page.getByTestId("bci-value")).toHaveText("53.9");
  await expect(page.getByTestId("verdict")).toHaveText("Proceed");
  await expect(page.getByTestId("churn-band")).toContainText(/medium/i);
  await expect(page.getByTestId("clash-value")).toBeVisible();
  await expect(page.locator("[data-testid=radar] svg").first()).toBeVisible();
  await expect(page.getByTestId("memo")).toBeVisible();
  await expect(page.getByTestId("memo")).toContainText("Nike + Adidas");
  await expect(page.getByTestId("shared-tastes")).toBeVisible();
  await expect(page.getByTestId("demographics")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nike × Adidas taste overlap" })).toBeVisible();
  await expect(page.getByTestId("demographics")).toContainText("under-indexed");
  const radarBox = await page.getByTestId("radar").boundingBox();
  expect(radarBox?.height ?? 0).toBeGreaterThanOrEqual(400);

  // signed affinities: negative bars sit left of the zero line, positive bars right of it
  const bars = page.getByTestId("demo-bar");
  const count = await bars.count();
  const signs = new Set<string | null>();
  for (let i = 0; i < count; i++) {
    const bar = bars.nth(i);
    const sign = await bar.getAttribute("data-sign");
    signs.add(sign);
    const box = await bar.boundingBox();
    const track = await bar.locator("xpath=..").boundingBox();
    const centre = track!.x + track!.width / 2;
    if (sign === "negative") expect(box!.x + box!.width).toBeLessThanOrEqual(centre + 1);
    else expect(box!.x).toBeGreaterThanOrEqual(centre - 1);
  }
  expect(signs).toEqual(new Set(["negative", "positive"]));
  for (const agent of AGENTS) {
    const row = page.getByTestId(`agent-${agent}`);
    await expect(row).toHaveAttribute("data-state", "done");
    await expect(row).toContainText("ms");
    await expect(row).toContainText("Qloo call");
  }
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();

  await page.screenshot({ path: "e2e/screenshots/desktop.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("bci-value")).toBeVisible();
  // the chart re-measures asynchronously after the resize, so poll
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(0);
  await page.screenshot({ path: "e2e/screenshots/mobile.png", fullPage: true });

  expect(errors).toEqual([]);
});

test("Patagonia + Gucci shows the no shared taste state and a Pass", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + Gucci" }).click();

  await expect(page.getByTestId("no-shared-taste")).toBeVisible();
  await expect(page.getByTestId("no-shared-taste")).toContainText("No shared taste");
  await expect(page.getByTestId("verdict")).toHaveText("Pass");
  await expect(page.getByTestId("memo")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/no-shared-taste.png", fullPage: true });

  expect(errors).toEqual([]);
});

test("typed brands run from the form", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByLabel("Acquirer").fill("Patagonia");
  await page.getByLabel("Target").fill("The North Face");
  await page.getByRole("button", { name: "Run diligence" }).click();
  await expect(page.getByTestId("verdict")).toHaveText("Proceed with conditions");
  await expect(page.getByTestId("bci-value")).toHaveText("46.6");
  expect(errors).toEqual([]);
});

test("unknown brand shows the API error inline", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByLabel("Target").fill("Zzqx Nonbrand");
  await page.getByRole("button", { name: "Run diligence" }).click();

  const alert = inlineAlert(page);
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("Zzqx Nonbrand");
  await expect(page.getByTestId("bci-value")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();

  // 422 is an expected API answer; the browser logs the failed resource as a console error.
  expect(errors.filter((e) => !e.includes("422"))).toEqual([]);
});

test("same brand twice shows an inline alert", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  let diligenceRequests = 0;
  page.on("request", (req) => {
    if (req.url().includes("/api/diligence")) diligenceRequests++;
  });
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByLabel("Target").fill("  nIKE ");
  await page.getByRole("button", { name: "Run diligence" }).click();

  await expect(inlineAlert(page)).toContainText(/different brands/i);
  expect(diligenceRequests).toBe(0);
  expect(errors).toEqual([]);
});

test("empty inputs are rejected client side", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Run diligence" }).click();
  await expect(inlineAlert(page)).toContainText(/both/i);
  expect(errors).toEqual([]);
});
