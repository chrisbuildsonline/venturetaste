import { expect, test } from "@playwright/test";

// Opt-in: only runs when BASE_URL points at a deployment with a real Qloo key (bun run docker:smoke, the public URL).
const AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"];

test("live: Nike + Adidas runs end to end with no console errors", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));

  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByLabel("Acquirer")).toHaveValue("Nike");
  await expect(page.getByLabel("Target")).toHaveValue("Adidas");

  await expect(page.getByTestId("bci-value")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("verdict")).toBeVisible();
  await expect(page.getByTestId("memo")).toContainText("Nike + Adidas");
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toHaveAttribute("data-state", "done");
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();

  expect(errors).toEqual([]);
});
