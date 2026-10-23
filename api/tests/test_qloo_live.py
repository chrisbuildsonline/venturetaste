"""Hits the real Qloo API. Run with: bun run test:live"""

import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_qloo
from api.presets import PRESETS, Preset
from api.qloo import DOMAINS, QlooClient

pytestmark = pytest.mark.live


@pytest.fixture
def requests_made() -> list[httpx.Request]:
    return []


@pytest.fixture
def qloo(tmp_path: Path, requests_made: list[httpx.Request]) -> QlooClient:
    http = httpx.Client(timeout=30, event_hooks={"request": [requests_made.append]})
    return QlooClient(cache_dir=tmp_path, http=http)


@pytest.mark.parametrize("brand", ["Nike", "Patagonia"])
def test_live_search(qloo: QlooClient, brand: str) -> None:
    entity = qloo.search(brand)
    assert entity.name == brand
    assert entity.id


def test_live_insights_cover_most_domains(qloo: QlooClient) -> None:
    nike = qloo.search("Nike")
    working = [d for d in DOMAINS if len(qloo.insights(nike.id, d)) >= 5]
    assert len(working) >= 4, working
    for domain in working:
        assert all(isinstance(a.affinity, float) for a in qloo.insights(nike.id, domain))


def test_live_demographics(qloo: QlooClient) -> None:
    demo = qloo.demographics(qloo.search("Nike").id)
    assert demo.age and demo.gender


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_qloo] = lambda: QlooClient(cache_dir=tmp_path)  # cold cache
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_live_preset_runs_cold_under_20s(api: TestClient, preset: Preset) -> None:
    start = time.perf_counter()
    res = api.post("/api/diligence", json={"acquirer": preset.acquirer, "target": preset.target})
    elapsed = time.perf_counter() - start
    assert res.status_code == 200, res.text
    report = res.json()
    assert elapsed < 20, f"{elapsed:.1f}s"
    assert sum(t["qloo_calls"] for t in report["trace"]) == 18
    assert set(report["domain_overlap"]) == set(DOMAINS)


def test_live_nonsense_brand_is_422(api: TestClient) -> None:
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "zzqxv notabrand"})
    assert res.status_code == 422
    assert "zzqxv notabrand" in res.json()["detail"]


def test_live_synergy_preset_beats_clash_preset(api: TestClient) -> None:
    def bci(preset: Preset) -> float:
        res = api.post("/api/diligence", json={"acquirer": preset.acquirer, "target": preset.target})
        assert res.status_code == 200, res.text
        return float(res.json()["scores"]["bci"])

    assert bci(next(p for p in PRESETS if p.kind == "synergy")) > bci(
        next(p for p in PRESETS if p.kind == "clash")
    )


def test_live_second_call_is_cache_hit(qloo: QlooClient, requests_made: list[httpx.Request]) -> None:
    qloo.search("Patagonia")
    assert len(requests_made) == 1
    qloo.search("Patagonia")
    assert len(requests_made) == 1
