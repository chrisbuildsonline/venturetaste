"use client";

import { useEffect, useState } from "react";
import Results from "./Results";
import ScreenTable from "./ScreenTable";
import { parseTargets, type Row } from "./screen";
import { AGENTS, type Diligence, type Preset, type Screen, type TraceStep } from "./types";

const AGENT_ROLES: Record<(typeof AGENTS)[number], string> = {
  Scout: "Resolves both brands in the Qloo taste graph",
  Cartographer: "Maps tastes and audiences across 7 domains",
  Analyst: "Scores overlap, culture clash and churn risk",
  Partner: "Writes the deal memo",
};

function errorText(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d as { msg?: string }).msg).filter(Boolean);
    if (msgs.length) return `Check the brand names: ${msgs.join("; ")}`;
  }
  return `The diligence run failed (HTTP ${status}). Try again.`;
}

const INPUT =
  "w-full rounded-xl border border-white/15 bg-black/30 px-4 py-3 text-base text-white placeholder:text-zinc-500 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-400/40";

export default function Home() {
  const [acquirer, setAcquirer] = useState("");
  const [target, setTarget] = useState("");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Diligence | null>(null);
  const [trace, setTrace] = useState<TraceStep[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [mode, setMode] = useState<"pair" | "screen">("pair");
  const [targetsText, setTargetsText] = useState("");
  const [screens, setScreens] = useState<Screen[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [screenAcquirer, setScreenAcquirer] = useState("");
  const [screening, setScreening] = useState(false);

  useEffect(() => {
    fetch("/api/presets")
      .then((r) => (r.ok ? r.json() : []))
      .then(setPresets)
      .catch(() => setPresets([]));
    fetch("/api/screens")
      .then((r) => (r.ok ? r.json() : []))
      .then(setScreens)
      .catch(() => setScreens([]));
  }, []);

  function show(d: Diligence) {
    setData(d);
    setTrace(d.trace);
    setActive(null);
  }

  /** Reads the SSE body, updating the agent cards live. Returns "fallback" if there is nothing usable to read. */
  async function streamRun(res: Response | null): Promise<"handled" | "fallback"> {
    if (!res?.body) return "fallback";
    if (!res.ok) {
      setError(errorText(await res.json().catch(() => null), res.status));
      return "handled";
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finished = false;
    const handle = (frame: string) => {
      let event = "message";
      let payload = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) payload += line.slice(5).trim();
      }
      if (!payload) return;
      const data: unknown = JSON.parse(payload);
      if (event === "agent") {
        const step = data as TraceStep;
        if (step.status === "running") setActive(step.agent);
        else setTrace((prev) => [...prev, step]);
      } else if (event === "result") {
        show(data as Diligence);
        finished = true;
      } else if (event === "error") {
        setError(errorText(data, (data as { status?: number }).status ?? 0));
        setActive(null);
        finished = true;
      }
    };
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      frames.forEach(handle);
      if (done) break;
    }
    if (buffer.trim()) handle(buffer);
    return finished ? "handled" : "fallback";
  }

  async function run(a: string, t: string) {
    const body = { acquirer: a.trim(), target: t.trim() };
    setError(null);
    if (!body.acquirer || !body.target) {
      setError("Enter both an acquirer and a target brand.");
      return;
    }
    if (body.acquirer.toLowerCase() === body.target.toLowerCase()) {
      setError(`Pick two different brands: ${body.acquirer} and ${body.target} are the same.`);
      return;
    }
    setData(null);
    setTrace([]);
    setActive(AGENTS[0]);
    setRunning(true);
    const post = (path: string) =>
      fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    try {
      const outcome = await streamRun(await post("/api/diligence/stream").catch(() => null));
      if (outcome === "fallback") {
        const res = await post("/api/diligence");
        const json: unknown = await res.json().catch(() => null);
        if (!res.ok) setError(errorText(json, res.status));
        else show(json as Diligence);
      }
    } catch {
      setError("Could not reach the VentureTaste API. Check your connection and try again.");
    } finally {
      setRunning(false);
    }
  }

  function pick(p: Preset) {
    setAcquirer(p.acquirer);
    setTarget(p.target);
    void run(p.acquirer, p.target);
  }

  function switchMode(next: "pair" | "screen") {
    setMode(next);
    setError(null);
  }

  /** Screens one target at a time (each run already fans out 6 Qloo threads), filling the rows as they finish. */
  async function screen(a: string, raw: string) {
    const acq = a.trim();
    setError(null);
    if (!acq) {
      setError("Enter an acquirer brand.");
      return;
    }
    const parsed = parseTargets(raw, acq);
    if (parsed.error) {
      setError(parsed.error);
      return;
    }
    const names = parsed.targets;
    const put = (i: number, row: Row) => setRows((prev) => prev.map((r, j) => (j === i ? row : r)));
    setScreenAcquirer(acq);
    setRows(names.map((t) => ({ target: t, state: "pending" })));
    setScreening(true);
    try {
      for (const [i, t] of names.entries()) {
        let res: Response;
        try {
          res = await fetch("/api/diligence", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acquirer: acq, target: t }) });
        } catch {
          put(i, { target: t, state: "error", error: "Could not reach the VentureTaste API. Check your connection and try again." });
          continue;
        }
        const json: unknown = await res.json().catch(() => null);
        if (res.ok) {
          const d = json as Diligence;
          put(i, { target: t, state: "done", bci: d.scores.bci, clash: d.scores.culture_clash, churn: d.scores.churn_risk, verdict: d.memo.verdict, recorded: d.recorded?.reason });
        } else if (res.status === 429) {
          const msg = errorText(json, res.status);
          setRows((prev) => prev.map((r, j) => (j >= i ? { target: r.target, state: "error", error: msg } : r)));
          break;
        } else {
          put(i, { target: t, state: "error", error: errorText(json, res.status) });
        }
      }
    } finally {
      setScreening(false);
    }
  }

  function pickScreen(s: Screen) {
    setAcquirer(s.acquirer);
    setTargetsText(s.targets.join(", "));
    void screen(s.acquirer, s.targets.join(", "));
  }

  function fullDiligence(t: string) {
    setMode("pair");
    setAcquirer(screenAcquirer);
    setTarget(t);
    void run(screenAcquirer, t);
  }

  const busy = running || screening;
  const showProgress = mode === "pair" && (running || data !== null);

  return (
    <main className="mx-auto max-w-5xl px-4 pb-20 pt-10 sm:px-6 sm:pt-16">
      <header className="mb-8 sm:mb-10">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-indigo-300">Powered by Qloo taste data</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">VentureTaste</h1>
        <p className="mt-3 max-w-2xl text-lg text-zinc-300">Taste-graph due diligence for consumer brand deals</p>
      </header>

      <div role="group" aria-label="Mode" className="mb-3 inline-flex rounded-xl border border-white/15 p-1">
        {(["pair", "screen"] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            disabled={busy}
            onClick={() => switchMode(m)}
            className={`min-h-10 rounded-lg px-4 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed ${mode === m ? "bg-indigo-500 text-white" : "text-zinc-300 hover:text-white"}`}
          >
            {m === "pair" ? "Compare a deal" : "Screen targets"}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void (mode === "pair" ? run(acquirer, target) : screen(acquirer, targetsText));
        }}
        className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6"
        noValidate
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="acquirer" className="mb-2 block text-sm font-medium text-zinc-200">Acquirer</label>
            <input id="acquirer" className={INPUT} value={acquirer} onChange={(e) => setAcquirer(e.target.value)} placeholder="e.g. Nike" autoComplete="off" maxLength={100} />
          </div>
          {mode === "pair" ? (
            <div>
              <label htmlFor="target" className="mb-2 block text-sm font-medium text-zinc-200">Target</label>
              <input id="target" className={INPUT} value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. Adidas" autoComplete="off" maxLength={100} />
            </div>
          ) : (
            <div>
              <label htmlFor="targets" className="mb-2 block text-sm font-medium text-zinc-200">Candidate targets</label>
              <textarea id="targets" className={INPUT} rows={3} value={targetsText} onChange={(e) => setTargetsText(e.target.value)} placeholder="2 to 5 brands, comma or line separated" />
            </div>
          )}
        </div>
        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-indigo-500 px-6 py-3 text-base font-semibold text-white transition hover:bg-indigo-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {mode === "pair" ? (running ? "Running diligence…" : "Run diligence") : screening ? "Screening targets…" : "Screen targets"}
          </button>
          {(mode === "pair" ? presets.length : screens.length) > 0 && (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={mode === "pair" ? "Preset deals" : "Preset screens"}>
              <span className="text-sm text-zinc-400">{mode === "pair" ? "Try a deal:" : "Try a screen:"}</span>
              {(mode === "pair" ? presets : screens).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  disabled={busy}
                  onClick={() => ("target" in p ? pick(p) : pickScreen(p))}
                  className="rounded-full border border-white/15 px-3.5 py-1.5 text-sm text-zinc-200 transition hover:border-indigo-300 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </div>
        {error && (
          <p role="alert" className="mt-5 rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </p>
        )}
      </form>

      {showProgress && (
        <section aria-label="Agent progress" className="mt-5 rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">Diligence agents</h2>
          <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {AGENTS.map((name) => {
              const step = trace.find((t) => t.agent === name);
              const done = Boolean(step);
              const waiting = !done && active !== name && !data;
              return (
                <li key={name} data-testid={`agent-${name}`} data-state={done ? "done" : waiting ? "waiting" : "running"} className={`rounded-xl border border-white/10 bg-black/20 p-4 ${waiting ? "opacity-60" : ""}`}>
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <span aria-hidden className={done ? "text-emerald-300" : waiting ? "inline-block size-2.5 rounded-full bg-zinc-600" : "inline-block size-2.5 animate-pulse rounded-full bg-indigo-400"}>{done ? "✓" : ""}</span>
                    {name}
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">{AGENT_ROLES[name]}</p>
                  <p className="mt-2 text-xs tabular-nums text-zinc-300">
                    {step ? `Done · ${step.ms} ms · ${step.qloo_calls} Qloo ${step.qloo_calls === 1 ? "call" : "calls"}` : waiting ? "Waiting" : "Running…"}
                  </p>
                  {step?.decision && <p data-testid={`decision-${name}`} className="mt-2 text-xs text-indigo-200">{step.decision}</p>}
                  {step?.planner && (
                    <p data-testid={`planner-${name}`} title={step.fallback} className="mt-1 text-xs text-zinc-400">
                      {step.planner === "llm" ? `${name === "Partner" ? "Memo by" : "Decided by"} ${step.model}` : step.planner === "rule" ? "Rule-based fallback" : "Template memo"}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <div className="mt-5" aria-live="polite">
        {mode === "screen" && rows.length > 0 && <ScreenTable acquirer={screenAcquirer} rows={rows} onFull={fullDiligence} />}
        {mode === "screen" && rows.length === 0 && !error && (
          <div data-testid="screen-empty" className="rounded-2xl border border-dashed border-white/15 px-6 py-14 text-center">
            <p className="text-lg font-medium text-white">Which acquisition target fits best?</p>
            <p className="mx-auto mt-2 max-w-xl text-sm text-zinc-400">
              Enter an acquirer and 2 to 5 candidate targets. Each one gets a full taste-graph diligence, one after another, and the table ranks them. Screening 5 targets counts as 5 diligence runs against the rate limit.
            </p>
          </div>
        )}
        {mode === "pair" && data && <Results data={data} />}
        {mode === "pair" && !data && !running && !error && (
          <div data-testid="empty-state" className="rounded-2xl border border-dashed border-white/15 px-6 py-14 text-center">
            <p className="text-lg font-medium text-white">Is this deal a cannibalization trap or a cross-sell win?</p>
            <p className="mx-auto mt-2 max-w-xl text-sm text-zinc-400">
              Enter an acquirer and a target, or pick a preset deal. Four agents compare the two audiences on Qloo&apos;s taste graph and hand back a
              Brand Cannibalization Index, a culture clash score and a deal memo.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
