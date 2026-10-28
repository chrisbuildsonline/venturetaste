from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api import main
from api.discover import MAX_CANDIDATES, discover, pick_candidates
from api.fixtures import BASE, fixture_handler, make_client
from api.main import RECORDED_FIXTURE_MODE, RECORDED_NO_KEY_BRANDS, app, get_qloo
from api.presets import DISCOVERED
from api.qloo import Affinity, Entity, QlooClient, TagRef, parse_insights, parse_search

NIKE = Entity("nike-id", "Nike", 0.9)
INDUSTRY = "urn:tag:industry:qloo"
GENRE = "urn:tag:genre:brand"
SUBSIDIARY = "urn:tag:subsidiary:qloo"


def tag(kind: str, name: str) -> TagRef:
    return (kind, f"{kind}:{name.lower()}", name)


def acquirer_with(name: str, *tags: TagRef) -> Entity:
    return Entity(f"{name}-id", name, 0.9, tags)


def aff(
    name: str,
    affinity: float = 0.5,
    id: str | None = None,
    types: tuple[str, ...] = ("Product Brand",),
    tags: tuple[TagRef, ...] = (),
) -> Affinity:
    return Affinity(id or f"id-{name}", name, affinity, None, types, tags)


def names_of(candidates: list[dict[str, Any]]) -> list[str]:
    return [c["name"] for c in candidates]


@pytest.mark.parametrize("kind", ["Product Brand", "Corporate Brand", "Retail Brand", "Service Brand"])
def test_pick_keeps_consumer_brand_types(kind: str) -> None:
    assert [c["name"] for c in pick_candidates(NIKE, [aff("Adidas", types=(kind,))])] == ["Adidas"]


@pytest.mark.parametrize("types", [("Entertainment Brand",), ("Media Brand",), ("Nonprofit Brand",), ()])
def test_pick_drops_clubs_media_nonprofits_and_untyped(types: tuple[str, ...]) -> None:
    assert names_of(pick_candidates(NIKE, [aff("Real Madrid CF", types=types), aff("Puma")])) == ["Puma"]


def test_pick_filters_before_the_cap() -> None:
    clubs = [aff(f"Club {i}", types=("Entertainment Brand",)) for i in range(8)]
    real = [aff(f"Brand {i}") for i in range(7)]
    assert [c["name"] for c in pick_candidates(NIKE, clubs + real)] == [f"Brand {i}" for i in range(5)]


def test_parse_insights_reads_the_brand_type_tags() -> None:
    entity = {
        "entity_id": "e1",
        "name": "Adidas",
        "query": {"affinity": 0.4},
        "tags": [
            {"id": "t1", "name": "Corporate Brand", "type": "urn:tag:brand_type:qloo"},
            {"id": "t2", "name": "Footwear", "type": "urn:tag:industry:qloo"},
        ],
    }
    bare = {"entity_id": "e2", "name": "Puma", "query": {"affinity": 0.3}}
    got = parse_insights({"results": {"entities": [entity, bare]}})
    assert [a.brand_types for a in got] == [("Corporate Brand",), ()]


def test_pick_drops_the_acquirer_by_id_and_by_slug() -> None:
    got = pick_candidates(NIKE, [aff("Nike", id="nike-id"), aff("Nike!"),aff("Adidas"), aff("NIKE", id="other")])
    assert [c["name"] for c in got] == ["Adidas"]


def test_pick_drops_sub_brands() -> None:
    got = pick_candidates(NIKE, [aff("Nike SB"), aff("Nike Training Club"), aff("Puma")])
    assert [c["name"] for c in got] == ["Puma"]


def test_pick_dedupes_by_slug_and_keeps_the_first() -> None:
    got = pick_candidates(NIKE, [aff("Adidas", 0.9), aff("ADIDAS", 0.8, id="x"), aff("Puma", 0.7)])
    assert [(c["name"], c["affinity"]) for c in got] == [("Adidas", 0.9), ("Puma", 0.7)]


def test_pick_caps_at_five_and_keeps_affinity_order_without_tag_signal() -> None:
    names = [f"Brand {i}" for i in range(9)]
    got = pick_candidates(NIKE, [aff(n, 1 - i / 10) for i, n in enumerate(names)])
    assert MAX_CANDIDATES == 5
    assert names_of(got) == names[:5]


JORDAN = acquirer_with("Nike", tag(SUBSIDIARY, "Jordan Brand"), tag(SUBSIDIARY, "Converse"))


def test_pick_drops_the_acquirers_own_lines_even_when_named_differently() -> None:
    got = pick_candidates(JORDAN, [aff("Air Jordan Product Line", 0.9), aff("Converse, Inc.", 0.8), aff("Adidas", 0.7)])
    assert names_of(got) == ["Adidas"]


