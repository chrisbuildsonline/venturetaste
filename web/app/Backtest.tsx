"use client";

import { useEffect, useState } from "react";
import { CHURN_STYLE, VERDICT_STYLE } from "./Results";
import type { Fit } from "./types";

type Deal = {
  acquirer_label: string;
  target_label: string;
  year: number;
  outcome: string;
  outcome_class?: string;
  bci: number;
  clash: number;
  churn: string;
  verdict: string;
  fit: Fit;
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const FIT_STYLE: Record<string, string> = { overlapping: "pill bg-lime/10 text-lime ring-1 ring-lime/30", complementary: "pill bg-ice/10 text-ice ring-1 ring-ice/30", adjacent: "pill bg-white/[0.06] text-zinc-200 ring-1 ring-white/15" };
const OUTCOME_STYLE: Record<string, string> = { kept: "pill bg-emerald-400/12 text-emerald-300", "sold at a loss": "pill bg-rose-400/12 text-rose-300", blocked: "pill bg-amber-400/12 text-amber-300" };

export default function Backtest() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [note, setNote] = useState("");

  useEffect(() => {
    fetch("/api/backtest")
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { deals: Deal[]; note: string } | null) => {
        if (j) {
          setDeals(j.deals);
          setNote(j.note);
        }
      })
      .catch(() => setDeals([]));
  }, []);

  if (deals.length === 0) return null;
  const count = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"][deals.length] ?? String(deals.length);
  const kept = deals.filter((d) => d.outcome_class === "kept");
  const failed = deals.filter((d) => d.outcome_class && d.outcome_class !== "kept");
  const classified = kept.length + failed.length > 0;
  const summary = `Kept: ${kept.filter((d) => d.fit.type === "complementary").length} of ${kept.length} complementary. Sold at a loss or blocked: ${failed.filter((d) => d.fit.type === "adjacent").length} of ${failed.length} adjacent.`;
  const verdict = (d: Deal) => <span className={VERDICT_STYLE[d.verdict] ?? VERDICT_STYLE.Pass}>{d.verdict}</span>;
  return (
    <section aria-label="Backtest on real deals" data-testid="backtest" className="card mt-10 p-5 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="eyebrow">Backtest: real deals</h2>
          <p className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">The same scores, run on {count} real deals and what happened to them.</p>
        </div>
        <span className="text-xs text-zinc-400">Today&apos;s Qloo audiences · recorded fixtures · no key needed</span>
      </div>
      {classified && <p data-testid="backtest-summary" className="mt-3 text-sm font-medium text-zinc-200">{summary}</p>}
      <ul className="mt-4 space-y-3 sm:hidden" aria-label="Backtest cards">
        {deals.map((d) => (
          <li key={`${d.acquirer_label}-${d.target_label}`} data-testid="backtest-card" className="well p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 font-medium text-white">{d.acquirer_label} + {d.target_label} <span className="text-zinc-500">({d.year})</span></p>
              {verdict(d)}
            </div>
            {d.outcome_class && <span className={`${OUTCOME_STYLE[d.outcome_class] ?? OUTCOME_STYLE.blocked} mt-2 text-[0.65rem]!`}>{cap(d.outcome_class)}</span>}
            <p className="mt-1 text-xs text-zinc-300">{d.outcome}</p>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
              <div><dt className="eyebrow">BCI</dt><dd className="num mt-0.5 text-lg font-semibold text-white">{d.bci.toFixed(1)}</dd></div>
              <div><dt className="eyebrow">Clash</dt><dd className="num mt-0.5 text-lg font-semibold text-zinc-200">{d.clash.toFixed(1)}%</dd></div>
              <div><dt className="eyebrow">Churn</dt><dd className={`mt-0.5 text-lg font-semibold ${CHURN_STYLE[d.churn]}`}>{cap(d.churn)}</dd></div>
            </dl>
            <p className="mt-3 text-sm text-zinc-300"><span className="font-semibold text-ice">Fit: {d.fit.label}.</span> {d.fit.note}</p>
          </li>
        ))}
      </ul>
      <div className="mt-4 hidden overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-lime/60 sm:block" role="region" aria-label="Backtest table" tabIndex={0}>
        <table className="w-full min-w-[52rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-white/10">
              <th scope="col" className="th">Deal</th>
              <th scope="col" className="th">Year</th>
              <th scope="col" className="th">Outcome</th>
              <th scope="col" className="th">BCI</th>
              <th scope="col" className="th">Clash</th>
              <th scope="col" className="th">Churn</th>
              <th scope="col" className="th">Verdict</th>
              <th scope="col" className="th">Fit</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={`${d.acquirer_label}-${d.target_label}`} data-testid="backtest-row" className="row">
                <th scope="row" className="td min-w-[10rem] text-left font-medium text-white">{d.acquirer_label} + {d.target_label}</th>
                <td className="td num text-zinc-400">{d.year}</td>
                <td className="td w-[30%] min-w-[15rem] text-zinc-300">
                  {d.outcome_class && <span className={`${OUTCOME_STYLE[d.outcome_class] ?? OUTCOME_STYLE.blocked} mb-1 text-[0.65rem]!`}>{cap(d.outcome_class)}</span>}
                  <p className="text-xs leading-snug text-zinc-400">{d.outcome}</p>
                </td>
                <td data-testid="backtest-bci" className="td num text-base font-semibold text-white">{d.bci.toFixed(1)}</td>
                <td data-testid="backtest-clash" className="td num text-zinc-200">{d.clash.toFixed(1)}%</td>
                <td className={`td font-medium ${CHURN_STYLE[d.churn]}`}>{cap(d.churn)}</td>
                <td className="td">{verdict(d)}</td>
                <td className="td">
                  <span data-testid="backtest-fit" className={FIT_STYLE[d.fit.type] ?? FIT_STYLE.adjacent}>{d.fit.label}</span>
                  <p data-testid="backtest-fit-note" className="sr-only">{d.fit.note}</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
        {[...new Map(deals.map((d) => [d.fit.type, d.fit])).values()].map((f) => (
          <div key={f.type} className="well px-3 py-2">
            <dt className="font-semibold text-zinc-200">{f.label}</dt>
            <dd className="mt-0.5 text-zinc-400">{f.note}</dd>
          </div>
        ))}
      </dl>
      <p data-testid="backtest-note" className="mt-4 text-xs text-zinc-400">{note}</p>
    </section>
  );
}
