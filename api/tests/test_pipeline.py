from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_qloo
from api.presets import PRESETS
from api.qloo import DOMAINS, MissingKeyError, QlooClient
from api.fixtures import fixture_handler, load, make_client

AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"]


@pytest.fixture
def calls() -> list[httpx.Request]:
    return []


@pytest.fixture
def api(tmp_path: Path, calls: list[httpx.Request]) -> Iterator[TestClient]:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler(calls))
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_handler(tmp_path: Path, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, handler)


def diligence(api: TestClient, acquirer: str, target: str) -> Any:
    res = api.post("/api/diligence", json={"acquirer": acquirer, "target": target})
    assert res.status_code == 200, res.text
    return res.json()


def entity_names(slug: str) -> set[str]:
    return {
        e["name"]
        for d in DOMAINS
        for e in load(f"insights_{slug}_{d}")["results"]["entities"]
    }


# ---- full report ----


def test_full_report(api: TestClient, calls: list[httpx.Request]) -> None:
    report = diligence(api, "Nike", "Adidas")
    assert report["brands"]["acquirer"]["name"] == "Nike"
    assert report["brands"]["target"]["name"] == "Adidas"
    assert report["brands"]["acquirer"]["id"] != report["brands"]["target"]["id"]
    assert set(report["domain_overlap"]) == set(DOMAINS)
    assert all(0 <= v <= 1 for v in report["domain_overlap"].values())
    assert 0 <= report["scores"]["bci"] <= 100
    assert report["scores"]["churn_risk"] in ("low", "medium", "high")
    assert report["top_shared"]
    assert report["top_clashing"]["acquirer"] and report["top_clashing"]["target"]
    for side in ("acquirer", "target"):
        assert report["demographics"][side]["age"] and report["demographics"][side]["gender"]
    assert report["memo"]["verdict"] and report["memo"]["rationale"] and report["memo"]["risks"]
    assert len(calls) == 18  # 2 searches, 14 insights, 2 demographics


def test_trace_has_four_agents_in_order(api: TestClient) -> None:
    trace = diligence(api, "Nike", "Adidas")["trace"]
    assert [t["agent"] for t in trace] == AGENTS
    assert all(t["status"] == "ok" and t["ms"] >= 0 for t in trace)
    assert [t["qloo_calls"] for t in trace] == [2, 16, 0, 0]


def test_missing_domain_counts_as_zero(api: TestClient, tmp_path: Path) -> None:
    ok = fixture_handler([])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("filter.type") == "urn:entity:book":
            return httpx.Response(200, json={"results": {"entities": []}})
        return ok(request)

    use_handler(tmp_path, handler)
    report = diligence(api, "Nike", "Adidas")
    assert set(report["domain_overlap"]) == set(DOMAINS)
    assert report["domain_overlap"]["book"] == 0


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_every_preset_runs(api: TestClient, preset: Any) -> None:
    report = diligence(api, preset.acquirer, preset.target)
    assert set(report["domain_overlap"]) == set(DOMAINS)


# ---- presets ----


def test_presets_endpoint(api: TestClient) -> None:
    presets = api.get("/api/presets").json()
    assert [p["id"] for p in presets] == [p.id for p in PRESETS]
    assert {"synergy", "clash"} <= {p["kind"] for p in presets}
    assert all(p["acquirer"] and p["target"] and p["label"] for p in presets)


# ---- errors ----


def test_unknown_brand_is_422_naming_the_brand(api: TestClient) -> None:
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "zzqxv notabrand"})
    assert res.status_code == 422
    assert "zzqxv notabrand" in res.json()["detail"]