def test_pick_drops_the_parent_when_its_subsidiaries_name_the_acquirer() -> None:
    converse = acquirer_with("Converse")
    parent = aff("Nike", 0.9, tags=(tag(SUBSIDIARY, "Jordan Brand"), tag(SUBSIDIARY, "Converse")))
    assert names_of(pick_candidates(converse, [parent, aff("Vans", 0.5)])) == ["Vans"]


def test_pick_drops_by_name_containment_in_both_directions() -> None:
    cola = acquirer_with("The Coca-Cola Company")
    assert names_of(pick_candidates(cola, [aff("Coca-Cola Zero"), aff("Coca-Cola"), aff("Pepsi")])) == ["Pepsi"]


def test_pick_has_no_false_positives_on_generic_words_or_unrelated_names() -> None:
    owner = acquirer_with("Nike", tag(SUBSIDIARY, "Jordan Brand"), tag(SUBSIDIARY, "The Group"))
    got = pick_candidates(owner, [aff("Brand Group Co", 0.9), aff("Adidas", 0.8), aff("Puma", 0.7), aff("Under Armour", 0.6)])
    assert names_of(got) == ["Brand Group Co", "Adidas", "Puma", "Under Armour"]


def test_pick_ranks_a_same_category_brand_above_a_more_affine_off_category_one() -> None:
    cafe = acquirer_with("Starbucks", tag(INDUSTRY, "Coffee"), tag(GENRE, "Cafe"))
    off = aff("Forever 21", 0.9, tags=(tag(INDUSTRY, "Fashion"),))
    same = aff("Dunkin'", 0.5, tags=(tag(INDUSTRY, "Coffee"), tag(GENRE, "Cafe")))
    assert names_of(pick_candidates(cafe, [off, same])) == ["Dunkin'", "Forever 21"]


def test_pick_ranks_over_the_whole_list_not_just_the_first_five() -> None:
    cafe = acquirer_with("Starbucks", tag(INDUSTRY, "Coffee"))
    far = [aff(f"Off {i}", 0.9 - i / 100, tags=(tag(INDUSTRY, "Fashion"),)) for i in range(8)]
    best = aff("Peet's", 0.3, tags=(tag(INDUSTRY, "Coffee"),))
    assert names_of(pick_candidates(cafe, [*far, best]))[0] == "Peet's"


def test_candidates_carry_score_adjacency_and_a_reason() -> None:
    cafe = acquirer_with("Starbucks", tag(INDUSTRY, "Coffee"), tag(GENRE, "Cafe"))
    got = pick_candidates(cafe, [aff("Dunkin'", 0.5, tags=(tag(INDUSTRY, "Coffee"), tag(GENRE, "Cafe")))])
    assert got == [
        {"name": "Dunkin'", "affinity": 0.5, "adjacency": 1.0, "score": 0.75, "reason": "Shares Coffee, Cafe · affinity 0.50"}
    ]


def test_reason_caps_shared_names_at_three_and_says_so_when_nothing_is_shared() -> None:
    shared = [tag(INDUSTRY, n) for n in ("Footwear", "Running", "Sports & Fitness", "Retail")]
    owner = acquirer_with("Nike", *shared)
    got = pick_candidates(owner, [aff("Brooks", 0.93, tags=tuple(shared)), aff("Zara", 0.4, tags=(tag(INDUSTRY, "Apparel"),))])
    assert [c["reason"] for c in got] == [
        "Shares Footwear, Running, Sports & Fitness · affinity 0.93",
        "No shared categories · affinity 0.40",
    ]


def test_parse_search_reads_tags_with_their_ids() -> None:
    item = {
        "entity_id": "e1",
        "name": "Nike",
        "tags": [{"tag_id": "urn:tag:subsidiary:qloo:converse", "name": "Converse", "type": SUBSIDIARY}, "junk"],
    }
    got = parse_search({"results": [item, {"entity_id": "e2", "name": "Bare"}]})
    assert [e.tags for e in got] == [((SUBSIDIARY, "urn:tag:subsidiary:qloo:converse", "Converse"),), ()]


def test_recorded_nike_drops_its_own_lines_and_keeps_sportswear_peers(tmp_path: Path) -> None:
    got = discover(make_client(tmp_path, fixture_handler([])), "Nike")["candidates"]
    assert not any("jordan" in n.casefold() for n in names_of(got))
    assert "Adidas" in names_of(got)
    assert not any(c["reason"].startswith("No shared") for c in got)


def test_recorded_starbucks_ranks_food_and_beverage_over_fashion(tmp_path: Path) -> None:
    got = discover(make_client(tmp_path, fixture_handler([])), "Starbucks")["candidates"]
    assert len(got) == MAX_CANDIDATES
    assert not set(names_of(got)) & {"Forever 21", "Victoria's Secret"}
    assert not any(c["reason"].startswith("No shared") for c in got)


