"""Four real deals scored on the recorded Qloo fixtures: a sanity check of BCI and culture clash, not a calibration."""

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Deal:
    acquirer_label: str  # who really bought, with the Qloo brand used as the proxy
    target_label: str
    acquirer: str  # the Qloo brand entity actually scored
    target: str
    year: int
    outcome: str
    outcome_class: str  # "kept" | "sold at a loss" | "blocked"


DEALS = (
    Deal("Nike", "Converse", "Nike", "Converse", 2003,
         "Nike paid $305M; still owned 20+ years later, a ~$2B-revenue brand", "kept"),
    Deal("VF Corp (as Vans)", "Supreme", "Vans", "Supreme", 2020,
         "Sold to EssilorLuxottica in 2024 for $1.5B (paid $2.1B)", "sold at a loss"),
    Deal("Tapestry (as Coach)", "Capri (as Michael Kors)", "Coach", "Michael Kors", 2023,
         "$8.5B deal; FTC sued, a court blocked it in Oct 2024, called off in Nov 2024", "blocked"),
    Deal("Adidas", "Reebok", "Adidas", "Reebok", 2006,
         "Paid ~$3.8B; sold to Authentic Brands in 2021 for up to EUR 2.1B", "sold at a loss"),
)

NOTE = (
    "4 deals is a sanity check, not a calibration. Scores use today's Qloo audiences, not the audiences at deal time, "
    "and holding companies are scored through their flagship brand."
)

_cache: dict[str, Any] | None = None
_lock = threading.Lock()  # concurrent first visitors wait for one computation instead of each running four pipelines


def backtest() -> dict[str, Any]:
    """Each deal scored with the normal diligence pipeline on recorded fixtures (no key, no network, no LLM)."""
    global _cache
    with _lock:
        if _cache is None:
            from api.main import fixture_client
            from api.pipeline import run_diligence

            client = fixture_client()
            deals = []
            for d in DEALS:
                r = run_diligence(client, d.acquirer, d.target, None)
                s = r["scores"]
                deals.append({
                    "acquirer_label": d.acquirer_label, "target_label": d.target_label,
                    "acquirer": d.acquirer, "target": d.target, "year": d.year,
                    "outcome": d.outcome, "outcome_class": d.outcome_class,
                    "bci": s["bci"], "clash": s["culture_clash"], "churn": s["churn_risk"], "verdict": r["memo"]["verdict"],
                })
            _cache = {"deals": deals, "note": NOTE}
        return _cache


if __name__ == "__main__":  # bun run backtest: the README table
    print("| Deal | Year | Outcome | BCI | Clash | Churn | Verdict |\n|---|---|---|---|---|---|---|")
    for r in backtest()["deals"]:
        print(f"| {r['acquirer_label']} + {r['target_label']} | {r['year']} | {r['outcome']} | {r['bci']} | {r['clash']} | {r['churn']} | {r['verdict']} |")
