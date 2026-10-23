"""Record raw Qloo responses to api/tests/fixtures. Run: bun run record"""

import json
import os
import sys
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
BRANDS = ["Nike", "Patagonia"]
DOMAINS = ["brand", "artist", "movie", "tv_show", "place", "destination", "book"]


def get(client: httpx.Client, path: str, params: dict[str, str]) -> object:
    resp = client.get(path, params=params)
    print(f"{resp.status_code} {path} {params.get('filter.type', params.get('query', ''))}")
    if resp.status_code != 200:
        return None
    data: object = resp.json()
    return data


def slim(entities: list[dict[str, object]]) -> None:
    """Drop the bulky blocks (properties, external ids) we never parse."""
    for entity in entities:
        entity.pop("properties", None)
        entity.pop("external", None)


def save(name: str, data: object) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True))


def main() -> int:
    key = os.environ.get("QLOO_API_KEY")
    if not key:
        print("QLOO_API_KEY not set", file=sys.stderr)
        return 1
    base = os.environ.get("QLOO_API_URL", "https://hackathon.api.qloo.com")
    with httpx.Client(base_url=base, headers={"X-Api-Key": key}, timeout=30) as client:
        for brand in BRANDS:
            slug = brand.lower()
            found = get(client, "/search", {"query": brand, "types": "urn:entity:brand"})
            if not isinstance(found, dict) or not found.get("results"):
                continue
            slim(found["results"])
            save(f"search_{slug}", found)
            entity_id = found["results"][0]["entity_id"]
            for domain in DOMAINS:
                params = {
                    "filter.type": f"urn:entity:{domain}",
                    "signal.interests.entities": entity_id,
                    "take": "10",
                }
                data = get(client, "/v2/insights", params)
                if isinstance(data, dict):
                    slim(data.get("results", {}).get("entities", []))
                    save(f"insights_{slug}_{domain}", data)
            demo = get(
                client,
                "/v2/insights",
                {"filter.type": "urn:demographics", "signal.interests.entities": entity_id},
            )
            if demo is not None:
                save(f"demographics_{slug}", demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
