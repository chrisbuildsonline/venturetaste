import { describe, expect, test } from "bun:test";
import { narration } from "./narration";

const all = Object.values(narration("100", "20")).join(" ");

describe("demo video narration", () => {
  test("never mentions the trivial bridges the tag filter drops", () => {
    expect(all).not.toMatch(/women-owned|friendship/i);
  });

  test("covers Find targets and the export", () => {
    expect(all).toMatch(/find targets/i);
    expect(all).toMatch(/export|download/i);
    expect(all).toMatch(/markdown/i);
  });

  test("does not claim there is no LLM (a recorded or local model plans and writes the memo)", () => {
    expect(all).not.toMatch(/no LLM anywhere/i);
  });

  test("the slides do not say there is no LLM either", async () => {
    const source = await Bun.file(new URL("./demo-video.ts", import.meta.url)).text();
    expect(source).not.toMatch(/no LLM|From templates/);
  });
});
