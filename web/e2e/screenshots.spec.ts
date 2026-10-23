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
  await page.screenshot({ path: "../docs/demo-desktop.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("bci-value")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "../docs/demo-mobile.png", fullPage: true });
});

test("README screenshots: Patagonia + Gucci culture clash", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page, "Patagonia + Gucci");
  await expect(page.getByTestId("verdict")).toHaveText("Pass");
  await page.screenshot({ path: "../docs/culture-clash.png", fullPage: true });
});
