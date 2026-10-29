"use client";

import { useState } from "react";
import { download, screenFilename, screenMarkdown } from "./export";
import { CHURN_STYLE, RecordedBanner, VERDICT_STYLE } from "./Results";
import { rankRows, recordedReason, type Found, type Row, type SortKey } from "./screen";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const SORT_BTN = "inline-flex min-h-11 items-center gap-1 uppercase tracking-[0.12em] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-lime/60";

export default function ScreenTable({ acquirer, rows, found, onFull }: { acquirer: string; rows: Row[]; found?: Found | null; onFull: (target: string) => void }) {
  const [sort, setSort] = useState<SortKey>("bci");
  const ranked = rankRows(rows, sort);
  const recorded = recordedReason(rows) ?? found?.recorded;
  const done = rows.filter((r) => r.state === "done").length;
  const th = (key: SortKey, label: string) => (
    <th scope="col" aria-sort={sort === key ? (key === "bci" ? "descending" : "ascending") : "none"} className="th">
      <button type="button" onClick={() => setSort(key)} className={SORT_BTN}>
        {label}
        <span aria-hidden>{sort === key ? (key === "bci" ? "↓" : "↑") : ""}</span>
      </button>
    </th>
  );
  let rank = 0;
  return (
    <section aria-label="Screening results" className="card rise p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="eyebrow">{acquirer} screened against {rows.length} targets</h2>
          <p className="mt-1 text-xl font-semibold tracking-tight text-white sm:text-2xl">Target screen: {acquirer}</p>
          {found && <p data-testid="screen-found" className="mt-1 text-sm text-lime">{found.line}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className="num text-xs text-zinc-400">{done} of {rows.length} scored</span>
          {done > 0 && (
            <button type="button" onClick={() => download(screenFilename(acquirer), screenMarkdown(rows, acquirer))} className="btn btn-ghost">
              Download table (.md)
            </button>
          )}
        </div>
      </div>
      {recorded && <RecordedBanner reason={recorded} className="mt-4" />}
      <ul className="mt-4 space-y-3 sm:hidden" aria-label="Screening cards">
        {ranked.map((r) => (
          <li key={r.target} data-testid="screen-card" className="well p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="font-medium text-white">{r.target}</p>
              {r.state === "done" && (
                <span data-testid="screen-card-verdict" className={VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.Pass}>{r.verdict}</span>
              )}
            </div>
            {found?.reasons?.[r.target] && <p className="mt-0.5 text-xs text-zinc-400">{found.reasons[r.target]}</p>}
            {r.state === "done" ? (
              <>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
                  <div><dt className="eyebrow">BCI</dt><dd className="num mt-0.5 text-lg font-semibold text-white">{r.bci.toFixed(1)}</dd></div>
                  <div><dt className="eyebrow">Clash</dt><dd className="num mt-0.5 text-lg font-semibold text-zinc-200">{r.clash.toFixed(1)}%</dd></div>
                  <div><dt className="eyebrow">Churn</dt><dd className={`mt-0.5 text-lg font-semibold ${CHURN_STYLE[r.churn]}`}>{cap(r.churn)}</dd></div>
                </dl>
                <button type="button" aria-label={`Full diligence for ${r.target}`} onClick={() => onFull(r.target)} className="btn btn-ghost mt-3 w-full">
                  Full diligence
                </button>
              </>
            ) : r.state === "pending" ? (
              <p className="mt-3 flex items-center gap-2 text-sm text-zinc-400"><span className="size-2 animate-pulse rounded-full bg-lime" />Screening…</p>
            ) : (
              <p className="mt-3 text-sm text-rose-200">{r.error}</p>
            )}
          </li>
        ))}
      </ul>
      <div className="relative mt-4 hidden overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-lime/60 sm:block" role="region" aria-label="Screening table" tabIndex={0}>
        <table data-testid="screen-table" className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-white/10">
              <th scope="col" className="th">Rank</th>
              <th scope="col" className="th">Target</th>
              {th("bci", "BCI")}
              {th("clash", "Culture clash")}
              <th scope="col" className="th">Churn risk</th>
              <th scope="col" className="th">Verdict</th>
              <th scope="col" className="th"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r) => (
              <tr key={r.target} data-testid="screen-row" data-target={r.target} className="row">
                <td className="td num text-zinc-500">{r.state === "done" ? `#${++rank}` : "–"}</td>
                <th scope="row" className="td text-left font-medium text-white">
                  {r.target}
                  {found?.reasons?.[r.target] && <p data-testid="screen-reason" className="mt-0.5 text-xs font-normal text-zinc-400">{found.reasons[r.target]}</p>}
                </th>
                {r.state === "done" ? (
                  <>
                    <td data-testid="screen-bci" className="td">
                      <span className="num text-base font-semibold text-white">{r.bci.toFixed(1)}</span>
                      <span className="mt-1 block h-1 w-20 rounded-full bg-white/[0.06]" aria-hidden><span className="block h-full rounded-full bg-lime" style={{ width: `${r.bci}%` }} /></span>
                    </td>
                    <td data-testid="screen-clash" className="td num text-zinc-200">{r.clash.toFixed(1)}%</td>
                    <td className={`td font-medium ${CHURN_STYLE[r.churn]}`}>{cap(r.churn)}</td>
                    <td className="td">
                      <span data-testid="screen-verdict" className={VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.Pass}>{r.verdict}</span>
                    </td>
                    <td className="td text-right">
                      <button type="button" aria-label={`Full diligence for ${r.target}`} onClick={() => onFull(r.target)} className="inline-flex min-h-11 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-lime hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-lime/60">
                        Full diligence <span aria-hidden>→</span>
                      </button>
                    </td>
                  </>
                ) : r.state === "pending" ? (
                  <td colSpan={5} className="td text-zinc-400"><span className="inline-flex items-center gap-2"><span className="size-2 animate-pulse rounded-full bg-lime" />Screening…</span></td>
                ) : (
                  <td colSpan={5} className="td text-rose-200">{r.error}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
