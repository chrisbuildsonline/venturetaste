"""Live probe: nonsense search, max take, candidate pair scores. Run: bun run probe"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from api.pipeline import run_diligence
from api.presets import PRESETS
from api.qloo import DOMAINS, QlooClient, QlooError
from api.scoring import BrandProfile, bridges, score

PAIRS = [
    ("Nike", "Adidas"),
    ("Nike", "Puma"),
    ("Coca-Cola", "Pepsi"),
    ("Patagonia", "The North Face"),
    ("Patagonia", "Gucci"),
    ("Nike", "Patagonia"),
    ("Gucci", "Walmart"),
    ("Nike", "Gucci"),
    ("Nike", "Lululemon"),
    ("Nike", "Under Armour"),
    ("Nike", "New Balance"),
    ("Nike", "Reebok"),
]


def tags_probe() -> int:
    """Raw urn:tag response for Patagonia. Run: bun run probe:tags"""
    client = QlooClient(cache_dir=Path(".cache/probe"))
    params = {"filter.type": "urn:tag", "signal.interests.entities": client.search("Patagonia").id, "take": "50"}
    resp = httpx.get(
        client._base + "/v2/insights", params=params, headers={"X-Api-Key": os.environ["QLOO_API_KEY"]}, timeout=30
    )
    print(resp.status_code)
    print(json.dumps(resp.json(), indent=1)[:3000])
    for preset in PRESETS:
        report = run_diligence(client, preset.acquirer, preset.target)
        cold = sum(1 for v in report["domain_overlap"].values() if v == 0)
        trace = next(t for t in report["trace"] if t["agent"] == "Analyst")
        print(preset.id, "cold", cold, trace["decision"], [b["name"] for b in report["bridges"]])
    return 0


def picks_probe() -> int:
    """The Analyst's follow-up on live Qloo: entities of every domain for the top bridge tag of each preset. Run: bun run probe:picks"""
    client = QlooClient(cache_dir=Path(".cache/probe"))
    for preset in PRESETS:
        a, b = client.search(preset.acquirer), client.search(preset.target)
        found = bridges(client.tags(a.id), client.tags(b.id))
        print(preset.id, "bridges", [x.id for x in found])
        if not found:
            continue
        for domain in DOMAINS:
            try:
                picks = client.tag_insights(found[0].id, domain)
            except QlooError as exc:
                print("  ", found[0].id, domain, "failed", repr(exc))
                continue
            print("  ", found[0].id, domain, [(p.name, p.affinity) for p in picks])
    return 0


def main() -> int:
    if sys.argv[1:] == ["tags"]:
        return tags_probe()
    if sys.argv[1:] == ["picks"]:
        return picks_probe()
    take = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    client = QlooClient(cache_dir=Path(".cache/probe"))
    try:
        print("nonsense:", client.search("zzqxv notabrand"))
    except Exception as exc:  # noqa: BLE001
        print("nonsense raised:", repr(exc))
    nike = client.search("Nike")
    for t in (60, 75, 99):
        try:
            print("take", t, [len(client.insights(nike.id, d, t)) for d in DOMAINS])
        except Exception as exc:  # noqa: BLE001
            print("take", t, "failed", repr(exc))
    profiles: dict[str, BrandProfile] = {}
    names = sorted({n for pair in PAIRS for n in pair})

    def build(name: str) -> BrandProfile | None:
        try:
            e = client.search(name)
            return BrandProfile(
                e.name,
                {d: client.insights(e.id, d, take) for d in DOMAINS},
                client.demographics(e.id),
            )
        except Exception as exc:  # noqa: BLE001
            print("skip", name, repr(exc))
            return None

    with ThreadPoolExecutor(2) as pool:
        for name, p in zip(names, pool.map(build, names), strict=True):
            if p:
                profiles[name] = p
    for a, b in PAIRS:
        if a in profiles and b in profiles:
            s = score(profiles[a], profiles[b])
            print(a, b, "bci", s.bci, "clash", s.culture_clash, "dist", s.demographic_distance)
            print("   ", s.domain_overlap, [t.name for t in s.top_shared])
    for preset in PRESETS:
        memo = run_diligence(client, preset.acquirer, preset.target)["memo"]
        print(preset.id, json.dumps(memo, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
