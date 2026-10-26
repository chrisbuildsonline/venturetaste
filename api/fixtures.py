"""Fixture-backed fake of the Qloo HTTP API: recorded answers for fixture mode and the tests."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from api.presets import preset_brands, slug
from api.qloo import QlooClient

FIXTURES = Path(__file__).parent / "fixture_data"
BASE = "https://qloo.test"


def load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


BRAND_IDS = {
    load(f"search_{slug(brand)}")["results"][0]["entity_id"]: slug(brand) for brand in preset_brands()
}


def fixture_handler(calls: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        params = request.url.params
        if request.url.path == "/search":
            name = slug(params["query"])
            if (FIXTURES / f"search_{name}.json").exists():
                return httpx.Response(200, json=load(f"search_{name}"))
            return httpx.Response(200, json={"results": []})
        name = BRAND_IDS[params["signal.interests.entities"]]
        kind = params["filter.type"]
        if kind == "urn:demographics":
            return httpx.Response(200, json=load(f"demographics_{name}"))
        if kind == "urn:tag":
            return httpx.Response(200, json=load(f"tags_{name}"))
        return httpx.Response(200, json=load(f"insights_{name}_{kind.split(':')[-1]}"))

    return handler


def make_client(tmp_path: Path, handler: Callable[[httpx.Request], httpx.Response]) -> QlooClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return QlooClient(api_key="test-key", base_url=BASE, cache_dir=tmp_path, http=http)
