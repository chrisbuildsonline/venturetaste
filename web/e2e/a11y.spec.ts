import { expect, test, type Page } from "@playwright/test";

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

test("every button, link and tab on the start page is at least 44px tall", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await expect(page.getByTestId("empty-state")).toBeVisible();
  const small: string[] = [];
  for (const el of await page.locator("button, a, [role=tab]").all()) {
    if (!(await el.isVisible())) continue;
    const box = await el.boundingBox();
    if (box && box.height < 44) small.push(`${(await el.innerText()).trim()} (${box.height}px)`);
  }
  expect(small).toEqual([]);
  expect(errors).toEqual([]);
});

test("screen mode shows stacked cards, not the table, at 375px with no sideways scroll", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" }).click();
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  test.setTimeout(120_000); // a live 4-target screen takes 6-15 s
  const cards = page.getByTestId("screen-card");
  await expect(cards).toHaveCount(4);
  await expect(page.getByText("Screening…")).toHaveCount(0, { timeout: 90_000 });
  await expect(cards.first()).toBeVisible();
  await expect(page.getByTestId("screen-table")).toBeHidden();
  await expect(cards.first().getByTestId("screen-card-verdict")).toBeVisible();
  await expect(cards.first().getByRole("button", { name: /Full diligence/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: "e2e/screenshots/screen-mobile-cards.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("keyboard focus shows a ring on the first chip", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  const chip = page.getByRole("group", { name: "Preset deals" }).getByRole("button").first();
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("Tab");
    if (await chip.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(chip).toBeFocused();
  // Tailwind's focus ring is a box-shadow (focus:outline-none leaves a transparent solid outline)
  expect(await chip.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe("none");
  expect(errors).toEqual([]);
});
