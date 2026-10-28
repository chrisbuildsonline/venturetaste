"use client";

import { useEffect, useState } from "react";
import { CHURN_STYLE, VERDICT_STYLE } from "./Results";

type Deal = {
  acquirer_label: string;
  target_label: string;
  year: number;
  outcome: string;
  bci: number;
  clash: number;
  churn: string;
  verdict: string;
};

const TH = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-widest text-zinc-400";
const TD = "px-3 py-3 align-top";
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

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
  const verdict = (d: Deal) => (
    <span className={`inline-block whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ring-1 ${VERDICT_STYLE[d.verdict] ?? VERDICT_STYLE.Pass}`}>{d.verdict}</span>
  );
  return (
    <section aria-label="Backtest on real deals" data-testid="backtest" className="mt-10 rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">Backtest: real deals</h2>
      <p className="mt-2 text-sm text-zinc-300">The same scores, run on four real deals and what happened to them.</p>
      <ul className="mt-4 space-y-3 sm:hidden" aria-label="Backtest cards">
        {deals.map((d) => (
          <li key={`${d.acquirer_label}-${d.target_label}`} data-testid="backtest-card" className="rounded-xl border border-white/10 bg-black/20 p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="min-w-0 font-medium text-white">{d.acquirer_label} + {d.target_label} <span className="text-zinc-400">({d.year})</span></p>
              {verdict(d)}
            </div>
            <p className="mt-1 text-xs text-zinc-400">{d.outcome}</p>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
              <div><dt className="text-xs uppercase tracking-widest text-zinc-400">BCI</dt><dd className="tabular-nums text-white">{d.bci.toFixed(1)}</dd></div>
              <div><dt className="text-xs uppercase tracking-widest text-zinc-400">Clash</dt><dd className="tabular-nums text-zinc-200">{d.clash.toFixed(1)}%</dd></div>
              <div><dt className="text-xs uppercase tracking-widest text-zinc-400">Churn</dt><dd className={`font-medium ${CHURN_STYLE[d.churn]}`}>{cap(d.churn)}</dd></div>
            </dl>
          </li>
        ))}
      </ul>
      <div className="mt-4 hidden overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 sm:block" role="region" aria-label="Backtest table" tabIndex={0}>
        <table className="w-full min-w-[40rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-white/10">
              <th scope="col" className={TH}>Deal</th>
              <th scope="col" className={TH}>Year</th>
              <th scope="col" className={TH}>Outcome</th>
              <th scope="col" className={TH}>BCI</th>
              <th scope="col" className={TH}>Clash</th>
              <th scope="col" className={TH}>Churn</th>
              <th scope="col" className={TH}>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={`${d.acquirer_label}-${d.target_label}`} data-testid="backtest-row" className="border-b border-white/5 last:border-0">
                <th scope="row" className={`${TD} text-left font-medium text-white`}>{d.acquirer_label} + {d.target_label}</th>
                <td className={`${TD} tabular-nums text-zinc-300`}>{d.year}</td>
                <td className={`${TD} text-zinc-300`}>{d.outcome}</td>
                <td data-testid="backtest-bci" className={`${TD} tabular-nums text-white`}>{d.bci.toFixed(1)}</td>
                <td data-testid="backtest-clash" className={`${TD} tabular-nums text-zinc-200`}>{d.clash.toFixed(1)}%</td>
                <td className={`${TD} font-medium ${CHURN_STYLE[d.churn]}`}>{cap(d.churn)}</td>
                <td className={TD}>{verdict(d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p data-testid="backtest-note" className="mt-4 text-xs text-zinc-400">{note}</p>
    </section>
  );
}
