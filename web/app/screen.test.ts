import { describe, expect, test } from "bun:test";
import { parseTargets, rankRows, type Row } from "./screen";

const done = (target: string, bci: number, clash: number): Row => ({
  target,
  state: "done",
  bci,
  clash,
  churn: "medium",
  verdict: "Proceed",
});

describe("parseTargets", () => {
  test("splits on commas and newlines, trims and drops empties", () => {
    expect(parseTargets(" Adidas, Puma\n\nGucci ,, ", "Nike")).toEqual({ targets: ["Adidas", "Puma", "Gucci"], error: null });
  });

  test("dedupes case-insensitively, keeping the first spelling", () => {
    expect(parseTargets("Adidas, adidas, ADIDAS, Puma", "Nike").targets).toEqual(["Adidas", "Puma"]);
  });

  test("drops the acquirer itself", () => {
    expect(parseTargets("nike, Adidas, Puma", " Nike ").targets).toEqual(["Adidas", "Puma"]);
  });

  test("fewer than 2 targets is an error", () => {
    for (const raw of ["", "  ,\n ", "Adidas", "Adidas, adidas", "Nike, Adidas"]) {
      const r = parseTargets(raw, "Nike");
      expect(r.error).toMatch(/at least 2/i);
    }
  });

  test("more than 5 targets is an error", () => {
    const r = parseTargets("a, b, c, d, e, f", "Nike");
    expect(r.error).toMatch(/at most 5/i);
  });

  test("exactly 2 and exactly 5 are fine", () => {
    expect(parseTargets("a, b", "Nike").error).toBeNull();
    expect(parseTargets("a, b, c, d, e", "Nike").error).toBeNull();
  });

  test("6 entries that dedupe to 5 are fine", () => {
    expect(parseTargets("a, b, c, d, e, A", "Nike")).toEqual({ targets: ["a", "b", "c", "d", "e"], error: null });
  });
});

describe("rankRows", () => {
  const rows: Row[] = [
    { target: "Pending", state: "pending" },
    done("Low", 30, 60),
    { target: "Broken", state: "error", error: "nope" },
    done("High", 70, 20),
    done("Mid", 50, 40),
  ];

  test("bci sorts descending with finished rows above pending and error rows", () => {
    expect(rankRows(rows, "bci").map((r) => r.target)).toEqual(["High", "Mid", "Low", "Pending", "Broken"]);
  });

  test("clash sorts ascending, lowest clash first", () => {
    expect(rankRows(rows, "clash").map((r) => r.target)).toEqual(["High", "Mid", "Low", "Pending", "Broken"]);
    const flipped = [done("A", 80, 50), done("B", 40, 10), done("C", 60, 30)];
    expect(rankRows(flipped, "clash").map((r) => r.target)).toEqual(["B", "C", "A"]);
  });

  test("bci ties break on lower clash", () => {
    const tied = [done("A", 50, 60), done("B", 50, 20), done("C", 50, 40)];
    expect(rankRows(tied, "bci").map((r) => r.target)).toEqual(["B", "C", "A"]);
  });

  test("clash ties break on higher bci", () => {
    const tied = [done("A", 40, 30), done("B", 60, 30)];
    expect(rankRows(tied, "clash").map((r) => r.target)).toEqual(["B", "A"]);
  });

  test("pending and error rows keep their input order and the input is not mutated", () => {
    const input: Row[] = [{ target: "P2", state: "pending" }, { target: "E", state: "error", error: "x" }, done("D", 1, 1), { target: "P1", state: "pending" }];
    const copy = [...input];
    expect(rankRows(input, "bci").map((r) => r.target)).toEqual(["D", "P2", "E", "P1"]);
    expect(input).toEqual(copy);
  });
});
