"""Live probe: nonsense search, max take, candidate pair scores. Run: bun run probe"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api.pipeline import run_diligence
from api.presets import PRESETS
from api.qloo import DOMAINS, QlooClient
from api.scoring import BrandProfile, score

PAIRS = [
    ("Nike", "Adidas"),
    ("Nike", "Puma"),
    ("Coca-Cola", "Pepsi"),
    ("Patagonia", "The North Face"),
    ("Patagonia", "Gucci"),
    ("Nike", "Patagonia"),
    ("Gucci", "Walmart"),
]


def main() -> int:
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
