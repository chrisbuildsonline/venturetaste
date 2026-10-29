import { expect, test, type Page } from "@playwright/test";

// Only runs with SCREENSHOTS=1 (see playwright.config.ts); writes the README images into ../docs/.
const AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"];

async function runPreset(page: Page, label: string) {
  await page.goto("/");
  await page.getByRole("button", { name: label }).click();
  await expect(page.getByTestId("bci-value")).toBeVisible();
  await expect(page.getByTestId("memo")).toBeVisible();
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toHaveAttribute("data-state", "done");
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();
  // let the charts finish animating before the shot
  await page.waitForTimeout(1500);
}

test("README screenshots: desktop and mobile Nike + Adidas", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page, "Nike + Adidas");
  await expect(page.getByTestId("bci-value")).toHaveText("53.9");
  // the layout the README describes: verdict and radar above the fold
  const verdictBox = (await page.getByTestId("verdict").boundingBox())!;
  const radarBox = (await page.getByTestId("radar").boundingBox())!;
  expect(verdictBox.y + verdictBox.height).toBeLessThanOrEqual(800);
  expect(radarBox.y).toBeLessThan(800);
  await expect(page.getByTestId("planner-Analyst")).toHaveText("Recorded qwen2.5:7b run");
  await expect(page.getByTestId("planner-Partner")).toHaveText("Recorded qwen2.5:7b run");
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toContainText("recorded answers, no live Qloo calls");
  await expect(page.getByRole("button", { name: "Download memo (.md)" })).toBeVisible();
  await page.screenshot({ path: "../docs/demo-desktop.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("bci-value")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "../docs/demo-mobile.png", fullPage: true });
});

test("README screenshots: Nike target screening table", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" }).click();
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  await expect(page.getByTestId("screen-row")).toHaveCount(4);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(page.locator("form").getByRole("button", { name: "Screen targets" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Download table (.md)" })).toBeVisible();
  await page.screenshot({ path: "../docs/screening.png", fullPage: true });
});

test("README screenshots: Find targets with a reason on each found target", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" }).click();
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByRole("button", { name: "Find targets" }).click();
  await expect(page.getByTestId("screen-found")).toHaveText("Found by Qloo: Nike's 5 best category fits");
  await expect(page.getByTestId("screen-row")).toHaveCount(5);
  const reasons = page.getByTestId("screen-reason");
  await expect(reasons).toHaveCount(5);
  for (const text of await reasons.allTextContents()) expect(text).toMatch(/^(Shares .+|No shared categories) · affinity \d\.\d\d$/);
  await expect(page.getByTestId("screen-bci")).toHaveCount(5);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Find targets" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Download table (.md)" })).toBeVisible();
  await page.screenshot({ path: "../docs/find-targets.png", fullPage: true });
});

test("README screenshots: mobile screening cards", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" }).click();
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  await expect(page.getByTestId("screen-card")).toHaveCount(4);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(page.getByTestId("screen-table")).toBeHidden();
  await expect(page.getByRole("list", { name: "Screening cards" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: "../docs/screening-mobile.png", fullPage: true });
});

test("README screenshots: deal memo export button", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page, "Nike + Adidas");
  const download = page.getByRole("button", { name: "Download memo (.md)" });
  await expect(download).toBeVisible();
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  expect(file.suggestedFilename()).toMatch(/\.md$/);
  await page.getByTestId("verdict").locator("xpath=ancestor::section[1]").screenshot({ path: "../docs/export.png" });
});

test("README screenshots: Patagonia + Gucci culture clash",async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page, "Patagonia + Gucci");
  await expect(page.getByTestId("verdict")).toHaveText("Pass");
  await expect(page.locator("body")).not.toContainText(/women-owned|friendship|inclusivity|credit card|hotel rating/i);
  await expect(page.getByTestId("radar-empty-caption")).toHaveText("No shared taste in any domain");
  await expect(page.locator("[data-testid=radar] .radar-baseline").first()).toBeAttached();
  await page.screenshot({ path: "../docs/culture-clash.png", fullPage: true });
});

test("README screenshots: backtest on real deals", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const panel = page.getByTestId("backtest");
  await expect(panel.getByRole("heading", { name: "Backtest: real deals" })).toBeVisible();
  await expect(panel.getByTestId("backtest-row")).toHaveCount(11);
  await expect(panel.getByTestId("backtest-row").first()).toContainText("Nike + Converse");
  await expect(panel.getByTestId("backtest-bci").first()).toHaveText("28.0");
  await expect(panel.getByTestId("backtest-note")).toContainText("sanity check, not a calibration");
  await panel.scrollIntoViewIfNeeded();
  await panel.screenshot({ path: "../docs/backtest.png" });
});
