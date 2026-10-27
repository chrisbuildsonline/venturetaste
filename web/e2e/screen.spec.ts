import { expect, test, type Page } from "@playwright/test";

const inlineAlert = (page: Page) => page.locator("[role=alert]:not(#__next-route-announcer__)");
const rows = (page: Page) => page.getByTestId("screen-row");
const targets = (page: Page) => rows(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-target")));
const screenButton = (page: Page) => page.locator("form").getByRole("button", { name: "Screen targets" });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

async function screenMode(page: Page) {
  await page.goto("/");
  await page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" }).click();
}

async function runPreset(page: Page) {
  await screenMode(page);
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  await expect(rows(page)).toHaveCount(4);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(screenButton(page)).toBeEnabled();
}

const bci = async (page: Page) =>
  (await rows(page).getByTestId("screen-bci").allTextContents()).map(Number);

test("mode switch: compare is the default and screen mode swaps the form", async ({ page }) => {
  await page.goto("/");
  const compare = page.getByRole("button", { name: "Compare a deal" });
  const screen = page.getByRole("group", { name: "Mode" }).getByRole("button", { name: "Screen targets" });
  await expect(compare).toHaveAttribute("aria-pressed", "true");
  await expect(screen).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByLabel("Target", { exact: true })).toBeVisible();
  await screen.click();
  await expect(screen).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Candidate targets")).toBeVisible();
  await expect(page.getByLabel("Target", { exact: true })).toHaveCount(0);
  await compare.click();
  await expect(page.getByLabel("Target", { exact: true })).toBeVisible();
});

test("screen preset fills every row, ranked by BCI descending", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page);

  await expect(page.getByLabel("Acquirer")).toHaveValue("Nike");
  await expect(page.getByLabel("Candidate targets")).toHaveValue(/Adidas/);
  const names = await targets(page);
  expect([...names].sort()).toEqual(["Adidas", "Gucci", "Lululemon", "Puma"]);
  const scores = await bci(page);
  expect(scores).toHaveLength(4);
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
  expect(names[0]).toBe("Adidas");
  await expect(rows(page).first().getByTestId("screen-verdict")).toHaveText("Proceed");
  const verdicts = new Set(await rows(page).getByTestId("screen-verdict").allTextContents());
  expect(verdicts.size).toBeGreaterThanOrEqual(2);
  await expect(page.getByRole("columnheader", { name: "BCI" })).toHaveAttribute("aria-sort", "descending");
  await expect(page.getByRole("columnheader", { name: "Culture clash" })).toHaveAttribute("aria-sort", "none");
  await expect(inlineAlert(page)).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Recorded Qloo data" })).toHaveCount(1);
  await page.screenshot({ path: "e2e/screenshots/screen-desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("clicking culture clash reorders the rows and sets aria-sort", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  // fixtures rank the real brands the same on both scores, so feed scores where BCI and clash disagree
  const fake: Record<string, [number, number]> = { A: [80, 50], B: [40, 10], C: [60, 30] };
  await page.route("**/api/diligence", async (route) => {
    const [bci, clash] = fake[route.request().postDataJSON().target];
    const body = { scores: { bci, culture_clash: clash, churn_risk: "medium" }, memo: { verdict: "Proceed with conditions" } };
    await route.fulfill({ json: body });
  });
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByLabel("Candidate targets").fill("A, B, C");
  await screenButton(page).click();
  await expect(rows(page)).toHaveCount(3);
  await expect(screenButton(page)).toBeEnabled();
  const byBci = await targets(page);
  expect(byBci).toEqual(["A", "C", "B"]);
  await page.getByRole("button", { name: "Culture clash" }).click();
  await expect(page.getByRole("columnheader", { name: "Culture clash" })).toHaveAttribute("aria-sort", "ascending");
  await expect(page.getByRole("columnheader", { name: "BCI" })).toHaveAttribute("aria-sort", "none");
  const clashes = (await rows(page).getByTestId("screen-clash").allTextContents()).map((t) => parseFloat(t));
  expect(clashes).toEqual([...clashes].sort((a, b) => a - b));
  expect(await targets(page)).toEqual(["B", "C", "A"]);
  await page.getByRole("button", { name: "BCI" }).click();
  await expect(page.getByRole("columnheader", { name: "BCI" })).toHaveAttribute("aria-sort", "descending");
  expect(await targets(page)).toEqual(byBci);
});

