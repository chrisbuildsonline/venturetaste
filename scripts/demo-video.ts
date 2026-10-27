// Records the demo video (2 to 3 min) with an edge-tts voice track and a quiet synthesized pad: the problem and who pays, two real
// runs and a target screen in the actual UI, how the pipeline works, and the real test counts.
// Needs bun, uv (uvicorn, pytest, edge-tts via uvx), ffmpeg/ffprobe and Playwright's chromium (cd web && bunx playwright install chromium).
// Runs its own server on :8766 in fixture mode (recorded Qloo responses, no key needed).
// bun run demo:video -> out/venturetaste-demo.mp4
import { chromium, type Page } from '../web/node_modules/@playwright/test';
import { mkdtempSync, mkdirSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ROOT = join(import.meta.dir, '..');
const PORT = 8766;
const BASE = `http://127.0.0.1:${PORT}`;
const TMP = mkdtempSync(join(tmpdir(), 'vt-demo-'));
const OUT = join(ROOT, 'out');
const VOICE = 'en-US-AndrewNeural';
const LIVE_URL = 'https://venturetaste.5-78-152-178.sslip.io';
const REPO_URL = 'https://github.com/chrisbuildsonline/venturetaste';
type Clip = { file: string; ms: number };

let n = 0;
async function tts(text: string): Promise<Clip> {
  const file = join(TMP, `${String(n++).padStart(3, '0')}.mp3`);
  // edge-tts sometimes stalls on the network: give each try 30 s, three tries.
  for (let tryNo = 1; ; tryNo++) {
    const p = Bun.spawn(['timeout', '30', 'uvx', 'edge-tts', '--voice', VOICE, '--rate=+8%', '--text', text, '--write-media', file], { stderr: 'pipe' });
    if (!(await p.exited)) break;
    if (tryNo === 3) throw new Error(`edge-tts failed: ${await new Response(p.stderr).text()}`);
  }
  const d = Bun.spawnSync(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]);
  return { file, ms: Math.round(Number(d.stdout.toString()) * 1000) };
}

function run(cmd: string[]) {
  const p = Bun.spawnSync(cmd, { cwd: ROOT, env: { ...process.env, CI: '1' } });
  const out = p.stdout.toString() + p.stderr.toString();
  if (p.exitCode) throw new Error(`${cmd.join(' ')} failed:\n${out.slice(-2000)}`);
  return out;
}
const grab = (text: string, re: RegExp, what: string) => {
  const m = text.match(re);
  if (!m) throw new Error(`could not read ${what} from the test output`);
  return m[1]!;
};

// ---- 1. real gate results, shown on the tests slide (the video is not made from a red build) ----
console.log('running the gates...');
const tests = run(['bun', 'run', 'test']);
run(['bun', 'run', 'typecheck']);
const pyPassed = grab(tests, /(\d+) passed/, 'pytest passes');
const bunPass = grab(tests, /(\d+) pass\b/, 'bun test passes');
console.log(`pytest ${pyPassed} passed, bun ${bunPass} pass`);
run(['bun', 'run', 'build']);