def test_brand_without_taste_data_is_422_before_scoring(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = fixture_handler([])
    adidas = load("search_adidas")["results"][0]["entity_id"]

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("signal.interests.entities") == adidas and params["filter.type"] != "urn:demographics":
            return httpx.Response(200, json={"results": {"entities": []}})
        return ok(request)

    def boom(*args: object) -> None:
        raise AssertionError("scoring must not run")

    monkeypatch.setattr("api.pipeline.score", boom)
    use_handler(tmp_path, handler)
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 422
    assert "Adidas" in res.json()["detail"]


def test_missing_key_is_422_naming_the_recorded_brands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 422  # a preset pair replays recorded answers instead, see test_recorded.py
    assert "QLOO_API_KEY" in res.json()["detail"] and "Adidas" in res.json()["detail"]


def test_missing_key_from_dependency_is_503() -> None:
    def no_key() -> QlooClient:
        raise MissingKeyError("QLOO_API_KEY is not set")

    app.dependency_overrides[get_qloo] = no_key
    try:
        res = TestClient(app).post("/api/diligence", json={"acquirer": "A", "target": "B"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 503


def test_qloo_failure_is_502(api: TestClient, tmp_path: Path) -> None:
    use_handler(tmp_path, lambda r: httpx.Response(500, text="boom"))
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 502
    assert "Qloo" in res.json()["detail"]


def test_malformed_qloo_response_is_502(api: TestClient, tmp_path: Path) -> None:
    use_handler(tmp_path, lambda r: httpx.Response(200, json={"oops": 1}))
    assert api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"}).status_code == 502


def test_aliases_of_one_entity_are_422_before_cartographer(
    api: TestClient, calls: list[httpx.Request], tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # every name resolves to Nike
        calls.append(request)
        return httpx.Response(200, json=load("search_nike"))

    use_handler(tmp_path, handler)
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "Nike Inc"})
    assert res.status_code == 422
    assert "two different brands" in res.json()["detail"]
    assert len(calls) == 2  # only Scout's searches


@pytest.mark.parametrize("body", [{}, {"acquirer": "Nike"}, {"acquirer": "  ", "target": "Adidas"}])
def test_bad_request_body_is_422(api: TestClient, body: dict[str, str]) -> None:
    assert api.post("/api/diligence", json=body).status_code == 422


def test_memo_does_not_list_the_brands_or_repeats_as_clashing_tastes(api: TestClient) -> None:
    memo = diligence(api, "Nike", "Adidas")["memo"]
    for line in (r for r in memo["risks"] if "favours" in r):
        assert "Nike (Brand)" not in line and "Adidas (Brand)" not in line
        listed = line.split("favours ")[1].split(", which")[0].split("), ")
        assert len(listed) == len(set(listed)), line


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_memo_uses_human_domain_labels(api: TestClient, preset: Any) -> None:
    memo = diligence(api, preset.acquirer, preset.target)["memo"]
    text = [memo["headline"], *memo["rationale"], *memo["risks"]]
    for line in text:
        assert "_" not in line, line
        assert not any(f"({d})" in line for d in DOMAINS), line


# ---- acceptance: the demo contrast ----


def test_given_synergy_preset_when_diligence_runs_then_it_beats_the_clash_preset(api: TestClient) -> None:
    # Given the high-synergy and the clash presets
    synergy = next(p for p in PRESETS if p.kind == "synergy")
    clash = next(p for p in PRESETS if p.kind == "clash")
    # When diligence runs on both
    good = diligence(api, synergy.acquirer, synergy.target)
    bad = diligence(api, clash.acquirer, clash.target)
    # Then the synergy deal scores higher and reads better
    assert good["scores"]["bci"] > bad["scores"]["bci"] + 15
    assert good["scores"]["culture_clash"] < bad["scores"]["culture_clash"]
    assert good["memo"]["verdict"] != bad["memo"]["verdict"]
    # And the memo names real entities from the shared Qloo data
    real = entity_names("nike") & entity_names("adidas")
    shared = {t["name"] for t in good["top_shared"]}
    assert shared and shared <= real
    memo_text = " ".join(good["memo"]["rationale"])
    assert any(name in memo_text for name in shared)
    # And the clash memo names what the audiences disagree on
    clashing = {t["name"] for t in bad["top_clashing"]["acquirer"]}
    assert clashing <= entity_names("patagonia")
    assert any(name in " ".join(bad["memo"]["risks"]) for name in clashing)
