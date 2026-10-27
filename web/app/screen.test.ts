import { describe, expect, test } from "bun:test";
import { discoveryLine, parseTargets, rankRows, recordedReason, rowsFromScreen, type Row } from "./screen";

describe("rowsFromScreen", () => {
  test("maps ok rows to done and error rows to error, in order", () => {
    const rows = rowsFromScreen([
      { target: "Adidas", ok: true, bci: 70, clash: 20, churn: "low", verdict: "Proceed", recorded: "why" },
      { target: "Zzqx", ok: false, status: 422, detail: "Qloo has no brand named Zzqx." },
    ]);
    expect(rows).toEqual([
      { target: "Adidas", state: "done", bci: 70, clash: 20, churn: "low", verdict: "Proceed", recorded: "why" },
      { target: "Zzqx", state: "error", error: "Qloo has no brand named Zzqx." },
    ]);
  });
});

describe("discoveryLine", () => {
  test("names the acquirer and counts the candidates", () => {
    expect(discoveryLine("Nike", 5)).toBe("Found by Qloo: Nike's top 5 consumer-brand affinities");
  });

  test("is singular for one candidate", () => {
    expect(discoveryLine("Nike", 1)).toBe("Found by Qloo: Nike's top consumer-brand affinity");
  });
});

const done = (target: string, bci: number, clash: number): Row => ({
  target,
  state: "done",
  bci,
  clash,
  churn: "medium",
  verdict: "Proceed",
});

describe("recordedReason", () => {
  test("is null when every finished row is live", () => {
    expect(recordedReason([done("A", 1, 1), { target: "B", state: "pending" }])).toBeNull();
  });

  test("is the reason of the first recorded finished row", () => {
    const rows: Row[] = [{ target: "B", state: "pending" }, done("A", 1, 1), { target: "C", state: "done", bci: 2, clash: 2, churn: "low", verdict: "Pass", recorded: "why" }];
    expect(recordedReason(rows)).toBe("why");
  });
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
