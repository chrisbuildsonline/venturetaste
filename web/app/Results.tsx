"use client";

import { useEffect, useRef } from "react";
import { download, memoFilename, memoMarkdown } from "./export";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { label, type Clashing, type Demographics, type Diligence } from "./types";

const pct = (v: number) => `${Math.round(v * 100)}%`;

export const VERDICT_STYLE: Record<string, string> = {
  Proceed: "bg-emerald-400/15 text-emerald-300 ring-emerald-400/40",
  "Proceed with conditions": "bg-amber-400/15 text-amber-300 ring-amber-400/40",
  Pass: "bg-rose-400/15 text-rose-300 ring-rose-400/40",
};

export const CHURN_STYLE: Record<string, string> = { low: "text-emerald-300", medium: "text-amber-300", high: "text-rose-300" };

export function RecordedBanner({ reason, className = "" }: { reason: string; className?: string }) {
  return (
    <div role="status" data-testid="recorded-banner" className={`rounded-2xl border border-amber-400/40 bg-amber-400/10 px-5 py-4 ${className}`}>
      <p className="text-sm font-semibold text-amber-200">Recorded Qloo data</p>
      <p className="mt-1 text-sm text-amber-50">{reason}</p>
    </div>
  );
}

function Card({ title, children, className = "", testId }: { title: string; children: React.ReactNode; className?: string; testId?: string }) {
  return (
    <section data-testid={testId} className={`min-w-0 rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6 ${className}`}>
      <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function TasteList({ title, items, empty, testId }: { title: string; items: { key: string; name: string; domain: string; note: string }[]; empty: string; testId?: string }) {
  return (
    <Card title={title} testId={testId}>
      {items.length === 0 ? (
        <p className="text-sm text-zinc-400">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((i) => (
            <li key={i.key} className="flex items-baseline justify-between gap-3">
              <span className="min-w-0">
                <span className="block truncate font-medium text-zinc-100">{i.name}</span>
                <span className="text-xs text-zinc-400">{label(i.domain)}</span>
              </span>
              <span className="shrink-0 text-xs tabular-nums text-zinc-400">{i.note}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const clashItems = (list: Clashing[]) =>
  list.map((c) => ({ key: `${c.domain}-${c.name}`, name: c.name, domain: c.domain, note: `affinity ${c.affinity.toFixed(2)}` }));

// Diverging bar: the track centre is zero, negative affinities grow left, positive grow right.
function Bar({ value, tone }: { value: number; tone: string }) {
  const v = Math.max(-1, Math.min(1, value));
  const style = v < 0 ? { right: "50%", width: `${-v * 50}%` } : { left: "50%", width: `${v * 50}%` };
  return (
    <div className="relative h-2 flex-1 rounded-full bg-white/10">
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-zinc-400" aria-hidden />
      <div data-testid="demo-bar" data-sign={v < 0 ? "negative" : "positive"} className={`absolute inset-y-0 ${v < 0 ? "rounded-l-full" : "rounded-r-full"} ${tone}`} style={style} />
    </div>
  );
}

function DemoGroup({ title, keys, a, b, nameA, nameB }: { title: string; keys: string[]; a: Record<string, number>; b: Record<string, number>; nameA: string; nameB: string }) {
  if (keys.length === 0) return null;
  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-zinc-200">{title}</h3>
      <div className="space-y-3">
        {keys.map((k) => (
          <div key={k} className="grid grid-cols-[7.5rem_1fr] items-center gap-3 text-xs sm:grid-cols-[9rem_1fr]">
            <span className="text-zinc-300">{k.replaceAll("_", " ")}</span>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <Bar value={a[k] ?? 0} tone="bg-indigo-400" />
                <span className="w-10 text-right tabular-nums text-zinc-400" aria-label={`${nameA} ${k}`}>{(a[k] ?? 0).toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <Bar value={b[k] ?? 0} tone="bg-fuchsia-400" />
                <span className="w-10 text-right tabular-nums text-zinc-400" aria-label={`${nameB} ${k}`}>{(b[k] ?? 0).toFixed(2)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DemographicsCard({ a, b, nameA, nameB, distance }: { a: Demographics; b: Demographics; nameA: string; nameB: string; distance: number }) {
  const keys = (x: Record<string, number>, y: Record<string, number>) => [...new Set([...Object.keys(x), ...Object.keys(y)])];
  const empty = keys(a.age, b.age).length + keys(a.gender, b.gender).length === 0;
  return (
    <Card title="Audience demographics" testId="demographics">
      <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-300">
        <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-indigo-400" />{nameA}</span>
        <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-fuchsia-400" />{nameB}</span>
        <span className="text-zinc-400">Distance {distance.toFixed(2)} (0 = identical audiences)</span>
        <span className="w-full text-zinc-400">← under-indexed · over-indexed →</span>
      </div>
      {empty ? (
        <p className="text-sm text-zinc-400">Qloo has no audience data for these brands.</p>
      ) : (
        <div className="space-y-8">
          <DemoGroup title="Age" keys={keys(a.age, b.age)} a={a.age} b={b.age} nameA={nameA} nameB={nameB} />
          <DemoGroup title="Gender" keys={keys(a.gender, b.gender)} a={a.gender} b={b.gender} nameA={nameA} nameB={nameB} />
        </div>
      )}
    </Card>
  );
}

// Radar axis label with the overlap percent underneath, so a zero axis still reads as "0%".
function AxisTick({ x, y, textAnchor, index, values }: { x?: number; y?: number; textAnchor?: "start" | "middle" | "end" | "inherit"; index?: number; values: { domain: string; overlap: number }[] }) {
  const row = values[index ?? 0];
  if (!row) return null;
  return (
    <text x={x} y={y} textAnchor={textAnchor} fill="#d4d4d8" fontSize={12}>
      <tspan x={x}>{row.domain}</tspan>
      <tspan x={x} dy="1.2em" data-testid="radar-value" fill="#a5b4fc" fontWeight={600}>{row.overlap}%</tspan>
    </text>
  );
}

export default function Results({ data }: { data: Diligence }) {
  const { scores, memo, brands } = data;
  const nameA = brands.acquirer.name;
  const nameB = brands.target.name;
  const radarData = Object.entries(data.domain_overlap).map(([d, v]) => ({ domain: label(d), overlap: Math.round(v * 100) }));
  const noOverlap = radarData.every((r) => r.overlap === 0);
  const top = useRef<HTMLDivElement>(null);
  // the verdict and radar sit at the top of the results: bring them into view once a run finishes
  useEffect(() => {
    top.current?.scrollIntoView({ block: "start" });
  }, []);

  return (
    <div ref={top} className="scroll-mt-4 space-y-5" data-testid="results">
      {data.recorded && <RecordedBanner reason={data.recorded.reason} />}
      <div className="grid gap-5 lg:grid-cols-2">
      <section className="flex flex-col justify-center gap-6 rounded-2xl border border-white/10 bg-gradient-to-br from-indigo-500/10 via-white/[0.03] to-fuchsia-500/10 p-5 sm:p-8">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-zinc-400">Brand Cannibalization Index</p>
          <p className="mt-2 flex items-baseline gap-2">
            <span data-testid="bci-value" className="text-7xl font-semibold tracking-tight text-white tabular-nums">{scores.bci.toFixed(1)}</span>
            <span className="text-lg text-zinc-400">/ 100</span>
          </p>
        </div>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <span data-testid="verdict" className={`rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${VERDICT_STYLE[memo.verdict] ?? VERDICT_STYLE.Pass}`}>{memo.verdict}</span>
            <span data-testid="churn-band" className={`text-sm font-medium ${CHURN_STYLE[scores.churn_risk]}`}>
              {scores.churn_risk.charAt(0).toUpperCase() + scores.churn_risk.slice(1)} churn risk
            </span>
          </div>
          <div>
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-zinc-300">Culture clash</span>
              <span data-testid="clash-value" className="font-semibold tabular-nums text-white">{scores.culture_clash.toFixed(1)}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-amber-400 to-rose-400" style={{ width: `${scores.culture_clash}%` }} />
            </div>
          </div>
          <p className="text-sm text-zinc-300">{memo.headline}</p>
          <button
            type="button"
            onClick={() => download(memoFilename(data), memoMarkdown(data))}
            className="min-h-11 rounded-xl border border-indigo-300/60 px-5 text-sm font-semibold text-indigo-100 transition hover:bg-indigo-400/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
          >
            Download memo (.md)
          </button>
        </div>
      </section>

        <Card title={`${nameA} × ${nameB} taste overlap`}>
          <div data-testid="radar" role="img" aria-label={`Taste overlap by domain: ${radarData.map((r) => `${r.domain} ${r.overlap}%`).join(", ")}`} className="h-80 w-full lg:h-[28rem]">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="72%" margin={{ top: 24, right: 40, bottom: 24, left: 40 }}>
                <PolarGrid stroke="rgba(255,255,255,0.18)" />
                <PolarAngleAxis dataKey="domain" tick={<AxisTick values={radarData} />} />
                <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
                <Radar name="Overlap" dataKey="overlap" stroke="#818cf8" fill="#818cf8" fillOpacity={0.4} dot={{ r: 3, fill: "#818cf8" }} isAnimationActive={false} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
          {noOverlap && (
            <p data-testid="no-shared-taste" className="mt-3 rounded-lg border border-dashed border-rose-400/40 bg-rose-400/5 px-3 py-2 text-center text-sm text-rose-200">
              No shared taste in any domain: the audiences don&apos;t overlap.
            </p>
          )}
          {data.probed_tags && (
            <div data-testid="bridge-potential" className="mt-3 rounded-lg border border-indigo-400/30 bg-indigo-400/5 px-3 py-2">
              <p className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium text-indigo-200">Bridge potential</span>
                <span className="font-semibold tabular-nums text-white"><span data-testid="bridge-potential-value">{data.bridge_potential}</span> / 100</span>
              </p>
              <p className="mt-1 text-xs text-zinc-400">How strongly the Analyst&apos;s tag probe found tastes both audiences share. BCI and culture clash are unchanged.</p>
            </div>
          )}
          {data.bridges.length > 0 && (
            <div data-testid="bridges" className="mt-3 rounded-lg border border-indigo-400/30 bg-indigo-400/5 px-3 py-2">
              <h3 className="text-sm font-medium text-indigo-200">Bridging tastes</h3>
              <ul className="mt-2 space-y-1.5">
                {data.bridges.map((b) => (
                  <li key={b.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 break-words text-zinc-100">{b.name}</span>
                    <span className="shrink-0 text-xs tabular-nums text-zinc-400">{b.affinity_acquirer.toFixed(2)} / {b.affinity_target.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-400">Qloo tags both audiences share, with {nameA} / {nameB} affinity.</p>
            </div>
          )}
          {data.bridge_picks.length > 0 && (
            <div data-testid="bridge-picks" className="mt-3 rounded-lg border border-indigo-400/30 bg-indigo-400/5 px-3 py-2">
              <h3 className="text-sm font-medium text-indigo-200">Follow-up: {label(data.bridge_picks[0].domain)} via {data.bridge_picks[0].tag_name}</h3>
              <ul className="mt-2 space-y-1.5">
                {data.bridge_picks.map((p) => (
                  <li key={p.name} className="min-w-0 break-words text-sm text-zinc-100">{p.name}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-400">The Analyst&apos;s one follow-up query: entities Qloo ties to the strongest bridging tag.</p>
            </div>
          )}
          <p className="mt-3 text-xs text-zinc-400">Weighted Jaccard overlap of what each audience loves: {Object.entries(data.domain_overlap).map(([d, v]) => `${label(d)} ${pct(v)}`).join(" · ")}</p>
        </Card>
      </div>

      <DemographicsCard a={data.demographics.acquirer} b={data.demographics.target} nameA={nameA} nameB={nameB} distance={scores.demographic_distance} />

      <div className="grid gap-5 md:grid-cols-3">
        <TasteList
          title="Shared tastes"
          testId="shared-tastes"
          empty="Neither audience loves anything in common."
          items={data.top_shared.map((s) => ({ key: `${s.domain}-${s.name}`, name: s.name, domain: s.domain, note: `${s.affinity_a.toFixed(2)} / ${s.affinity_b.toFixed(2)}` }))}
        />
        <TasteList title={`Only ${nameA} fans`} testId="clash-acquirer" empty="No distinctive tastes found." items={clashItems(data.top_clashing.acquirer)} />
        <TasteList title={`Only ${nameB} fans`} testId="clash-target" empty="No distinctive tastes found." items={clashItems(data.top_clashing.target)} />
      </div>

      <Card title="Deal memo" testId="memo">
        <p className="text-lg font-semibold text-white">{memo.headline}</p>
        <div className="mt-5 grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium text-zinc-200">Rationale</h3>
            <ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-zinc-300">
              {memo.rationale.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-medium text-zinc-200">Risks</h3>
            <ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-zinc-300">
              {memo.risks.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
