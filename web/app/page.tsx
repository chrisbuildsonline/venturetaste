"use client";

import { useEffect, useState } from "react";
import Backtest from "./Backtest";
import Results from "./Results";
import ScreenTable from "./ScreenTable";
import { discoveryLine, MIN_TARGETS, parseTargets, rowsFromScreen, type Found, type Row, type ScreenRow } from "./screen";
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
  const [finding, setFinding] = useState(false);
  const [found, setFound] = useState<Found | null>(null);

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

  /** Screens every target in ONE request (the server runs them in parallel and counts one rate-limit hit); rows stay pending until it answers. */
  async function screen(a: string, raw: string, from: typeof found = null) {
    const acq = a.trim();
    setError(null);
    setFound(from);
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
    const failAll = (error: string) => setRows(names.map((t) => ({ target: t, state: "error", error })));
    setScreenAcquirer(acq);
    setRows(names.map((t) => ({ target: t, state: "pending" })));
    setScreening(true);
    try {
      let res: Response;
      try {
        res = await fetch("/api/screen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acquirer: acq, targets: names }) });
      } catch {
        failAll("Could not reach the VentureTaste API. Check your connection and try again.");
        return;
      }
      const json: unknown = await res.json().catch(() => null);
      if (res.ok && Array.isArray((json as { rows?: unknown } | null)?.rows)) setRows(rowsFromScreen((json as { rows: ScreenRow[] }).rows));
      else failAll(errorText(json, res.status));
    } finally {
      setScreening(false);
    }
  }

  function pickScreen(s: Screen) {
    setAcquirer(s.acquirer);
    setTargetsText(s.targets.join(", "));
    void screen(s.acquirer, s.targets.join(", "));
  }

  /** Asks Qloo for the acquirer's closest brands, then screens them in one parallel request. */
  async function findTargets() {
    const acq = acquirer.trim();
    setError(null);
    if (!acq) {
      setError("Enter an acquirer brand.");
      return;
    }
    setFinding(true);
    try {
      let res: Response;
      try {
        res = await fetch("/api/discover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acquirer: acq }) });
      } catch {
        setError("Could not reach the VentureTaste API. Check your connection and try again.");
        return;
      }
      const json: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        setError(errorText(json, res.status));
        return;
      }
      const d = json as { acquirer: string; candidates: { name: string; reason?: string }[]; recorded?: { reason: string } };
      const names = d.candidates.map((c) => c.name);
      if (names.length < MIN_TARGETS) {
        setError(`Qloo found fewer than ${MIN_TARGETS} other brands for ${d.acquirer}. Type the targets yourself.`);
        return;
      }
      const text = names.join(", ");
      setTargetsText(text);
      const reasons = Object.fromEntries(d.candidates.flatMap((c) => (c.reason ? [[c.name, c.reason]] : [])));
      await screen(acq, text, { line: discoveryLine(d.acquirer, names.length), recorded: d.recorded?.reason, reasons });
    } finally {
      setFinding(false);
    }
  }

  function fullDiligence(t: string) {
    setMode("pair");
    setAcquirer(screenAcquirer);
    setTarget(t);
    void run(screenAcquirer, t);
  }

  const busy = running || screening || finding;
  const showProgress = mode === "pair" && (running || data !== null);

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/[0.07] pb-5">
        <div className="flex items-center gap-3">
          <Mark />
          <div>
            <h1 className="text-[1.05rem] font-semibold tracking-tight text-white">VentureTaste</h1>
            <p className="text-xs text-zinc-400">Taste-graph due diligence for consumer brand deals</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
          <span className="pill bg-lime/10 text-lime">Powered by Qloo Taste AI</span>
          <span className="hidden rounded-full border border-white/10 px-3 py-1.5 sm:inline">4 agents · 7 taste domains · 18 Qloo calls per run</span>
          <a href="https://github.com/chrisbuildsonline/venturetaste" target="_blank" rel="noreferrer" className="btn btn-ghost min-h-11! px-3.5! text-xs">
            Source
          </a>
        </div>
      </header>

      <section className="relative mt-10 sm:mt-14">
        <svg aria-hidden className="pointer-events-none absolute -right-10 -top-24 hidden h-[26rem] w-[40rem] text-lime opacity-[0.07] lg:block" viewBox="0 0 640 416" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="250" cy="208" r="170" />
          <circle cx="390" cy="208" r="170" />
          <path d="M320 73a170 170 0 0 1 0 270a170 170 0 0 1 0-270z" fill="currentColor" stroke="none" />
        </svg>
        <p className="display text-[2.5rem] leading-[1.02] text-white sm:text-[3.6rem]">
          Do these customers <em className="text-lime">overlap</em>, or <em className="text-rose-300">clash</em>?
        </p>
        <p className="mt-4 max-w-2xl text-base text-zinc-400 sm:text-lg">
          The spreadsheet shows revenue and margin. It does not show whether two brands&apos; audiences cannibalize each other or walk away after the deal. Four agents answer that from Qloo&apos;s cross-domain taste graph.
        </p>
      </section>

      <div role="group" aria-label="Mode" className="mt-8 inline-flex rounded-xl border border-white/10 bg-well p-1">
        {(["pair", "screen"] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            disabled={busy}
            onClick={() => switchMode(m)}
            className={`min-h-11 rounded-lg px-4 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-lime/60 disabled:cursor-not-allowed ${mode === m ? "bg-white/[0.08] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]" : "text-zinc-400 hover:text-white"}`}
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
        className="card mt-3 p-5 sm:p-6"
        noValidate
      >
        <div className={`grid gap-4 ${mode === "pair" ? "sm:grid-cols-[1fr_auto_1fr] sm:items-end" : "sm:grid-cols-2"}`}>
          <div>
            <label htmlFor="acquirer" className="eyebrow mb-2 block">Acquirer</label>
            <input id="acquirer" className="field" value={acquirer} onChange={(e) => setAcquirer(e.target.value)} placeholder="e.g. Nike" autoComplete="off" maxLength={100} />
          </div>
          {mode === "pair" ? (
            <>
              <div aria-hidden className="hidden h-12 w-12 items-center justify-center self-end rounded-full border border-white/10 text-lg text-zinc-500 sm:flex">×</div>
              <div>
                <label htmlFor="target" className="eyebrow mb-2 block">Target</label>
                <input id="target" className="field" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. Adidas" autoComplete="off" maxLength={100} />
              </div>
            </>
          ) : (
            <div>
              <label htmlFor="targets" className="eyebrow mb-2 block">Candidate targets</label>
              <textarea id="targets" className="field" rows={3} value={targetsText} onChange={(e) => setTargetsText(e.target.value)} placeholder="2 to 5 brands, comma or line separated" />
              <button type="button" disabled={busy} onClick={() => void findTargets()} className="btn btn-ghost mt-3">
                {finding ? "Finding targets…" : "Find targets"}
              </button>
            </div>
          )}
        </div>
        {(mode === "pair" ? presets.length : screens.length) > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2" role="group" aria-label={mode === "pair" ? "Preset deals" : "Preset screens"}>
            <span className="text-sm text-zinc-500">{mode === "pair" ? "Try a deal:" : "Try a screen:"}</span>
            {(mode === "pair" ? presets : screens).map((p) => (
              <button key={p.id} type="button" disabled={busy} onClick={() => ("target" in p ? pick(p) : pickScreen(p))} className="chip">
                {p.label}
              </button>
            ))}
          </div>
        )}
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button type="submit" disabled={busy} className="btn btn-primary min-h-13! px-7! text-base!">
            {mode === "pair" ? (running ? "Running diligence…" : "Run diligence") : screening ? "Screening targets…" : "Screen targets"}
            {!busy && <span aria-hidden>→</span>}
          </button>
          <span className="text-xs text-zinc-400">{mode === "pair" ? "18 Qloo calls, about 10 seconds live" : "One run per target, in parallel"}</span>
        </div>
        {error && (
          <p role="alert" className="mt-5 rounded-xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </p>
        )}
      </form>

      {showProgress && (
        <section aria-label="Agent progress" className="card rise mt-4 p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="eyebrow">Diligence pipeline</h2>
            <span className="text-xs text-zinc-400">{data ? "Finished" : "Running"}</span>
          </div>
          <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {AGENTS.map((name, i) => {
              const step = trace.find((t) => t.agent === name);
              const done = Boolean(step);
              const waiting = !done && active !== name && !data;
              return (
                <li key={name} data-testid={`agent-${name}`} data-state={done ? "done" : waiting ? "waiting" : "running"} className={`well relative p-4 transition ${waiting ? "opacity-50" : ""}`}>
                  <div className="flex items-center gap-2.5">
                    <span aria-hidden className={`flex size-6 items-center justify-center rounded-full text-[0.7rem] font-bold ${done ? "bg-lime text-black" : waiting ? "border border-white/15 text-zinc-500" : "border border-lime/60 text-lime"}`}>
                      {done ? "✓" : waiting ? i + 1 : <span className="size-2 animate-pulse rounded-full bg-lime" />}
                    </span>
                    <span className="text-sm font-semibold text-white">{name}</span>
                  </div>
                  <p className="mt-2 text-xs text-zinc-400">{AGENT_ROLES[name]}</p>
                  <p className="num mt-2 text-xs text-zinc-300">
                    {step ? `Done · ${step.ms} ms · ${step.replayed ? "recorded answers, no live Qloo calls" : `${step.qloo_calls} Qloo ${step.qloo_calls === 1 ? "call" : "calls"}`}` : waiting ? "Waiting" : "Running…"}
                  </p>
                  {step?.decision && <p data-testid={`decision-${name}`} className="mt-2 border-l-2 border-lime/50 pl-2 text-xs text-zinc-200">{step.decision}</p>}
                  {step?.planner && (
                    <p data-testid={`planner-${name}`} title={step.fallback} className="mt-1.5 text-xs text-zinc-400">
                      {step.planner === "llm" ? (step.recorded ? `Recorded ${step.model} run` : `${name === "Partner" ? "Memo by" : "Decided by"} ${step.model}`) : step.planner === "rule" ? "Rule-based fallback" : "Template memo"}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <div className="mt-4" aria-live="polite">
        {mode === "screen" && rows.length > 0 && <ScreenTable acquirer={screenAcquirer} rows={rows} found={found} onFull={fullDiligence} />}
        {mode === "screen" && rows.length === 0 && !error && (
          <Empty testId="screen-empty" title="Which acquisition target fits best?" body="Enter an acquirer and 2 to 5 candidate targets. Each one gets a full taste-graph diligence, run in parallel, and the table ranks them. A whole screen counts as one run against the rate limit." />
        )}
        {mode === "pair" && data && <Results data={data} />}
        {mode === "pair" && !data && !running && !error && (
          <Empty testId="empty-state" title="Is this deal a cannibalization trap or a cross-sell win?" body="Enter an acquirer and a target, or pick a preset deal. Four agents compare the two audiences on Qloo's taste graph and hand back a Brand Cannibalization Index, a culture clash score and a deal memo." />
        )}
      </div>

      {mode === "pair" && <Backtest />}

      <footer className="mt-14 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] pt-5 text-xs text-zinc-400">
        <span>Every score is computed from Qloo data with fixed formulas. The optional LLM only words the memo and is fact-checked against the data.</span>
        <span>Built for the Qloo Agentic Hackathon · MIT</span>
      </footer>
    </main>
  );
}

const STEPS = [
  ["Scout", "Resolves both brands to Qloo entities"],
  ["Cartographer", "Pulls 7 taste domains + demographics"],
  ["Analyst", "Scores overlap, clash and churn risk"],
  ["Partner", "Writes the deal memo and verdict"],
];

function Empty({ testId, title, body }: { testId: string; title: string; body: string }) {
  return (
    <div data-testid={testId} className="card rise p-6 sm:p-8">
      <p className="display text-2xl text-white sm:text-3xl">{title}</p>
      <p className="mt-2 max-w-3xl text-sm text-zinc-400">{body}</p>
      <ol className="relative mt-7 grid gap-6 sm:grid-cols-4 sm:gap-4">
        <span aria-hidden className="absolute left-3 top-3 hidden h-px w-[calc(100%-1.5rem)] bg-gradient-to-r from-lime/60 via-white/15 to-white/15 sm:block" />
        {STEPS.map(([name, role], i) => (
          <li key={name} className="relative flex gap-3 sm:block">
            <span className={`num relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full border text-[0.65rem] font-bold ${i === 0 ? "border-lime bg-lime text-black" : "border-white/20 bg-panel text-zinc-400"}`}>{i + 1}</span>
            <div className="sm:mt-3">
              <p className="text-sm font-semibold text-white">{name}</p>
              <p className="mt-0.5 text-xs text-zinc-400">{role}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Mark() {
  return (
    <svg aria-hidden width="36" height="36" viewBox="0 0 36 36" className="shrink-0">
      <rect width="36" height="36" rx="10" fill="#c6f135" />
      <circle cx="14.5" cy="18" r="7" fill="none" stroke="#0b0f00" strokeWidth="2.2" />
      <circle cx="21.5" cy="18" r="7" fill="none" stroke="#0b0f00" strokeWidth="2.2" />
      <path d="M18 12.1a7 7 0 0 1 0 11.8a7 7 0 0 1 0-11.8z" fill="#0b0f00" />
    </svg>
  );
}
