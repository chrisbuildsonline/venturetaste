# VentureTaste

An autonomous 4-agent M&A and venture diligence pipeline that leverages Qloo's 250M entity graph to deterministically quantify brand synergy, customer retention overlap, and cultural churn risk for consumer brand acquisitions.

Built for [Qloo Agentic Hackathon](https://qloo.devpost.com/). Submissions close 2026-10-30.

## What it does

An autonomous 4-agent M&A and venture diligence pipeline that leverages Qloo's 250M entity graph to deterministically quantify brand synergy, customer retention overlap, and cultural churn risk for consumer brand acquisitions.

## Stack

Python, FastAPI, Qloo Taste AI API, LangGraph, Pydantic, Next.js, Tailwind, Recharts.

## How to run

Needs [bun](https://bun.sh), [uv](https://docs.astral.sh/uv/) and Python 3.12.

```
bun run setup                     # uv sync + bun install in web/
(cd web && bunx playwright install chromium)  # once, for e2e
bun run build                     # static export to web/out
bun run start                     # FastAPI + web on http://127.0.0.1:8765
bun run dev                       # API with reload + next dev
bun run test                      # pytest
bun run typecheck                 # tsc + mypy
bun run e2e                       # build, then Playwright against FastAPI on :8765
```

## Diligence pipeline

`POST /api/diligence` with `{"acquirer": "Nike", "target": "Adidas"}` runs four agents as a LangGraph `StateGraph` (`api/pipeline.py`, no LLM) and returns one report: resolved brands, scores, `domain_overlap` for all 7 domains (no data = 0), top shared and clashing tastes, demographics for both brands, the memo, and a per-agent `trace` (agent, status, ms, Qloo calls).

1. **Scout** resolves both brand names to Qloo entities.
2. **Cartographer** fetches insights for all 7 domains plus demographics for both brands (16 calls, in parallel threads; 18 Qloo calls per run with the two searches). Insights use `take=50`, the most Qloo allows.
3. **Analyst** scores the pair with `api/scoring.py`.
4. **Partner** writes the deal memo from templates: a verdict (`Proceed`, `Proceed with conditions`, `Pass`), rationale and risks that name real Qloo entities from the data.

Errors: unknown brand or a brand with no taste data is 422 with a message naming the brand, missing `QLOO_API_KEY` is 503, a Qloo failure is 502. Qloo rate limits (HTTP 429) are retried with backoff.

`GET /api/presets` lists the demo pairs (verified live, `api/presets.py`):

- **Nike + Adidas**: high synergy.
- **Patagonia + The North Face**: mixed, shared outdoor tastes.
- **Patagonia + Gucci**: culture clash.

`bun run record` re-records the fixtures for the preset brands; `bun run probe` scores candidate pairs live.

## Scoring

`api/scoring.py` is pure (no I/O, no LLM). `score(a, b)` compares two brand profiles:

- **Domain overlap** (0..1, per domain in brand, artist, movie, tv_show, place, destination, book): weighted Jaccard over entity ids, weight = affinity clamped at 0: `sum(min(wa, wb)) / sum(max(wa, wb))` over the union of ids. Both empty (or all weights 0) gives 0. Domains empty for both brands are left out. A domain with entities for one brand only scores 0.
- **Mean overlap**: mean of the domain overlaps (0 if there are none).
- **Demographic distance** (0..1): over the union of age and gender keys (missing = 0), `mean(|a - b|) / 2`, clamped.
- **BCI** (0..100): `100 * (0.7 * mean_overlap + 0.3 * (1 - demographic_distance))`.
- **Culture Clash %** (0..100): `100 * (0.7 * (1 - mean_overlap) + 0.3 * demographic_distance)`.
- **Churn-risk band**: from Culture Clash, below 33 is `low`, below 66 is `medium`, otherwise `high`.
- **Top shared tastes**: entities in both lists of a domain, ranked by the lower of the two affinities, top 5. **Top clashing tastes**: entities with positive affinity for one brand and absent from the other's list, ranked by affinity, top 5 per brand.

Rounding: BCI and Culture Clash to 1 decimal, everything else to 4.

## License

MIT, see LICENSE.
