import { expect, test, type Page } from "@playwright/test";

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

const modeButton = (page: Page, name: string) => page.getByRole("group", { name: "Mode" }).getByRole("button", { name });

test("switching Compare -> Screen -> Compare after a run never crashes the app", async ({ page }) => {
  // Chrome 155 returns a Promise from scrollIntoView; React then calls it as the effect cleanup on unmount
  await page.addInitScript(() => {
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element, ...args: []) {
      original.apply(this, args);
      return Promise.resolve() as unknown as undefined;
    };
  });
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByTestId("results")).toBeVisible();
  await expect(page.getByTestId("agent-Partner")).toHaveAttribute("data-state", "done");

  await modeButton(page, "Screen targets").click();
  await expect(page.getByText(/couldn.t load/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  await expect(page.getByTestId("screen-row")).toHaveCount(4);
  await expect(page.getByText("Screening…")).toHaveCount(0);

  await modeButton(page, "Compare a deal").click();
  await expect(page.getByText(/couldn.t load/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByTestId("results")).toBeVisible();
  await expect(page.getByTestId("agent-Partner")).toHaveAttribute("data-state", "done");
  await expect(page.getByText(/couldn.t load/i)).toHaveCount(0);
  expect(errors).toEqual([]);
});
