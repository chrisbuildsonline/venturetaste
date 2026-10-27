export const MIN_TARGETS = 2;
export const MAX_TARGETS = 5;

export type Row =
  | { target: string; state: "pending" }
  | { target: string; state: "error"; error: string }
  | { target: string; state: "done"; bci: number; clash: number; churn: string; verdict: string; recorded?: string };

export type SortKey = "bci" | "clash";

export function parseTargets(raw: string, acquirer: string): { targets: string[]; error: string | null } {
  const skip = new Set([acquirer.trim().toLowerCase()]);
  const targets: string[] = [];
  for (const part of raw.split(/[,\n]/)) {
    const name = part.trim();
    if (!name || skip.has(name.toLowerCase())) continue;
    skip.add(name.toLowerCase());
    targets.push(name);
  }
  if (targets.length < MIN_TARGETS) return { targets, error: `Enter at least ${MIN_TARGETS} different candidate targets, separated by commas or new lines.` };
  if (targets.length > MAX_TARGETS) return { targets, error: `Screen at most ${MAX_TARGETS} targets at a time. Remove ${targets.length - MAX_TARGETS}.` };
  return { targets, error: null };
}

/** The line above the table after "Find targets". */
export function discoveryLine(acquirer: string, count: number): string {
  return `Found by Qloo: ${acquirer}'s top ${count === 1 ? "" : `${count} `}consumer-brand ${count === 1 ? "affinity" : "affinities"}`;
}

/** The reason of the first finished row that came from recorded Qloo data, or null when every row is live. */
export function recordedReason(rows: Row[]): string | null {
  for (const r of rows) if (r.state === "done" && r.recorded) return r.recorded;
  return null;
}

/** Finished rows first, sorted by the key (bci high to low, clash low to high, the other as tie-break); pending and error rows keep their order. */
export function rankRows(rows: Row[], key: SortKey): Row[] {
  const finished = rows.filter((r): r is Extract<Row, { state: "done" }> => r.state === "done");
  const rest = rows.filter((r) => r.state !== "done");
  finished.sort((a, b) => (key === "bci" ? b.bci - a.bci || a.clash - b.clash : a.clash - b.clash || b.bci - a.bci));
  return [...finished, ...rest];
}
