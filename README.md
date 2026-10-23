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

## License

MIT, see LICENSE.
