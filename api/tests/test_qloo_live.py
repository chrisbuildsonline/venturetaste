"""Hits the real Qloo API. Run with: bun run test:live"""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import RECORDED_KEY_REJECTED, app, get_qloo
from api.presets import PRESETS, SCREENS, Preset
from api.qloo import DOMAINS, QlooClient, normalize_base_url

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
    assert sum(t["qloo_calls"] for t in report["trace"]) == (20 if report["probed_tags"] else 18)
    assert set(report["domain_overlap"]) == set(DOMAINS)
    assert "recorded" not in report  # a live run with a valid key never replays recorded answers


def analyst_trace(report: dict[str, Any]) -> dict[str, Any]:
    return next(t for t in report["trace"] if t["agent"] == "Analyst")


def test_live_cold_pair_takes_the_tag_probe(api: TestClient) -> None:
    res = api.post("/api/diligence", json={"acquirer": "Patagonia", "target": "Gucci"})
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["probed_tags"] is True
    assert isinstance(report["bridges"], list) and len(report["bridges"]) <= 5
    trace = analyst_trace(report)
    assert trace["qloo_calls"] == 2
    assert "probed Qloo tags" in trace["decision"]


def test_live_warm_pair_skips_the_tag_probe(api: TestClient) -> None:
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["probed_tags"] is False and report["bridges"] == []
    trace = analyst_trace(report)
    assert trace["qloo_calls"] == 0
    assert "no tag probe needed" in trace["decision"]


def test_live_placeholder_key_is_rejected_and_replays_recorded(tmp_path: Path) -> None:
    """The jury sandbox sends a placeholder key to the real Qloo API: it must answer 401/403 so the fallback fires."""
    base = normalize_base_url(os.environ.get("QLOO_API_URL"))
    app.dependency_overrides[get_qloo] = lambda: QlooClient(api_key="set by orchestrator", base_url=base, cache_dir=tmp_path)
    try:
        res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    assert res.json()["recorded"]["reason"] == RECORDED_KEY_REJECTED


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


@pytest.mark.parametrize("target", [t for s in SCREENS for t in s.targets])
def test_live_screen_target_scores_and_verdict(api: TestClient, target: str) -> None:
    res = api.post("/api/diligence", json={"acquirer": SCREENS[0].acquirer, "target": target})
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["brands"]["target"]["name"].casefold() == target.casefold()
    assert 0 <= report["scores"]["bci"] <= 100 and 0 <= report["scores"]["culture_clash"] <= 100
    assert report["memo"]["verdict"] in {"Proceed", "Proceed with conditions", "Pass"}


def test_live_discover_nike_finds_other_brands(api: TestClient) -> None:
    res = api.post("/api/discover", json={"acquirer": "Nike"})
    assert res.status_code == 200, res.text
    body = res.json()
    names = [c["name"] for c in body["candidates"]]
    assert len(names) == 5
    assert not any("nike" in n.casefold() or "jordan" in n.casefold() or "converse" in n.casefold() for n in names)
    assert all(c["reason"].strip() and "·" in c["reason"] for c in body["candidates"])
    assert "recorded" not in body


def test_live_second_call_is_cache_hit(qloo: QlooClient, requests_made: list[httpx.Request]) -> None:
    qloo.search("Patagonia")
    assert len(requests_made) == 1
    qloo.search("Patagonia")
    assert len(requests_made) == 1
