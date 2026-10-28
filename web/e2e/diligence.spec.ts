import { readFileSync } from "node:fs";
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
  const banner = page.getByRole("status").filter({ hasText: "Recorded Qloo data" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("This server runs in fixture mode: recorded Qloo answers, no live calls.");
  await expect(page.getByTestId("churn-band")).toContainText(/medium/i);
  await expect(page.getByTestId("clash-value")).toBeVisible();
  await expect(page.locator("[data-testid=radar] svg").first()).toBeVisible();
  await expect(page.getByTestId("radar-value")).toHaveCount(7);
  await expect(page.getByTestId("radar-value").first()).toHaveText(/^\d+%$/);
  await expect(page.getByTestId("radar-empty-caption")).toHaveCount(0);
  await expect(page.locator("[data-testid=radar] .radar-baseline")).toHaveCount(0);
  await expect(page.getByTestId("no-shared-taste")).toHaveCount(0);
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
  // every radar axis label must sit inside the radar container (no clipped "estinations")
  await expect
    .poll(async () => {
      const container = await page.getByTestId("radar").boundingBox();
      const labels = page.locator("[data-testid=radar] .recharts-polar-angle-axis-tick text");
      const n = await labels.count();
      let outside = n === 0 ? 1 : 0;
      for (let i = 0; i < n; i++) {
        const b = await labels.nth(i).boundingBox();
        if (!b || !container || b.x < container.x || b.x + b.width > container.x + container.width) outside++;
      }
      return outside;
    })
    .toBe(0);
  await page.screenshot({ path: "e2e/screenshots/mobile.png", fullPage: true });

  expect(errors).toEqual([]);
});

test("after a run the verdict and radar sit in a 1280x800 viewport and the memo downloads", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByTestId("bci-value")).toHaveText("53.9");

  // no manual scrolling: the results scroll themselves into view
  await expect
    .poll(async () => {
      for (const id of ["verdict", "radar"]) {
        const b = await page.getByTestId(id).boundingBox();
        if (!b || b.y < 0 || b.x < 0 || b.y + b.height > 800 || b.x + b.width > 1280) return id;
      }
      return "ok";
    })
    .toBe("ok");
  const verdict = (await page.getByTestId("verdict").boundingBox())!;
  const radar = (await page.getByTestId("radar").boundingBox())!;
  expect(verdict.x + verdict.width).toBeLessThanOrEqual(radar.x); // side by side
  await page.screenshot({ path: "e2e/screenshots/above-the-fold.png" });

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download memo (.md)" }).click();
  const file = await downloadPromise;
  expect(file.suggestedFilename()).toBe("venturetaste-nike-adidas.md");
  const text = readFileSync((await file.path())!, "utf8");
  expect(text).toContain("**Verdict:** Proceed");
  expect(text).toContain("53.9 / 100");
  expect(text).toContain("recorded Qloo data");
  expect(text).toContain("recorded qwen2.5:7b");
  expect(errors).toEqual([]);
});

test("Patagonia + Gucci shows the no shared taste state and a Pass", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + Gucci" }).click();

  await expect(page.getByTestId("verdict")).toHaveText("Pass");
  // the radar always renders: all 7 axes, each with its percent, and a caption when nothing overlaps
  await expect(page.locator("[data-testid=radar] svg").first()).toBeVisible();
  await expect(page.locator("[data-testid=radar] .recharts-polar-angle-axis-tick text")).toHaveCount(7);
  const values = page.getByTestId("radar-value");
  await expect(values).toHaveCount(7);
  for (let i = 0; i < 7; i++) await expect(values.nth(i)).toHaveText("0%");
  await expect(page.getByTestId("no-shared-taste")).toBeVisible();
  await expect(page.getByTestId("no-shared-taste")).toHaveText(
    "No shared taste in any domain: the audiences don't overlap.",
  );
  // the empty radar is not a bare dot: a dashed baseline ring and a caption on the chart itself
  await expect(page.getByTestId("radar-empty-caption")).toBeVisible();
  await expect(page.getByTestId("radar-empty-caption")).toHaveText("No shared taste in any domain");
  await expect(page.locator("[data-testid=radar] .radar-baseline").first()).toBeAttached();
  await expect(page.getByTestId("memo")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/no-shared-taste.png", fullPage: true });

  expect(errors).toEqual([]);
});

