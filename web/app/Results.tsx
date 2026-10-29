"use client";

import { useEffect, useRef } from "react";
import { download, memoFilename, memoMarkdown } from "./export";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { label, type Clashing, type Demographics, type Diligence } from "./types";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const VERDICT_STYLE: Record<string, string> = {
  Proceed: "pill bg-emerald-400/12 text-emerald-300 ring-1 ring-emerald-400/30",
  "Proceed with conditions": "pill bg-amber-400/12 text-amber-300 ring-1 ring-amber-400/30",
  Pass: "pill bg-rose-400/12 text-rose-300 ring-1 ring-rose-400/30",
};

export const CHURN_STYLE: Record<string, string> = { low: "text-emerald-300", medium: "text-amber-300", high: "text-rose-300" };

// The hero card is tinted by the verdict, like a risk console that goes red on a high score.
const VERDICT_TINT: Record<string, string> = {
  Proceed: "from-emerald-400/[0.14] via-panel to-panel",
  "Proceed with conditions": "from-amber-400/[0.14] via-panel to-panel",
  Pass: "from-rose-400/[0.14] via-panel to-panel",
};

export function RecordedBanner({ reason, className = "" }: { reason: string; className?: string }) {
  return (
    <div role="status" data-testid="recorded-banner" className={`flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-3.5 py-2 ${className}`}>
      <p className="text-xs font-semibold text-amber-200">Recorded Qloo data</p>
      <p className="text-xs text-amber-50/80">{reason}</p>
    </div>
  );
}