def test_recorded_patagonia_keeps_outdoor_peers(tmp_path: Path) -> None:
    got = discover(make_client(tmp_path, fixture_handler([])), "Patagonia")["candidates"]
    assert "The North Face" in names_of(got)
    assert not any(c["reason"].startswith("No shared") for c in got)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    monkeypatch.setenv("VENTURETASTE_RATE_LIMIT", "30")
    main.reset_rate_limit()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    return TestClient(app)


def status_client(tmp_path: Path, status: int) -> QlooClient:
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json={})))
    return QlooClient(api_key="rejected-key", base_url=BASE, cache_dir=tmp_path, http=http)


def test_happy_path_returns_nike_candidates_without_nike(api: TestClient) -> None:
    res = api.post("/api/discover", json={"acquirer": "nike"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["acquirer"] == "Nike"
    assert body["source"] == "Qloo consumer-brand affinities (urn:entity:brand)"
    names = [c["name"] for c in body["candidates"]]
    assert names == list(DISCOVERED["Nike"])
    assert 2 <= len(names) <= 5 and "Nike" not in names
    assert all(isinstance(c["affinity"], float) for c in body["candidates"])
    assert "recorded" not in body


def test_unknown_brand_is_a_friendly_422(api: TestClient) -> None:
    res = api.post("/api/discover", json={"acquirer": "Zzqx Nonbrand"})
    assert res.status_code == 422
    assert "Zzqx Nonbrand" in res.json()["detail"]


def test_blank_acquirer_is_rejected(api: TestClient) -> None:
    assert api.post("/api/discover", json={"acquirer": "  "}).status_code == 422


def test_no_key_with_a_preset_replays_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/discover", json={"acquirer": "Nike"})
    assert res.status_code == 200, res.text
    assert res.json()["recorded"] == {"reason": RECORDED_NO_KEY_BRANDS}
    assert [c["name"] for c in res.json()["candidates"]] == list(DISCOVERED["Nike"])


def test_no_key_with_a_non_preset_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    assert TestClient(app).post("/api/discover", json={"acquirer": "Zara"}).status_code == 422


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_falls_back_for_a_preset(tmp_path: Path, status: int) -> None:
    app.dependency_overrides[get_qloo] = lambda: status_client(tmp_path, status)
    res = TestClient(app).post("/api/discover", json={"acquirer": "Nike"})
    assert res.status_code == 200, res.text
    assert "rejected" in res.json()["recorded"]["reason"]


def test_rejected_key_for_a_non_preset_is_a_422_listing_recorded_brands(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: status_client(tmp_path, 401)
    res = TestClient(app).post("/api/discover", json={"acquirer": "Zara"})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("Qloo rejected this server's API key, so only recorded brands work: ")


def test_other_qloo_failures_do_not_fall_back(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: status_client(tmp_path, 500)
    res = TestClient(app).post("/api/discover", json={"acquirer": "Nike"})
    assert res.status_code == 502 and "recorded" not in res.text


def test_fixture_mode_is_labelled_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    res = TestClient(app).post("/api/discover", json={"acquirer": "Nike"})
    assert res.json()["recorded"] == {"reason": RECORDED_FIXTURE_MODE}


def test_discover_counts_as_one_rate_limit_hit(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_RATE_LIMIT", "2")
    assert api.post("/api/discover", json={"acquirer": "Nike"}).status_code == 200
    assert api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"}).status_code == 200
    res = api.post("/api/discover", json={"acquirer": "Nike"})
    assert res.status_code == 429 and "Retry-After" in res.headers


@pytest.mark.parametrize("acquirer", sorted(DISCOVERED))
def test_every_discovered_candidate_has_recorded_diligence(
    monkeypatch: pytest.MonkeyPatch, acquirer: str
) -> None:
    """The offline demo: Find targets, then screen each candidate, with no key and no network."""
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    api = TestClient(app)
    candidates = api.post("/api/discover", json={"acquirer": acquirer}).json()["candidates"]
    assert len(candidates) >= 2
    for c in candidates:
        res = api.post("/api/diligence", json={"acquirer": acquirer, "target": c["name"]})
        assert res.status_code == 200, (c["name"], res.text)
        assert "recorded" in res.json()


def test_fixture_candidates_match_what_discovery_derives(tmp_path: Path) -> None:
    """DISCOVERED is just a snapshot of the recorded brand affinities, so it cannot drift from the fixtures."""
    client = make_client(tmp_path, fixture_handler([]))
    for acquirer, expected in DISCOVERED.items():
        names = [c["name"] for c in discover(client, acquirer)["candidates"]]
        assert names == list(expected), names