// ---- 2. our own server (fixture mode: recorded Qloo responses) ----
if (await fetch(`${BASE}/api/health`).then(() => true, () => false)) throw new Error(`port ${PORT} is busy: stop the old server first`);
const server = Bun.spawn([join(ROOT, '.venv/bin/uvicorn'), 'api.main:app', '--port', String(PORT)], {
  cwd: ROOT,
  env: { ...process.env, VENTURETASTE_FIXTURES: '1' },
  stdout: 'ignore', stderr: 'inherit',
});
let secs = '0';
let webm = '';
const clips: { file: string; at: number }[] = [];
const out = join(OUT, 'venturetaste-demo.mp4');
try {
  for (let i = 0; ; i++) {
    try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch {}
    if (i > 100) throw new Error('server did not start');
    await Bun.sleep(200);
  }

  // ---- 3. slides ----
  const CSS = `
:root{--ink:#e4e4f0;--dim:#9a9ab5;--line:#2a2a45;--a1:#818cf8;--ok:#34d399;--hot:#fb7185}
*{box-sizing:border-box}
body{margin:0;height:100vh;background:#0b0b18;color:var(--ink);font:19px/1.45 Inter,system-ui,sans-serif;overflow:hidden}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(ellipse 60% 50% at 85% 0%,#1e1b4b 0%,transparent 70%),radial-gradient(ellipse 50% 40% at 0% 100%,#2e1065 0%,transparent 70%);z-index:-1}
.stage{position:absolute;inset:0;padding:40px 56px 56px;display:flex;flex-direction:column;animation:enter .7s cubic-bezier(.2,.7,.2,1) both}
@keyframes enter{from{opacity:0;transform:translateY(14px)}}
.eyebrow{font:600 13px Inter;letter-spacing:.16em;text-transform:uppercase;color:var(--a1);margin-bottom:6px}
h1{font:700 36px/1.15 Inter;letter-spacing:-.02em;margin:0 0 8px}
.lead{color:var(--dim);margin:0 0 22px;font-size:18px}
.card{background:#14142a;border:1px solid var(--line);border-radius:16px;padding:16px 20px}
.card b{font-weight:600}
.cols{display:grid;gap:18px}
.in{animation:enter .6s cubic-bezier(.2,.7,.2,1) both}
.mono{font:15px/1.6 ui-monospace,'JetBrains Mono',monospace}
.chip{display:inline-block;font:500 13px ui-monospace,monospace;background:#1e1b4b;color:#c7d2fe;border:1px solid #3730a3;border-radius:8px;padding:2px 8px;margin:4px 4px 0 0}
.dim{color:var(--dim);font-size:16px}
.big{font:700 64px/1 Inter;letter-spacing:-.03em;color:var(--ok)}
`;
  const slide = (body: string) => `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body><div class="stage">${body}</div></body></html>`;
  const card = (d: number, inner: string) => `<div class="card in" style="animation-delay:${d}s">${inner}</div>`;

  const TITLE = slide(`<div class="eyebrow">Powered by Qloo taste data</div><h1 style="font-size:56px">VentureTaste</h1>
<p class="lead" style="font-size:22px">Taste-graph due diligence for consumer brand deals</p>
<div class="cols" style="grid-template-columns:1fr 1fr;flex:1;align-content:start">
  ${card(0.6, `<div class="eyebrow">The problem</div><b>The spreadsheet misses the customer.</b><p class="dim">Revenue and margin say nothing about whether the two audiences overlap (cannibalization) or clash (churn after the deal).</p>`)}
  ${card(1.2, `<div class="eyebrow">Who pays</div><b>Deal teams buying consumer brands</b><p class="dim">Corporate development teams, PE and VC consumer-brand investors, and M&amp;A advisors. Priced per seat as SaaS, or per diligence report.</p>`)}
</div>`);

  const agent = (d: number, name: string, role: string, detail: string) => card(d, `<div class="eyebrow">${name}</div><b>${role}</b><p class="dim" style="margin:6px 0 0;font-size:14.5px">${detail}</p>`);
  const HOW = slide(`<div class="eyebrow">How it works</div><h1>Four agents, deterministic scoring, no LLM</h1><p class="lead">Every number and every memo sentence comes from Qloo data and fixed formulas.</p>
<div class="cols" style="grid-template-columns:repeat(4,1fr)">
  ${agent(0.3, 'Scout', 'Resolves both brands', 'Qloo <span class="chip">/search</span>')}
  ${agent(0.9, 'Cartographer', 'Maps tastes and audiences', '<span class="chip">/v2/insights</span> per domain (7), <span class="chip">urn:demographics</span>')}
  ${agent(1.5, 'Analyst', 'Scores, then decides', 'Overlap in under 4 of 7 domains: probes <span class="chip">urn:tag</span> for bridging tastes')}
  ${agent(2.1, 'Partner', 'Writes the deal memo', 'From templates, naming real Qloo entities')}
</div>
<div class="card in mono" style="margin-top:20px;animation-delay:4s;font-size:15.5px">
  BCI = 100 * (0.7 * mean weighted-Jaccard overlap + 0.3 * (1 - demographic distance))<br>
  Culture clash = 100 * (0.7 * mean exclusive taste mass + 0.3 * demographic distance)<br>
  <span style="color:var(--hot)">Pass</span> if clash &gt;= 66 &nbsp;·&nbsp; <span style="color:var(--ok)">Proceed</span> if BCI &gt;= 50 &nbsp;·&nbsp; else <span style="color:#fbbf24">Proceed with conditions</span>
</div>`);

  const TESTS = slide(`<div class="eyebrow">Run just now, before this recording</div><h1>Tested</h1><p class="lead">The numbers come from the run that preceded this video.</p>
<div class="cols" style="grid-template-columns:repeat(3,1fr)">
  ${card(0.3, `<div class="big">${pyPassed}</div><p class="dim">pytest tests passed (API, scoring, pipeline)</p>`)}
  ${card(1.0, `<div class="big">${bunPass}</div><p class="dim">bun tests passed (web screening logic)</p>`)}
  ${card(1.7, `<div class="big">0</div><p class="dim">type errors: tsc and mypy clean</p>`)}
</div>
<div class="card in mono" style="margin-top:22px;animation-delay:2.6s">$ bun run test &nbsp;<span style="color:var(--ok)">✓ ${pyPassed} passed · ${bunPass} pass</span><br>$ bun run typecheck &nbsp;<span style="color:var(--ok)">✓ no errors</span></div>`);

  const OUTRO = slide(`<div style="margin:auto;text-align:center">
  <h1 class="in" style="font-size:56px">VentureTaste</h1>
  <p class="lead in" style="font-size:22px;animation-delay:.4s">Do these customers overlap, or clash? Ask Qloo before you sign.</p>
  <div class="card in mono" style="display:inline-block;text-align:left;animation-delay:.9s">Live: ${LIVE_URL}<br>Code: ${REPO_URL}</div>
</div>`);

  // ---- 4. voice lines, synthesized up front so the recording never waits on edge-tts ----
  const N = {
    title: tts("VentureTaste is due diligence for consumer brand deals, built on Qloo's taste graph. When a company buys a brand, the spreadsheet shows revenue and margin, but not whether the two customer bases overlap or clash. Overlap means cannibalization. Clash means churn. The buyers are corporate development teams, private equity and venture investors in consumer brands, and M and A advisors. We would charge per seat as a SaaS tool, or per diligence report."),
    nike: tts('Here is the real app. This recording replays recorded Qloo responses, so it needs no key. Nike and Adidas: one click on the preset. Four agents run in order, and each reports its time and how many Qloo calls it made. The radar shows taste overlap across seven domains. The brand cannibalization index is 53.9, the verdict is Proceed, and the deal memo names real entities from the Qloo data.'),
    gucci: tts('Now Patagonia and Gucci. Qloo finds no shared taste in any domain. The Analyst agent notices, and decides to probe Qloo tags for both brands, looking for bridging tastes the two audiences have in common. Its decision line is on the card. The bridges are evidence only, they never change the score. Culture clash is 75.7, so the verdict is Pass.'),
    screen: tts('Screen targets mode ranks one acquirer against several candidates. Nike against Adidas, Puma, Lululemon and Gucci. Each target gets a full diligence run, and the ranked table fills in as they finish.'),
    how: tts('How it works. Scout resolves both brands with Qloo search. Cartographer pulls insights for seven domains, plus demographics. The Analyst scores the pair in plain code, and if most domains show no overlap, it probes Qloo tags. Partner writes the memo from templates. There is no LLM anywhere: the scoring is deterministic, and the agents decide from Qloo data. The index is seventy percent weighted overlap plus thirty percent demographic similarity. Culture clash is seventy percent exclusive taste plus thirty percent demographic distance. Pass when clash is at least sixty six. Proceed when the index is at least fifty. Otherwise, proceed with conditions.'),
    tests: tts(`Before this recording, the test suite ran. ${pyPassed} Python tests and ${bunPass} web tests passed, and the type checks are clean.`),
    outro: tts('VentureTaste. Do these customers overlap, or clash? Ask Qloo before you sign. The live app and the code are on screen.'),
  };
  await Promise.all(Object.values(N));

  // ---- 5. recording ----
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, colorScheme: 'dark', recordVideo: { dir: TMP, size: { width: 1280, height: 720 } } });
  const page: Page = await ctx.newPage();
  const t0 = Date.now();
  const now = () => Date.now() - t0;

  // Plays a narration clip; the steps run spread across it (for reveals in sync with the voice).
  async function narrate(clip: Promise<Clip>, steps: (() => Promise<unknown>)[] = []) {
    const c = await clip;
    const at = now();
    clips.push({ file: c.file, at });
    for (const step of steps) { await step(); await Bun.sleep(c.ms / (steps.length + 1)); }
    await Bun.sleep(Math.max(0, c.ms - (now() - at)) + 350);
  }
  async function show(html: string) {
    await page.setContent(html, { waitUntil: 'load' });
  }
  const glide = (testId: string, block: 'start' | 'center' = 'start') =>
    page.getByTestId(testId).evaluate((el, b) => el.scrollIntoView({ behavior: 'smooth', block: b }), block);
  const preset = async (label: string, bci: string, verdict: string) => {
    await page.goto(BASE);
    await Bun.sleep(900);
    await page.getByRole('button', { name: label, exact: true }).click();
    await page.getByTestId('bci-value').waitFor();
    await page.getByTestId('memo').waitFor();
    for (const a of ['Scout', 'Cartographer', 'Analyst', 'Partner']) {
      if ((await page.getByTestId(`agent-${a}`).getAttribute('data-state')) !== 'done') throw new Error(`agent ${a} not done`);
    }
    return { bci: await page.getByTestId('bci-value').innerText(), verdict: await page.getByTestId('verdict').innerText(), expect: { bci, verdict } };
  };
  const check = (r: Awaited<ReturnType<typeof preset>>) => {
    if (r.bci !== r.expect.bci || r.verdict !== r.expect.verdict) throw new Error(`narration says ${r.expect.bci} ${r.expect.verdict}, the app shows ${r.bci} ${r.verdict}`);
  };

  await show(TITLE);
  await Bun.sleep(900);
  await narrate(N.title);

  // Nike + Adidas in the real UI
  await page.goto(BASE);
  await narrate(N.nike, [
    async () => { check(await preset('Nike + Adidas', '53.9', 'Proceed')); },
    () => glide('radar', 'center'),
    () => glide('memo'),
  ]);

  // Patagonia + Gucci: zero overlap, the Analyst probes tags
  await narrate(N.gucci, [
    async () => {
      check(await preset('Patagonia + Gucci', '24.3', 'Pass'));
      const clash = await page.getByTestId('clash-value').innerText();
      if (clash !== '75.7%') throw new Error(`narration says 75.7, the app shows ${clash}`);
      const decision = await page.getByTestId('decision-Analyst').innerText();
      if (!decision.includes('probed Qloo tags')) throw new Error(`Analyst did not probe tags: ${decision}`);
      await page.getByTestId('decision-Analyst').scrollIntoViewIfNeeded();
    },
    () => glide('bridges', 'center'),
    () => glide('verdict', 'center'),
  ]);

  // Screen targets mode
  await narrate(N.screen, [
    async () => {
      await page.goto(BASE);
      await Bun.sleep(600);
      await page.getByRole('group', { name: 'Mode' }).getByRole('button', { name: 'Screen targets' }).click();
      await Bun.sleep(900);
      await page.getByRole('button', { name: 'Nike: 4 targets' }).click();
    },
    async () => {
      await page.getByTestId('screen-row').nth(3).waitFor();
      await page.getByText('Screening…').waitFor({ state: 'detached' });
      await glide('screen-table', 'center');
    },
  ]);

  await show(HOW);
  await narrate(N.how);
  await show(TESTS);
  await narrate(N.tests);
  await show(OUTRO);
  await narrate(N.outro);
  await Bun.sleep(1200);

  secs = (now() / 1000).toFixed(2);
  await ctx.close();
  await browser.close();
  webm = join(TMP, readdirSync(TMP).find((f) => f.endsWith('.webm'))!);
} finally {
  server.kill();
}

