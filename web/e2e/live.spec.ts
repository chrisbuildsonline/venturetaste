import path from "node:path";
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
  await expect(page.getByTestId("recorded-banner")).toHaveCount(0); // live data, not a replay
  await expect(page.getByTestId("verdict")).toBeVisible();
  await expect(page.getByTestId("memo")).toContainText("Nike + Adidas");
  for (const agent of AGENTS) await expect(page.getByTestId(`agent-${agent}`)).toHaveAttribute("data-state", "done");
  await expect(page.getByRole("button", { name: "Run diligence" })).toBeEnabled();

  const scout = page.getByTestId("agent-Scout");
  await expect(scout).toContainText(/Qloo calls?/);
  const calls = Number((await scout.innerText()).match(/(\d+) Qloo calls?/)?.[1]);
  expect(calls).toBeGreaterThan(0);

  await page.screenshot({ path: path.resolve(__dirname, "../../docs/live-qloo-run.png"), fullPage: true });

  expect(errors).toEqual([]);
});

test("live: the proxy streams SSE events as they happen instead of buffering them", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  const arrivals = await page.evaluate(async () => {
    const t0 = performance.now();
    const res = await fetch("/api/diligence/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acquirer: "Patagonia", target: "Gucci" }),
    });
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    const out: { ms: number; events: string[] }[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const events = [...decoder.decode(value, { stream: true }).matchAll(/^event: (\w+)$/gm)].map((m) => m[1]);
      out.push({ ms: Math.round(performance.now() - t0), events });
    }
    return { status: res.status, type: res.headers.get("content-type"), chunks: out };
  });
  console.log(JSON.stringify(arrivals.chunks));

  expect(arrivals.status).toBe(200);
  expect(arrivals.type).toContain("text/event-stream");
  const all = arrivals.chunks.flatMap((c) => c.events);
  expect(all.at(-1)).toBe("result");
  const first = arrivals.chunks.find((c) => c.events.includes("agent"))!;
  const last = arrivals.chunks.find((c) => c.events.includes("result"))!;
  expect(arrivals.chunks.length).toBeGreaterThan(1);
  expect(first.ms).toBeLessThan(last.ms);
  expect(first.events).not.toContain("result");
});
