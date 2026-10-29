import { rankRows, type Row } from "./screen";
import { label, type Diligence } from "./types";

const day = (d: Date) => d.toISOString().slice(0, 10);
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const cell = (s: string) => s.replaceAll("|", "\\|").replace(/\s*\n\s*/g, " ");

export const memoFilename = (d: Diligence) => `venturetaste-${slug(d.brands.acquirer.name)}-${slug(d.brands.target.name)}.md`;
export const screenFilename = (acquirer: string) => `venturetaste-screen-${slug(acquirer)}.md`;

/** The deal memo as markdown: the same facts the Results page shows. */
export function memoMarkdown(d: Diligence, now: Date = new Date()): string {
  const { scores, memo, brands } = d;
  const pair = `${brands.acquirer.name} + ${brands.target.name}`;
  return [
    `# Deal memo: ${pair}`,
    "",
    `**Verdict:** ${memo.verdict}`,
    "",
    `**Fit:** ${d.fit.label}. ${d.fit.note}`,
    "",
    memo.headline,
    "",
    `- **Brand Cannibalization Index:** ${scores.bci.toFixed(1)} / 100`,
    `- **Culture clash:** ${scores.culture_clash.toFixed(1)}%`,
    `- **Churn risk:** ${cap(scores.churn_risk)}`,
    ...(d.probed_tags ? [`- **Bridge potential:** ${d.bridge_potential} / 100`] : []),
    "",
    ...(d.bridges.length
      ? [
          "## Bridging tastes",
          "",
          ...d.bridges.map((b) => `- ${b.name} (${brands.acquirer.name} ${b.affinity_acquirer.toFixed(2)} / ${brands.target.name} ${b.affinity_target.toFixed(2)})`),
          "",
        ]
      : []),
    ...(d.bridge_picks.length
      ? [`## Follow-up: ${label(d.bridge_picks[0].domain)} via ${d.bridge_picks[0].tag_name}`, "", ...d.bridge_picks.map((p) => `- ${p.name}`), ""]
      : []),
    "## Taste overlap by domain",
    "",
    "| Domain | Overlap |",
    "| --- | --- |",
    ...Object.entries(d.domain_overlap).map(([k, v]) => `| ${label(k)} | ${Math.round(v * 100)}% |`),
    "",
    "## Rationale",
    "",
    ...memo.rationale.map((r) => `- ${r}`),
    "",
    "## Risks",
    "",
    ...memo.risks.map((r) => `- ${r}`),
    "",
    "---",
    "",
    `**Memo written by:** ${memo.author ?? "template"}  `,
    `**Data source:** ${d.recorded ? `recorded Qloo data (${d.recorded.reason})` : "live Qloo"}  `,
    `**Date:** ${day(now)}`,
    "",
  ].join("\n");
}

/** The ranked screening table as markdown, same columns as the on-screen table. */
export function screenMarkdown(rows: Row[], acquirer = "", now: Date = new Date()): string {
  let rank = 0;
  const lines = rankRows(rows, "bci").map((r) =>
    r.state === "done"
      ? `| ${++rank} | ${cell(r.target)} | ${r.bci.toFixed(1)} | ${r.clash.toFixed(1)}% | ${cap(r.churn)} | ${r.verdict} |`
      : `| – | ${cell(r.target)} | ${r.state === "error" ? cell(r.error) : "Screening…"} |`,
  );
  return [
    `# ${acquirer ? `${acquirer} screened` : "Screened"} against ${rows.length} targets`,
    "",
    `Date: ${day(now)}`,
    "",
    "| Rank | Target | BCI | Culture clash | Churn risk | Verdict |",
    "| --- | --- | --- | --- | --- | --- |",
    ...lines,
    "",
  ].join("\n");
}

/** Saves text as a file through a temporary <a download>. */
export function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url)); // revoking at once can cancel the download in Firefox
}
