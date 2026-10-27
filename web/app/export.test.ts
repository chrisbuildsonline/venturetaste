import { describe, expect, test } from "bun:test";
import { memoFilename, memoMarkdown, screenFilename, screenMarkdown } from "./export";
import type { Row } from "./screen";
import type { Diligence } from "./types";

const base: Diligence = {
  brands: { acquirer: { query: "nike", id: "a", name: "Nike", popularity: 1 }, target: { query: "adidas", id: "b", name: "Adidas", popularity: 1 } },
  scores: { bci: 53.9, culture_clash: 41.2, churn_risk: "medium", demographic_distance: 0.3 },
  domain_overlap: { brand: 0.5, tv_show: 0.25 },
  top_shared: [],
  top_clashing: { acquirer: [], target: [] },
  demographics: { acquirer: { age: {}, gender: {} }, target: { age: {}, gender: {} } },
  bridges: [],
  probed_tags: false,
  memo: { verdict: "Proceed", headline: "Nike + Adidas overlap a lot", rationale: ["Shared sneaker fans"], risks: ["Cannibalization"], author: "qwen2.5:7b" },
  trace: [],
};
const date = new Date("2026-10-27T12:00:00Z");

describe("memoMarkdown", () => {
  const md = memoMarkdown(base, date);

  test("has the pair, verdict, headline and scores", () => {
    expect(md).toContain("# Deal memo: Nike + Adidas");
    expect(md).toContain("**Verdict:** Proceed");
    expect(md).toContain("Nike + Adidas overlap a lot");
    expect(md).toContain("**Brand Cannibalization Index:** 53.9 / 100");
    expect(md).toContain("**Culture clash:** 41.2%");
  });

  test("has the overlap table, rationale and risks", () => {
    expect(md).toContain("| Domain | Overlap |");
    expect(md).toContain("| Brands | 50% |");
    expect(md).toContain("| TV shows | 25% |");
    expect(md).toContain("- Shared sneaker fans");
    expect(md).toContain("- Cannibalization");
  });

  test("live case: names the model, live Qloo data and the date", () => {
    expect(md).toContain("**Memo written by:** qwen2.5:7b");
    expect(md).toContain("**Data source:** live Qloo");
    expect(md).toContain("**Date:** 2026-10-27");
  });

  test("recorded case: labels the recorded run and recorded Qloo data", () => {
    const rec = memoMarkdown({ ...base, memo: { ...base.memo, author: "recorded qwen2.5:7b" }, recorded: { reason: "fixture mode" } }, date);
    expect(rec).toContain("**Memo written by:** recorded qwen2.5:7b");
    expect(rec).toContain("**Data source:** recorded Qloo data (fixture mode)");
  });

  test("template case", () => {
    expect(memoMarkdown({ ...base, memo: { ...base.memo, author: undefined } }, date)).toContain("**Memo written by:** template");
  });
});

describe("screenMarkdown", () => {
  const rows: Row[] = [
    { target: "Low", state: "done", bci: 30, clash: 60, churn: "high", verdict: "Pass" },
    { target: "Broken", state: "error", error: "no brand" },
    { target: "High", state: "done", bci: 70.25, clash: 20, churn: "low", verdict: "Proceed" },
  ];
  const md = screenMarkdown(rows, "Nike", date);

  test("ranks finished rows by BCI with the table columns", () => {
    expect(md).toContain("| Rank | Target | BCI | Culture clash | Churn risk | Verdict |");
    expect(md).toContain("| 1 | High | 70.3 | 20.0% | Low | Proceed |");
    expect(md).toContain("| 2 | Low | 30.0 | 60.0% | High | Pass |");
    expect(md.indexOf("High")).toBeLessThan(md.indexOf("| 2 | Low"));
  });

  test("unfinished rows show a dash and the error", () => {
    expect(md).toContain("| – | Broken | no brand |");
  });

  test("names the acquirer and the date", () => {
    expect(md).toContain("# Nike screened against 3 targets");
    expect(md).toContain("2026-10-27");
  });
});

describe("filenames", () => {
  test("slugged", () => {
    expect(memoFilename(base)).toBe("venturetaste-nike-adidas.md");
    expect(screenFilename("Louis Vuitton")).toBe("venturetaste-screen-louis-vuitton.md");
  });
});