test("typed targets with an unknown brand show that row's error while the others finish", async ({ page }) => {
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByLabel("Candidate targets").fill("Zzqx Nonbrand\nPuma, adidas, PUMA, nike");
  await screenButton(page).click();
  await expect(rows(page)).toHaveCount(3);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  const bad = rows(page).filter({ hasText: "Zzqx Nonbrand" });
  await expect(bad).toContainText("Qloo has no brand named");
  await expect(bad.getByRole("button", { name: /Full diligence/ })).toHaveCount(0);
  expect((await targets(page)).at(-1)).toBe("Zzqx Nonbrand");
  await expect(rows(page).first().getByRole("button", { name: /Full diligence/ })).toBeVisible();
  expect(await bci(page)).toHaveLength(2);
});

test("fewer than 2 targets shows the validation error", async ({ page }) => {
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Nike");
  await page.getByLabel("Candidate targets").fill("Adidas, adidas, Nike");
  await screenButton(page).click();
  await expect(inlineAlert(page)).toContainText(/at least 2/i);
  await expect(rows(page)).toHaveCount(0);
  await page.getByLabel("Candidate targets").fill("a, b, c, d, e, f");
  await screenButton(page).click();
  await expect(inlineAlert(page)).toContainText(/at most 5/i);
  await expect(rows(page)).toHaveCount(0);
});

test("Full diligence on a row opens the pair flow with its Results", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await runPreset(page);
  await rows(page).filter({ hasText: "Puma" }).getByRole("button", { name: /Full diligence/ }).click();

  await expect(page.getByRole("button", { name: "Compare a deal" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Acquirer")).toHaveValue("Nike");
  await expect(page.getByLabel("Target", { exact: true })).toHaveValue("Puma");
  await expect(page.getByTestId("results")).toBeVisible();
  await expect(page.getByTestId("memo")).toContainText("Nike + Puma");
  await expect(page.getByTestId("agent-Partner")).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId("screen-table")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a 429 stops the screen and marks the remaining rows", async ({ page }) => {
  await screenMode(page);
  let calls = 0;
  await page.route("**/api/diligence", async (route) => {
    calls++;
    if (calls === 1) return route.continue();
    await route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "Too many diligence runs from your network. Try again in a minute." }) });
  });
  await page.getByRole("button", { name: "Nike: 4 targets" }).click();
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(rows(page).filter({ hasText: "Too many diligence runs" })).toHaveCount(3);
  expect(calls).toBe(2);
});

const findButton = (page: Page) => page.getByRole("button", { name: /^Find(ing)? targets/ });

test("Find targets discovers Nike's candidates and screens them with recorded data", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Nike");
  const box = await findButton(page).boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  await findButton(page).focus();
  await expect(findButton(page)).toBeFocused();
  await findButton(page).click();
  await expect(findButton(page)).toBeDisabled();

  await expect(page.getByTestId("screen-found")).toHaveText("Found by Qloo: Nike's top 5 consumer-brand affinities");
  await expect(page.getByLabel("Candidate targets")).toHaveValue(/Adidas/);
  await expect(rows(page)).toHaveCount(5);
  const reasons = rows(page).getByTestId("screen-reason");
  await expect(reasons).toHaveCount(5);
  for (const text of await reasons.allTextContents()) expect(text).toMatch(/^(Shares .+|No shared categories) · affinity \d\.\d\d$/);
  await expect(page.getByLabel("Candidate targets")).not.toHaveValue(/Jordan/);
  await expect(page.getByText("Screening…")).toHaveCount(0);
  await expect(findButton(page)).toBeEnabled();
  await expect(rows(page).getByTestId("screen-bci")).toHaveCount(5); // every row finished with recorded data
  const scores = await bci(page);
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
  await expect(page.getByRole("status").filter({ hasText: "Recorded Qloo data" })).toHaveCount(1);
  await expect(inlineAlert(page)).toHaveCount(0);
  await page.screenshot({ path: "test-results/find-targets.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("Find targets with an unknown acquirer shows the friendly alert", async ({ page }) => {
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Zzqx Nonbrand");
  await findButton(page).click();
  await expect(inlineAlert(page)).toContainText("Qloo has no brand named");
  await expect(rows(page)).toHaveCount(0);
  await expect(findButton(page)).toBeEnabled();
});

test("Find targets shows a 429 from discovery", async ({ page }) => {
  await page.route("**/api/discover", (route) =>
    route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "Too many diligence runs from your network. Try again in a minute." }) }),
  );
  await screenMode(page);
  await page.getByLabel("Acquirer").fill("Nike");
  await findButton(page).click();
  await expect(inlineAlert(page)).toContainText("Too many diligence runs");
});

test("390px: the screening table has no horizontal overflow and keeps usable touch targets", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await runPreset(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  for (const btn of [screenButton(page), page.getByRole("button", { name: "Culture clash" }), rows(page).first().getByRole("button", { name: /Full diligence/ })]) {
    const box = await btn.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(36);
  }
  await page.screenshot({ path: "e2e/screenshots/screen-mobile.png", fullPage: true });
});
