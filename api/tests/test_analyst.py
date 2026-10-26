from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.fixtures import fixture_handler, make_client
from api.main import app, get_qloo
from api.pipeline import COLD_DOMAINS_TO_PROBE, State, build_memo, make_analyst
from api.qloo import DOMAINS, Affinity, Demographics, Entity, Tag
from api.scoring import BrandProfile, score

DEMO = Demographics(age={"25_to_29": 0.2}, gender={"female": 0.1})


class FakeQloo:
    def __init__(self, tags: dict[str, list[Tag]]) -> None:
        self.tags_by_entity = tags
        self.tag_calls: list[str] = []

    def tags(self, entity_id: str) -> list[Tag]:
        self.tag_calls.append(entity_id)
        return self.tags_by_entity[entity_id]


def state_with_cold(cold: int) -> State:
    """Both brands list the same entity in 7 - cold domains and different ones in the first `cold`."""
    a: dict[str, list[Affinity]] = {}
    b: dict[str, list[Affinity]] = {}
    for i, d in enumerate(DOMAINS):
        if i < cold:
            a[d] = [Affinity(f"{d}-a", "A fan", 0.5, None)]
            b[d] = [Affinity(f"{d}-b", "B fan", 0.5, None)]
        else:
            a[d] = b[d] = [Affinity(f"{d}-x", "Both", 0.5, None)]
    return {
        "entities": {"acquirer": Entity("ida", "A", None), "target": Entity("idt", "T", None)},
        "profiles": {"acquirer": BrandProfile("A", a, DEMO), "target": BrandProfile("T", b, DEMO)},
    }


def tag(name: str, affinity: float) -> Tag:
    return Tag(f"urn:tag:{name}", name, affinity)


TAGS_A = [tag(f"t{i}", a) for i, a in enumerate([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3])] + [tag("only-a", 1.0)]
TAGS_T = [tag(f"t{i}", t) for i, t in enumerate([0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])] + [tag("only-t", 1.0)]


def fake() -> FakeQloo:
    return FakeQloo({"ida": TAGS_A, "idt": TAGS_T})


def test_cold_overlap_probes_tags_and_finds_bridges() -> None:
    qloo = fake()
    update, calls = make_analyst(qloo)(state_with_cold(7))
    assert calls == 2
    assert sorted(qloo.tag_calls) == ["ida", "idt"]
    assert update["probed_tags"] is True
    bridges = update["bridges"]
    assert len(bridges) == 5  # 7 shared tags, top 5
    mins = [min(b.affinity_acquirer, b.affinity_target) for b in bridges]
    assert mins == sorted(mins, reverse=True)
    assert {b.name for b in bridges} <= {f"t{i}" for i in range(7)}  # the exclusive tags never bridge
    assert [b.name for b in bridges] == ["t3", "t4", "t2", "t5", "t1"]  # min affinity, ties by name
    assert (bridges[0].affinity_acquirer, bridges[0].affinity_target) == (0.6, 0.5)
    assert update["decision"] == "Overlap 0 in 7/7 domains → probed Qloo tags: 5 bridging tastes"


def test_probe_with_no_shared_tags_says_so() -> None:
    qloo = FakeQloo({"ida": [tag("x", 1.0)], "idt": [tag("y", 1.0)]})
    update, calls = make_analyst(qloo)(state_with_cold(5))
    assert calls == 2
    assert update["bridges"] == [] and update["probed_tags"] is True
    assert update["decision"] == "Overlap 0 in 5/7 domains → probed Qloo tags: no bridging tastes found"


def test_one_bridge_is_singular() -> None:
    qloo = FakeQloo({"ida": [tag("x", 0.4)], "idt": [tag("x", 0.8)]})
    update, _ = make_analyst(qloo)(state_with_cold(4))
    assert update["decision"].endswith("1 bridging taste")


def test_warm_overlap_makes_no_extra_calls() -> None:
    qloo = fake()
    update, calls = make_analyst(qloo)(state_with_cold(2))
    assert calls == 0 and qloo.tag_calls == []
    assert update["bridges"] == [] and update["probed_tags"] is False
    assert update["decision"] == "Overlap in 5/7 domains → no tag probe needed"


def test_threshold_edge_three_cold_skips_four_cold_probes() -> None:
    assert COLD_DOMAINS_TO_PROBE == 4
    for cold, probed in ((3, False), (4, True)):
        qloo = fake()
        _, calls = make_analyst(qloo)(state_with_cold(cold))
        assert (calls, bool(qloo.tag_calls)) == ((2, True) if probed else (0, False))


def test_bridges_never_change_the_scores() -> None:
    state = state_with_cold(7)
    profiles = state["profiles"]
    plain = score(profiles["acquirer"], profiles["target"])
    with_bridges = make_analyst(fake())(state)[0]["scores"]
    without = make_analyst(FakeQloo({"ida": [], "idt": []}))(state)[0]["scores"]
    assert with_bridges == without == plain


def test_memo_names_bridges() -> None:
    state = state_with_cold(7)
    s = score(state["profiles"]["acquirer"], state["profiles"]["target"])
    bridges = make_analyst(fake())(state)[0]["bridges"]
    memo = build_memo("A", "T", s, bridges, True)
    assert "Qloo tags bridge the two audiences: t3, t4, t2." in memo["rationale"]
    assert memo["verdict"] == build_memo("A", "T", s)["verdict"]


def test_memo_is_honest_when_the_probe_found_nothing() -> None:
    state = state_with_cold(7)
    s = score(state["profiles"]["acquirer"], state["profiles"]["target"])
    rationale = build_memo("A", "T", s, [], True)["rationale"]
    assert "Qloo tags found no bridging tastes between the two audiences." in rationale
    assert not any("bridge" in line for line in build_memo("A", "T", s)["rationale"])


# ---- through the API, on the recorded fixtures ----


@pytest.fixture
def api(tmp_path: Path) -> Any:
    calls: list[httpx.Request] = []
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler(calls))
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def analyst_of(report: dict[str, Any]) -> dict[str, Any]:
    return next(t for t in report["trace"] if t["agent"] == "Analyst")


def test_report_for_a_cold_preset_carries_the_probe(api: Any) -> None:
    client, calls = api
    report = client.post("/api/diligence", json={"acquirer": "Patagonia", "target": "Gucci"}).json()
    assert report["probed_tags"] is True
    assert isinstance(report["bridges"], list)
    assert set(report["bridges"][0]) == {"id", "name", "affinity_acquirer", "affinity_target"} if report["bridges"] else True
    assert analyst_of(report)["qloo_calls"] == 2
    assert analyst_of(report)["decision"].startswith("Overlap 0 in 7/7 domains → probed Qloo tags: ")
    assert len(calls) == 20


def test_report_for_a_warm_preset_has_no_probe(api: Any) -> None:
    client, calls = api
    report = client.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"}).json()
    assert report["probed_tags"] is False and report["bridges"] == []
    assert analyst_of(report)["qloo_calls"] == 0
    assert "no tag probe needed" in analyst_of(report)["decision"]
    assert len(calls) == 18