// ---- 6. mix: voice + a quiet synthesized pad (no licensed music) that ducks under speech; encode ----
mkdirSync(OUT, { recursive: true });
// Two soft chords crossfading every 8 s, low-passed, with a slow swell and a touch of echo.
const chord = (f: number[]) => f.map((hz, i) => `${(0.5 / (i + 1)).toFixed(2)}*sin(2*PI*${hz}*t+0.6*sin(2*PI*0.13*t))`).join('+');
const pad = `aevalsrc='(0.5+0.5*cos(2*PI*t/16))*(${chord([220, 277.18, 329.63, 493.88])})+(0.5-0.5*cos(2*PI*t/16))*(${chord([185, 220, 277.18, 329.63])})':s=48000:d=${secs},`
  + `lowpass=f=1100,aecho=0.8:0.6:180|360:0.25|0.15,volume=0.022,afade=t=in:d=2.5,afade=t=out:st=${(Number(secs) - 3).toFixed(2)}:d=3[pad]`;
const inputs = clips.flatMap((c) => ['-i', c.file]);
const voices = clips.map((c, i) => `[${i + 1}:a]adelay=${c.at}|${c.at}[a${i}]`).join(';')
  + `;${clips.map((_, i) => `[a${i}]`).join('')}amix=inputs=${clips.length}:normalize=0,asplit[v1][v2]`;