test("Patagonia + Gucci: the Analyst probes tags and finds no real bridging taste", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + Gucci" }).click();

  // Their only shared tags are trivial ("Identifies as women-owned", "friendship"), which are filtered out.
  const decision = page.getByTestId("decision-Analyst");
  await expect(decision).toHaveText(/^Overlap 0 in 7\/7 domains → probed Qloo tags \(genre, lifestyle\): no bridging tastes found \(recorded qwen2\.5:7b: .+\)$/);
  await expect(page.getByTestId("agent-Analyst")).toContainText("recorded answers, no live Qloo calls");
  await expect(page.getByTestId("bridges")).toHaveCount(0);
  await expect(page.getByTestId("bridge-potential")).toBeVisible(); // a probe that found nothing still shows its score
  await expect(page.getByTestId("bridge-potential-value")).toHaveText("0");
  await expect(page.getByTestId("bridge-picks")).toHaveCount(0);
  await expect(page.getByTestId("memo")).toContainText("audiences share no tastes");
  expect(errors).toEqual([]);
});

test("the bridging tastes panel lists bridges and fits a phone", async ({ page }) => {
  const errors = watchErrors(page);
  await page.route("**/api/diligence/stream", (r) => r.abort());
  await page.route("**/api/diligence", async (route) => {
    const res = await route.fetch();
    const json = await res.json();
    json.bridges = [{ id: "urn:tag:keyword:qloo:sustainability", name: "sustainability", affinity_acquirer: 0.6, affinity_target: 0.5 }];
    await route.fulfill({ response: res, json });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + Gucci" }).click();
  const bridges = page.getByTestId("bridges");
  await expect(bridges).toContainText("Bridging tastes");
  expect(await bridges.locator("li").count()).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(bridges).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(0);
  expect(errors.filter((e) => !e.includes("net::ERR_FAILED"))).toEqual([]);
});

test("Nike + Adidas: the Analyst probes chosen tag families, scores the bridges and follows up in a domain", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();

  await expect(page.getByTestId("decision-Analyst")).toHaveText(
    /^Overlap 0 in 1\/7 domains → probed Qloo tags \([a-z_, ]+\): \d bridging tastes? → follow-up in [A-Za-z ]+: .+ \(recorded qwen2\.5:7b: .+\)$/,
  );
  await expect(page.getByTestId("agent-Analyst")).toContainText("recorded answers, no live Qloo calls");
  const potential = page.getByTestId("bridge-potential");
  await expect(potential).toBeVisible();
  await expect(potential).toContainText("Bridge potential");
  const value = Number(await page.getByTestId("bridge-potential-value").textContent());
  expect(value).toBeGreaterThan(0);
  expect(value).toBeLessThanOrEqual(100);
  expect(await page.getByTestId("bridges").locator("li").count()).toBeGreaterThan(0);
  const picks = page.getByTestId("bridge-picks");
  await expect(picks).toContainText("Follow-up: Destinations via");
  expect(await picks.locator("li").count()).toBeGreaterThan(0);
  await expect(page.getByTestId("bci-value")).toHaveText("53.9"); // the bridge potential never moves the BCI
  expect(errors).toEqual([]);
});

test("Patagonia + The North Face: no tag probe, so no bridge potential", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + The North Face" }).click();

  await expect(page.getByTestId("decision-Analyst")).toHaveText(/^Overlap in 7\/7 domains → no tag probe needed \(recorded qwen2\.5:7b: .+\)$/);
  await expect(page.getByTestId("bridge-potential")).toHaveCount(0);
  await expect(page.getByTestId("bridges")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("with the LLM off a preset replays a labelled recorded run for both agents", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();

  await expect(page.getByTestId("planner-Analyst")).toHaveText("Recorded qwen2.5:7b run");
  await expect(page.getByTestId("planner-Partner")).toHaveText("Recorded qwen2.5:7b run");
  await expect(page.getByTestId("decision-Analyst")).toContainText("(recorded qwen2.5:7b:");
  await expect(page.getByTestId("memo")).toBeVisible();
  expect(errors).toEqual([]);
});

test("with the LLM off a pair with no recording says it fell back to the rule and the template", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await page.getByLabel("Acquirer").fill("Adidas");
  await page.getByLabel("Target").fill("Nike");
  await page.getByRole("button", { name: "Run diligence" }).click();

  await expect(page.getByTestId("planner-Analyst")).toHaveText("Rule-based fallback");
  await expect(page.getByTestId("planner-Partner")).toHaveText("Template memo");
  await expect(page.getByTestId("planner-Partner")).toHaveAttribute("title", "LLM unreachable");
  await expect(page.getByTestId("memo")).toBeVisible();
  expect(errors).toEqual([]);
});

test("the Analyst decision shows in the non-stream fallback too", async ({ page }) => {
  await page.route("**/api/diligence/stream", (r) => r.abort());
  await page.goto("/");
  await page.getByRole("button", { name: "Patagonia + Gucci" }).click();
  await expect(page.getByTestId("decision-Analyst")).toContainText("probed Qloo tags");
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

  expect(errors).toEqual([]);
});

test("agent cards go live: waiting, running, done in order", async ({ page }) => {
  const errors = watchErrors(page);
  await page.addInitScript(() => {
    const w = window as unknown as { __states: string[] };
    w.__states = [];
    const seen = new Map<Element, string>();
    new MutationObserver(() => {
      for (const el of document.querySelectorAll("[data-testid^=agent-]")) {
        const state = el.getAttribute("data-state");
        if (state && seen.get(el) !== state) {
          seen.set(el, state);
          w.__states.push(`${el.getAttribute("data-testid")}:${state}`);
        }
      }
    }).observe(document, { subtree: true, attributes: true, childList: true });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByTestId("bci-value")).toHaveText("53.9");
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toHaveAttribute("data-state", "done");

  const states = await page.evaluate(() => (window as unknown as { __states: string[] }).__states);
  const done = states.filter((s) => s.endsWith(":done")).map((s) => s.slice(6, -5));
  expect(done).toEqual(AGENTS);
  expect(states).toContain("agent-Scout:running");
  expect(states).toContain("agent-Partner:waiting");
  expect(states.indexOf("agent-Scout:done")).toBeLessThan(states.indexOf("agent-Cartographer:done"));
  expect(errors).toEqual([]);
});

test("falls back to the plain POST when the stream is unavailable", async ({ page }) => {
  const errors = watchErrors(page);
  let streamTries = 0;
  await page.route("**/api/diligence/stream", (r) => {
    streamTries++;
    return r.abort();
  });
  await page.route("**/api/diligence", async (r) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await r.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(page.getByTestId("agent-Scout")).toHaveAttribute("data-state", "running");
  await expect(page.getByTestId("bci-value")).toHaveText("53.9");
  expect(streamTries).toBe(1);
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toHaveAttribute("data-state", "done");
  expect(errors.filter((e) => !e.includes("net::ERR_FAILED"))).toEqual([]); // the aborted stream request itself
});

const TOO_MANY = "Too many diligence runs from your network. Try again in a minute.";
const tooMany = { status: 429, headers: { "Retry-After": "42" }, json: { detail: TOO_MANY } };

test("a 429 from the stream shows the message and does not fall back", async ({ page }) => {
  const errors = watchErrors(page);
  let posts = 0;
  await page.route("**/api/diligence/stream", (r) => r.fulfill(tooMany));
  await page.route("**/api/diligence", (r) => {
    posts++;
    return r.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(inlineAlert(page)).toHaveText(TOO_MANY);
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();
  expect(posts).toBe(0);
  // the browser logs a failed-resource console error for any 4xx fetch; only that one is expected
  expect(errors.filter((e) => !e.includes("429"))).toEqual([]);
});

const UNAVAILABLE = "Taste data from Qloo is temporarily unavailable. Please try again in a moment.";

test("an upstream failure in the stream shows the friendly message", async ({ page }) => {
  const errors = watchErrors(page);
  await page.route("**/api/diligence/stream", (r) =>
    r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: agent\ndata: {"agent":"Scout","status":"running"}\n\nevent: error\ndata: ${JSON.stringify({ status: 502, detail: UNAVAILABLE })}\n\n`,
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(inlineAlert(page)).toHaveText(UNAVAILABLE);
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();
  expect(errors).toEqual([]);
});

test("a 502 from the plain POST shows the friendly message", async ({ page }) => {
  const errors = watchErrors(page);
  await page.route("**/api/diligence/stream", (r) => r.abort());
  await page.route("**/api/diligence", (r) => r.fulfill({ status: 502, json: { detail: UNAVAILABLE } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(inlineAlert(page)).toHaveText(UNAVAILABLE);
  expect(errors.filter((e) => !e.includes("502") && !e.includes("net::ERR_FAILED"))).toEqual([]);
});

test("a 422 no-key message from the plain POST shows the recorded brands", async ({ page }) => {
  const NO_KEY = "No Qloo API key is set on this server, so only recorded brands work: Adidas, Nike. Set QLOO_API_KEY to try any brand.";
  await page.route("**/api/diligence/stream", (r) => r.abort());
  await page.route("**/api/diligence", (r) => r.fulfill({ status: 422, json: { detail: NO_KEY } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(inlineAlert(page)).toHaveText(NO_KEY);
});

test("a 429 from the plain POST shows the message", async ({ page }) => {
  const errors = watchErrors(page);
  await page.route("**/api/diligence/stream", (r) => r.abort());
  await page.route("**/api/diligence", (r) => r.fulfill(tooMany));
  await page.goto("/");
  await page.getByRole("button", { name: "Nike + Adidas" }).click();
  await expect(inlineAlert(page)).toHaveText(TOO_MANY);
  expect(errors.filter((e) => !e.includes("429") && !e.includes("net::ERR_FAILED"))).toEqual([]);
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
