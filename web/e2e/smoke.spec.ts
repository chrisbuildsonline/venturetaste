import { expect, test } from "@playwright/test";

test("home page loads with no console or page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "VentureTaste" }),
  ).toBeVisible();
  await expect(
    page.getByText("Taste-graph due diligence for consumer brand deals"),
  ).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/smoke.png" });

  expect(errors).toEqual([]);
});
