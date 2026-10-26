"""Record raw Qloo responses to api/fixture_data. Run: bun run record"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

from api.presets import preset_brands, slug
from api.qloo import DEFAULT_TAKE, DOMAINS

FIXTURES = Path(__file__).resolve().parent / "fixture_data"


def get(client: httpx.Client, path: str, params: dict[str, str]) -> object:
    for attempt in range(6):
        resp = client.get(path, params=params)
        print(f"{resp.status_code} {path} {params.get('filter.type', params.get('query', ''))}")
        if resp.status_code != 429:
            break
        time.sleep(2 * (attempt + 1))
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
    (FIXTURES / f"{name}.json").write_text(json.dumps(data, separators=(",", ":"), sort_keys=True))


def main() -> int:
    key = os.environ.get("QLOO_API_KEY")
    if not key:
        print("QLOO_API_KEY not set", file=sys.stderr)
        return 1
    base = os.environ.get("QLOO_API_URL", "https://hackathon.api.qloo.com")
    with httpx.Client(base_url=base, headers={"X-Api-Key": key}, timeout=30) as client:
        for brand in preset_brands():
            name = slug(brand)
            found = get(client, "/search", {"query": brand, "types": "urn:entity:brand"})
            if not isinstance(found, dict) or not found.get("results"):
                print(f"no search result for {brand}", file=sys.stderr)
                return 1
            slim(found["results"])
            save(f"search_{name}", found)
            entity_id = found["results"][0]["entity_id"]
            for domain in DOMAINS:
                params = {
                    "filter.type": f"urn:entity:{domain}",
                    "signal.interests.entities": entity_id,
                    "take": str(DEFAULT_TAKE),
                }
                data = get(client, "/v2/insights", params)
                if isinstance(data, dict):
                    slim(data.get("results", {}).get("entities", []))
                    save(f"insights_{name}_{domain}", data)
            demo = get(
                client,
                "/v2/insights",
                {"filter.type": "urn:demographics", "signal.interests.entities": entity_id},
            )
            if demo is not None:
                save(f"demographics_{name}", demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
