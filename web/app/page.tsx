"use client";

import { useEffect, useState } from "react";
import Results from "./Results";
import { AGENTS, type Diligence, type Preset } from "./types";

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

  useEffect(() => {
    fetch("/api/presets")
      .then((r) => (r.ok ? r.json() : []))
      .then(setPresets)
      .catch(() => setPresets([]));
  }, []);

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
    setRunning(true);
    try {
      const res = await fetch("/api/diligence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json: unknown = await res.json().catch(() => null);
      if (!res.ok) setError(errorText(json, res.status));
      else setData(json as Diligence);
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

  const showProgress = running || data !== null;

  return (
    <main className="mx-auto max-w-5xl px-4 pb-20 pt-10 sm:px-6 sm:pt-16">
      <header className="mb-8 sm:mb-10">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-indigo-300">Powered by Qloo taste data</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">VentureTaste</h1>
        <p className="mt-3 max-w-2xl text-lg text-zinc-300">Taste-graph due diligence for consumer brand deals</p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(acquirer, target);
        }}
        className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6"
        noValidate
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="acquirer" className="mb-2 block text-sm font-medium text-zinc-200">Acquirer</label>
            <input id="acquirer" className={INPUT} value={acquirer} onChange={(e) => setAcquirer(e.target.value)} placeholder="e.g. Nike" autoComplete="off" maxLength={100} />
          </div>
          <div>
            <label htmlFor="target" className="mb-2 block text-sm font-medium text-zinc-200">Target</label>
            <input id="target" className={INPUT} value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. Adidas" autoComplete="off" maxLength={100} />
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="submit"
            disabled={running}
            className="rounded-xl bg-indigo-500 px-6 py-3 text-base font-semibold text-white transition hover:bg-indigo-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "Running diligence…" : "Run diligence"}
          </button>
          {presets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Preset deals">
              <span className="text-sm text-zinc-400">Try a deal:</span>
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  disabled={running}
                  onClick={() => pick(p)}
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
              const step = data?.trace.find((t) => t.agent === name);
              const done = Boolean(step);
              return (
                <li key={name} data-testid={`agent-${name}`} data-state={done ? "done" : "running"} className="rounded-xl border border-white/10 bg-black/20 p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <span aria-hidden className={done ? "text-emerald-300" : "inline-block size-2.5 animate-pulse rounded-full bg-indigo-400"}>{done ? "✓" : ""}</span>
                    {name}
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">{AGENT_ROLES[name]}</p>
                  <p className="mt-2 text-xs tabular-nums text-zinc-300">
                    {step ? `Done · ${step.ms} ms · ${step.qloo_calls} Qloo ${step.qloo_calls === 1 ? "call" : "calls"}` : "Running…"}
                  </p>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      <div className="mt-5" aria-live="polite">
        {data && <Results data={data} />}
        {!data && !running && !error && (
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