const mix = `${voices};${pad};[pad][v2]sidechaincompress=threshold=0.015:ratio=6:attack=30:release=600[duck];[v1][duck]amix=inputs=2:normalize=0,alimiter=limit=0.9[aud]`;
const ff = Bun.spawnSync(['ffmpeg', '-y', '-v', 'error', '-i', webm, ...inputs, '-filter_complex', `[0:v]scale=1920:1080:flags=lanczos,fps=30[v];${mix}`,
  '-map', '[v]', '-map', '[aud]', '-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', out], { stderr: 'inherit' });
if (ff.exitCode) throw new Error('ffmpeg failed');

// ---- 7. assertions on the finished file ----
const probe = JSON.parse(Bun.spawnSync(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', out]).stdout.toString());
const v = probe.streams.find((s: { codec_type: string }) => s.codec_type === 'video');
const a = probe.streams.find((s: { codec_type: string }) => s.codec_type === 'audio');
const dur = Number(probe.format.duration);
const failures = [
  v?.width !== 1920 && `width ${v?.width}`,
  v?.height !== 1080 && `height ${v?.height}`,
  v?.codec_name !== 'h264' && `video codec ${v?.codec_name}`,
  !a && 'no audio stream',
  !(dur >= 120 && dur <= 180) && `duration ${dur.toFixed(1)} s, wanted 120 to 180`,
].filter(Boolean);
if (failures.length) { console.error(`demo video failed: ${failures.join('; ')}`); process.exit(1); }
console.log(`demo video: ${out} (${v.width}x${v.height} ${v.codec_name}, ${a.codec_name} audio, ${dur.toFixed(1)} s)`);