function Card({ title, children, className = "", testId, aside }: { title: string; children: React.ReactNode; className?: string; testId?: string; aside?: React.ReactNode }) {
  return (
    <section data-testid={testId} className={`card min-w-0 p-5 sm:p-6 ${className}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="eyebrow">{title}</h2>
        {aside}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

// A ruler of ticks: everything up to the value lights up, the value is pinned above it and the threshold that flips the verdict is marked below.
function Gauge({ label, value, valueText, threshold, thresholdLabel, tone, valueTestId }: { label: string; value: number; valueText: string; threshold: number; thresholdLabel: string; tone: string; valueTestId?: string }) {
  const ticks = 60;
  const v = Math.max(0, Math.min(100, value));
  const lit = v >= 100 ? ticks : v > 0 ? Math.max(1, Math.min(ticks - 1, Math.round((v / 100) * ticks))) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-zinc-300">{label}</span>
        <span data-testid={valueTestId} className="num font-semibold text-white">{valueText}</span>
      </div>
      <div className="relative mt-6">
        <span aria-hidden className="num absolute -top-5 -translate-x-1/2 rounded bg-white px-1.5 py-0.5 text-[0.65rem] font-bold leading-none text-black" style={{ left: `${v}%` }}>{valueText}</span>
        <div className="flex h-7 items-end gap-[2px]" aria-hidden>
          {Array.from({ length: ticks }, (_, i) => (
            <span key={i} className={`flex-1 rounded-[1px] ${i < lit ? tone : "bg-white/[0.08]"} ${i % 10 === 0 ? "h-7" : "h-5"}`} />
          ))}
        </div>
        <span aria-hidden className="absolute inset-y-[-5px] w-[2px] rounded-full bg-white" style={{ left: `calc(${threshold}% - 1px)` }} />
      </div>
      <div className="num relative mt-1.5 h-4 text-[0.65rem] text-zinc-500" aria-hidden>
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap font-medium text-zinc-300" style={{ left: `${threshold}%` }}>{thresholdLabel}</span>
        <span className="absolute right-0">100</span>
      </div>
    </div>
  );
}

function TasteList({ title, items, empty, testId, tone }: { title: string; items: { key: string; name: string; domain: string; note: string; strength: number }[]; empty: string; testId?: string; tone: string }) {
  return (
    <Card title={title} testId={testId}>
      {items.length === 0 ? (
        <p className="text-sm text-zinc-400">{empty}</p>
      ) : (
        <ol className="space-y-3">
          {items.map((i, n) => (
            <li key={i.key} className="grid grid-cols-[1.25rem_1fr_auto] items-center gap-x-3">
              <span className="num text-xs text-zinc-500">{n + 1}</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-zinc-100">{i.name}</span>
                <span className="text-xs text-zinc-400">{label(i.domain)}</span>
              </span>
              <span className="num shrink-0 text-xs text-zinc-400">{i.note}</span>
              <span className="col-start-2 col-end-4 mt-1.5 h-1 rounded-full bg-white/[0.06]" aria-hidden>
                <span className={`block h-full rounded-full ${tone}`} style={{ width: `${Math.round(i.strength * 100)}%` }} />
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

const clashItems = (list: Clashing[]) =>
  list.map((c) => ({ key: `${c.domain}-${c.name}`, name: c.name, domain: c.domain, note: `affinity ${c.affinity.toFixed(2)}`, strength: c.affinity }));

// Diverging bar: the track centre is zero, negative affinities grow left, positive grow right.
function Bar({ value, tone }: { value: number; tone: string }) {
  const v = Math.max(-1, Math.min(1, value));
  const style = v < 0 ? { right: "50%", width: `${-v * 50}%` } : { left: "50%", width: `${v * 50}%` };
  return (
    <div className="relative h-2.5 flex-1 rounded-full bg-white/[0.07]">
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-zinc-500" aria-hidden />
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
          <div key={k} className="grid grid-cols-[6.5rem_1fr] items-center gap-3 text-xs sm:grid-cols-[8rem_1fr]">
            <span className="text-zinc-300">{k.replaceAll("_", " ")}</span>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <Bar value={a[k] ?? 0} tone="bg-lime" />
                <span className="num w-10 text-right text-zinc-400" aria-label={`${nameA} ${k}`}>{(a[k] ?? 0).toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <Bar value={b[k] ?? 0} tone="bg-ice" />
                <span className="num w-10 text-right text-zinc-400" aria-label={`${nameB} ${k}`}>{(b[k] ?? 0).toFixed(2)}</span>
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
    <Card title="Audience demographics" testId="demographics" aside={<span className="num text-xs text-zinc-400">Distance {distance.toFixed(2)} · 0 = identical audiences</span>}>
      <div className="mb-5 flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-300">
        <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-lime" />{nameA}</span>
        <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-ice" />{nameB}</span>
        <span className="text-zinc-400">← under-indexed · over-indexed →</span>
      </div>
      {empty ? (
        <p className="text-sm text-zinc-400">Qloo has no audience data for these brands.</p>
      ) : (
        <div className="grid gap-8 lg:grid-cols-[3fr_2fr]">
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
      <tspan x={x} dy="1.25em" data-testid="radar-value" fill="#c6f135" fontWeight={600}>{row.overlap}%</tspan>
    </text>
  );
}

export default function Results({ data }: { data: Diligence }) {
  const { scores, memo, brands } = data;
  const nameA = brands.acquirer.name;
  const nameB = brands.target.name;
  const radarData = Object.entries(data.domain_overlap).map(([d, v]) => ({ domain: label(d), overlap: Math.round(v * 100), baseline: 100 }));
  const noOverlap = radarData.every((r) => r.overlap === 0);
  const qlooCalls = data.trace.reduce((n, t) => n + t.qloo_calls, 0);
  const replayed = data.trace.some((t) => t.replayed);
  const top = useRef<HTMLDivElement>(null);
  // the verdict and radar sit at the top of the results: bring them into view once a run finishes
  useEffect(() => {
    top.current?.scrollIntoView({ block: "start" });
  }, []);

  return (
    <div ref={top} className="rise scroll-mt-4 space-y-4" data-testid="results">
      {data.recorded && <RecordedBanner reason={data.recorded.reason} />}
      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <section className={`card flex flex-col gap-6 bg-gradient-to-br p-5 sm:p-7 ${VERDICT_TINT[memo.verdict] ?? VERDICT_TINT.Pass}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Deal</p>
              <p className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">
                {nameA} <span className="text-zinc-500">×</span> {nameB}
              </p>
            </div>
            <button type="button" onClick={() => download(memoFilename(data), memoMarkdown(data))} className="btn btn-ghost px-3.5! text-xs!">
              Download memo (.md)
            </button>
          </div>

          <div>
            <p className="eyebrow">Brand Cannibalization Index</p>
            <div className="mt-1 flex flex-wrap items-end gap-x-5 gap-y-3">
              <p className="flex items-baseline gap-2">
                <span data-testid="bci-value" className="num text-[6rem] font-semibold leading-none tracking-[-0.05em] text-white sm:text-[8rem]">{scores.bci.toFixed(1)}</span>
                <span className="num text-xl text-zinc-500">/100</span>
              </p>
              <div className="pb-2">
                <span data-testid="verdict" className={`${VERDICT_STYLE[memo.verdict] ?? VERDICT_STYLE.Pass} px-4! py-2! text-sm!`}>{memo.verdict}</span>
                <p className="mt-2 text-sm text-zinc-400">
                  <span data-testid="churn-band" className={`font-semibold ${CHURN_STYLE[scores.churn_risk]}`}>{cap(scores.churn_risk)}</span> churn risk
                </p>
              </div>
            </div>
            <dl className="mt-4 grid grid-cols-3 gap-x-4 gap-y-3 border-t border-white/[0.07] pt-4 text-sm">
              <div>
                <dt className="text-xs text-zinc-400">Audience distance</dt>
                <dd className="num font-semibold text-white">{scores.demographic_distance.toFixed(2)}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-400">Domains overlapping</dt>
                <dd className="num font-semibold text-white">{radarData.filter((r) => r.overlap > 0).length} / {radarData.length}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-400">Qloo calls</dt>
                <dd className="num font-semibold text-white">{replayed ? "Recorded" : qlooCalls}</dd>
              </div>
            </dl>
          </div>

          <div className="space-y-7">
            <Gauge label="Cannibalization" value={scores.bci} valueText={scores.bci.toFixed(1)} threshold={50} thresholdLabel="Proceed ≥ 50" tone="bg-lime" />
            <Gauge label="Culture clash" value={scores.culture_clash} valueText={`${scores.culture_clash.toFixed(1)}%`} threshold={66} thresholdLabel="Pass ≥ 66" tone="bg-rose-400" valueTestId="clash-value" />
          </div>

          <div className="well p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span data-testid="fit-chip" className="pill bg-ice/10 text-ice ring-1 ring-ice/30">Fit: {data.fit.label}</span>
              <span className="text-sm text-zinc-300">{memo.headline}</span>
            </div>
            <p data-testid="fit-note" className="mt-2 text-sm text-zinc-400">{data.fit.note}</p>
          </div>

        </section>

        <Card title={`${nameA} × ${nameB} taste overlap`} aside={<span className="text-xs text-zinc-400">7 Qloo domains</span>}>
          <div data-testid="radar" role="img" aria-label={`Taste overlap by domain: ${radarData.map((r) => `${r.domain} ${r.overlap}%`).join(", ")}`} className="relative h-[26rem] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="78%" margin={{ top: 28, right: 48, bottom: 28, left: 48 }}>
                <PolarGrid stroke={noOverlap ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.12)"} />
                <PolarAngleAxis dataKey="domain" tick={<AxisTick values={radarData} />} />
                <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
                {noOverlap && (
                  <Radar className="radar-baseline" name="Baseline" dataKey="baseline" stroke="#fb7185" strokeDasharray="6 4" strokeOpacity={0.7} fill="none" dot={false} isAnimationActive={false} />
                )}
                <Radar name="Overlap" dataKey="overlap" stroke="#c6f135" strokeWidth={2} fill="#c6f135" fillOpacity={0.28} dot={{ r: 3, fill: "#c6f135", strokeWidth: 0 }} isAnimationActive={false} />
              </RadarChart>
            </ResponsiveContainer>
            {noOverlap && (
              <p data-testid="radar-empty-caption" className="pointer-events-none absolute inset-x-0 top-[56%] text-center text-xs font-medium text-rose-200">
                No shared taste in any domain
              </p>
            )}
          </div>
          {noOverlap && (
            <p data-testid="no-shared-taste" className="mt-3 rounded-lg border border-dashed border-rose-400/40 bg-rose-400/5 px-3 py-2 text-center text-sm text-rose-200">
              No shared taste in any domain: the audiences don&apos;t overlap.
            </p>
          )}
          <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-xs" aria-label="Overlap by domain">
            {radarData.map((r) => (
              <li key={r.domain} className="grid grid-cols-[5.5rem_1fr_2.5rem] items-center gap-2">
                <span className="text-zinc-300">{r.domain}</span>
                <span className="h-1.5 rounded-full bg-white/[0.06]" aria-hidden><span className="block h-full rounded-full bg-lime/80" style={{ width: `${r.overlap}%` }} /></span>
                <span className="num text-right text-zinc-200">{r.overlap}%</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {(data.probed_tags || data.bridges.length > 0 || data.bridge_picks.length > 0) && (
        <Card title="Bridging tastes: the Analyst's tag probe" aside={<span className="text-xs text-zinc-400">Never changes BCI, clash or verdict</span>}>
          <div className="flex flex-wrap gap-3 [&>*]:min-w-[16rem] [&>*]:flex-1">
          {data.probed_tags && (
            <div data-testid="bridge-potential" className="well px-4 py-3">
              <p className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium text-zinc-100">Bridge potential</span>
                <span className="num font-semibold text-white"><span data-testid="bridge-potential-value">{data.bridge_potential}</span> / 100</span>
              </p>
              <p className="mt-1 text-xs text-zinc-400">How strongly the Analyst&apos;s tag probe found tastes both audiences share. BCI and culture clash are unchanged.</p>
            </div>
          )}
          {data.bridges.length > 0 && (
            <div data-testid="bridges" className="well px-4 py-3">
              <h3 className="text-sm font-medium text-zinc-100">Bridging tastes</h3>
              <ul className="mt-2 space-y-1.5">
                {data.bridges.map((b) => (
                  <li key={b.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 break-words text-zinc-200">{b.name}</span>
                    <span className="num shrink-0 text-xs text-zinc-400">{b.affinity_acquirer.toFixed(2)} / {b.affinity_target.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-400">Qloo tags both audiences share, with {nameA} / {nameB} affinity.</p>
            </div>
          )}
          {data.bridge_picks.length > 0 && (
            <div data-testid="bridge-picks" className="well px-4 py-3">
              <h3 className="text-sm font-medium text-zinc-100">Follow-up: {label(data.bridge_picks[0].domain)} via {data.bridge_picks[0].tag_name}</h3>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {data.bridge_picks.map((p) => (
                  <li key={p.name} className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-zinc-200">{p.name}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-400">The Analyst&apos;s one follow-up query: entities Qloo ties to the strongest bridging tag.</p>
            </div>
          )}
          </div>
        </Card>
      )}

      <DemographicsCard a={data.demographics.acquirer} b={data.demographics.target} nameA={nameA} nameB={nameB} distance={scores.demographic_distance} />

      <div className="grid gap-4 md:grid-cols-3">
        <TasteList
          title="Shared tastes"
          testId="shared-tastes"
          tone="bg-lime"
          empty="Neither audience loves anything in common."
          items={data.top_shared.map((s) => ({ key: `${s.domain}-${s.name}`, name: s.name, domain: s.domain, note: `${s.affinity_a.toFixed(2)} / ${s.affinity_b.toFixed(2)}`, strength: Math.min(s.affinity_a, s.affinity_b) }))}
        />
        <TasteList title={`Only ${nameA} fans`} testId="clash-acquirer" tone="bg-rose-400/80" empty="No distinctive tastes found." items={clashItems(data.top_clashing.acquirer)} />
        <TasteList title={`Only ${nameB} fans`} testId="clash-target" tone="bg-rose-400/80" empty="No distinctive tastes found." items={clashItems(data.top_clashing.target)} />
      </div>

      <Card title="Deal memo" testId="memo" aside={<span className="text-xs text-zinc-400">{memo.author ? `Memo by ${memo.author}` : "Template memo"}</span>}>
        <p className="display text-2xl text-white sm:text-3xl">{memo.headline}</p>
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="well p-4">
            <h3 className="eyebrow text-emerald-300/80!">Rationale</h3>
            <ul className="mt-3 space-y-2.5 text-sm text-zinc-300">
              {memo.rationale.map((r) => (
                <li key={r} className="flex gap-2.5"><span aria-hidden className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-emerald-400" />{r}</li>
              ))}
            </ul>
          </div>
          <div className="well p-4">
            <h3 className="eyebrow text-rose-300/80!">Risks</h3>
            <ul className="mt-3 space-y-2.5 text-sm text-zinc-300">
              {memo.risks.map((r) => (
                <li key={r} className="flex gap-2.5"><span aria-hidden className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-rose-400" />{r}</li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
