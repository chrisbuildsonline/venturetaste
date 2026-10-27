"use client";

import { useState } from "react";
import { download, screenFilename, screenMarkdown } from "./export";
import { CHURN_STYLE, RecordedBanner, VERDICT_STYLE } from "./Results";
import { rankRows, recordedReason, type Found, type Row, type SortKey } from "./screen";

const TH = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-widest text-zinc-400";
const TD = "px-3 py-3 align-middle";
const SORT_BTN = "inline-flex min-h-11 items-center gap-1 uppercase tracking-widest hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300";

export default function ScreenTable({ acquirer, rows, found, onFull }: { acquirer: string; rows: Row[]; found?: Found | null; onFull: (target: string) => void }) {
  const [sort, setSort] = useState<SortKey>("bci");
  const ranked = rankRows(rows, sort);
  const recorded = recordedReason(rows) ?? found?.recorded;
  const th = (key: SortKey, label: string) => (
    <th scope="col" aria-sort={sort === key ? (key === "bci" ? "descending" : "ascending") : "none"} className={TH}>
      <button type="button" onClick={() => setSort(key)} className={SORT_BTN}>
        {label}
        <span aria-hidden>{sort === key ? (key === "bci" ? "↓" : "↑") : ""}</span>
      </button>
    </th>
  );
  let rank = 0;
  return (
    <section aria-label="Screening results" className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">{acquirer} screened against {rows.length} targets</h2>
      {found && <p data-testid="screen-found" className="mt-2 text-sm text-indigo-200">{found.line}</p>}
      {recorded && <RecordedBanner reason={recorded} className="mt-4" />}
      {rows.some((r) => r.state === "done") && (
        <button
          type="button"
          onClick={() => download(screenFilename(acquirer), screenMarkdown(rows, acquirer))}
          className="mt-4 min-h-11 rounded-xl border border-indigo-300/60 px-5 text-sm font-semibold text-indigo-100 transition hover:bg-indigo-400/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
        >
          Download table (.md)
        </button>
      )}
      <ul className="mt-4 space-y-3 sm:hidden" aria-label="Screening cards">
        {ranked.map((r) => (
          <li key={r.target} data-testid="screen-card" className="rounded-xl border border-white/10 bg-black/20 p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="font-medium text-white">{r.target}</p>
              {r.state === "done" && (
                <span data-testid="screen-card-verdict" className={`inline-block whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ring-1 ${VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.Pass}`}>{r.verdict}</span>
              )}
            </div>
            {found?.reasons?.[r.target] && <p className="mt-0.5 text-xs text-zinc-400">{found.reasons[r.target]}</p>}
            {r.state === "done" ? (
              <>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                  <div><dt className="text-xs uppercase tracking-widest text-zinc-400">BCI</dt><dd className="tabular-nums text-white">{r.bci.toFixed(1)}</dd></div>
                  <div><dt className="text-xs uppercase tracking-widest text-zinc-400">Clash</dt><dd className="tabular-nums text-zinc-200">{r.clash.toFixed(1)}%</dd></div>
                  <div><dt className="text-xs uppercase tracking-widest text-zinc-400">Churn</dt><dd className={`font-medium ${CHURN_STYLE[r.churn]}`}>{r.churn.charAt(0).toUpperCase() + r.churn.slice(1)}</dd></div>
                </dl>
                <button
                  type="button"
                  aria-label={`Full diligence for ${r.target}`}
                  onClick={() => onFull(r.target)}
                  className="mt-3 min-h-11 w-full rounded-full border border-white/15 px-3.5 text-sm text-zinc-200 transition hover:border-indigo-300 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
                >
                  Full diligence
                </button>
              </>
            ) : r.state === "pending" ? (
              <p className="mt-3 text-sm text-zinc-400">Screening…</p>
            ) : (
              <p className="mt-3 text-sm text-rose-200">{r.error}</p>
            )}
          </li>
        ))}
      </ul>
      <div className="relative mt-4 hidden overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 sm:block" role="region" aria-label="Screening table" tabIndex={0}>
        <table data-testid="screen-table" className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-white/10">
              <th scope="col" className={TH}>Rank</th>
              <th scope="col" className={TH}>Target</th>
              {th("bci", "BCI")}
              {th("clash", "Culture clash")}
              <th scope="col" className={TH}>Churn risk</th>
              <th scope="col" className={TH}>Verdict</th>
              <th scope="col" className={TH}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r) => (
              <tr key={r.target} data-testid="screen-row" data-target={r.target} className="border-b border-white/5 last:border-0">
                <td className={`${TD} tabular-nums text-zinc-400`}>{r.state === "done" ? ++rank : "–"}</td>
                <th scope="row" className={`${TD} text-left font-medium text-white`}>
                  {r.target}
                  {found?.reasons?.[r.target] && <p data-testid="screen-reason" className="mt-0.5 text-xs font-normal text-zinc-400">{found.reasons[r.target]}</p>}
                </th>
                {r.state === "done" ? (
                  <>
                    <td data-testid="screen-bci" className={`${TD} tabular-nums text-white`}>{r.bci.toFixed(1)}</td>
                    <td data-testid="screen-clash" className={`${TD} tabular-nums text-zinc-200`}>{r.clash.toFixed(1)}%</td>
                    <td className={`${TD} font-medium ${CHURN_STYLE[r.churn]}`}>{r.churn.charAt(0).toUpperCase() + r.churn.slice(1)}</td>
                    <td className={TD}>
                      <span data-testid="screen-verdict" className={`inline-block whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ring-1 ${VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.Pass}`}>{r.verdict}</span>
                    </td>
                    <td className={`${TD} text-right`}>
                      <button
                        type="button"
                        aria-label={`Full diligence for ${r.target}`}
                        onClick={() => onFull(r.target)}
                        className="min-h-11 whitespace-nowrap rounded-full border border-white/15 px-3.5 text-sm text-zinc-200 transition hover:border-indigo-300 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
                      >
                        Full diligence
                      </button>
                    </td>
                  </>
                ) : r.state === "pending" ? (
                  <td colSpan={5} className={`${TD} text-zinc-400`}>Screening…</td>
                ) : (
                  <td colSpan={5} className={`${TD} text-rose-200`}>{r.error}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
