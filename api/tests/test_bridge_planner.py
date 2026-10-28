"""The Analyst's widened plan: which tag families to probe, an optional follow-up query, and the bridge potential score."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from api.fixtures import BRAND_IDS, fixture_handler, make_client
from api.pipeline import ALLOWED_FAMILIES, PLAN_SYSTEM, Plan, Rejected, _check_plan, build_memo, make_analyst
from api.qloo import DOMAINS, Affinity, QlooAPIError, Tag
from api.scoring import Bridge, BridgePick, bridge_potential, bridges, score, tag_family
from api.tests.test_analyst import FakeQloo, state_with_cold, tag

REASON = "audiences are far apart"


def plan(**over: Any) -> dict[str, Any]:
    return {"probe_tags": True, "tag_families": ["genre", "lifestyle"], "follow_up_domain": "movie", "reason": REASON, **over}


# ---- _check_plan ----


def test_a_good_plan_is_accepted() -> None:
    assert _check_plan(plan(), 0, 7) == Plan(True, ("genre", "lifestyle"), "movie", REASON)
    assert _check_plan(plan(follow_up_domain=None), 0, 7).follow_up is None
    assert _check_plan(plan(follow_up_domain=None), 0, 7) == _check_plan({k: v for k, v in plan().items() if k != "follow_up_domain"}, 0, 7)


def test_a_plan_that_does_not_probe_carries_no_families_or_follow_up() -> None:
    assert _check_plan(plan(probe_tags=False, tag_families=[], follow_up_domain=None), 6, 7) == Plan(False, (), None, REASON)
    assert _check_plan({"probe_tags": False, "reason": REASON}, 6, 7) == Plan(False, (), None, REASON)
    assert _check_plan(plan(probe_tags=False), 6, 7) == Plan(False, (), None, REASON)  # families and follow-up are ignored without a probe


@pytest.mark.parametrize(
    "bad",
    [
        {"tag_families": []},
        {"tag_families": ["genre", "nonsense"]},
        {"tag_families": "genre"},
        {"tag_families": [3]},
        {"tag_families": ["cost_description"]},  # trivial family
        {"follow_up_domain": "gadgets"},
        {"follow_up_domain": 7},
        {"follow_up_domain": ""},
    ],
)
def test_bad_families_or_follow_up_domain_are_rejected_when_probing(bad: dict[str, Any]) -> None:
    with pytest.raises(Rejected):
        _check_plan(plan(**bad), 0, 7)


def test_the_overlap_consistency_checks_still_apply() -> None:
    with pytest.raises(Rejected):
        _check_plan(plan(reason="Low overlap in most domains."), 6, 7)


def test_allowed_families_exclude_the_trivial_ones_and_the_prompt_lists_them() -> None:
    from api.scoring import TRIVIAL_TAGS

    assert ALLOWED_FAMILIES and not any(f"urn:tag:{f}:" in TRIVIAL_TAGS for f in ALLOWED_FAMILIES)
    assert all(f in PLAN_SYSTEM for f in ALLOWED_FAMILIES) and all(d in PLAN_SYSTEM for d in DOMAINS)
    assert "tag_families" in PLAN_SYSTEM and "follow_up_domain" in PLAN_SYSTEM


# ---- families and bridges ----


def t(tag_id: str, a: float) -> Tag:
    return Tag(tag_id, tag_id.rsplit(":", 1)[-1], a)


def test_tag_family_is_the_third_urn_segment() -> None:
    assert tag_family("urn:tag:genre:music:rock") == "genre"
    assert tag_family("urn:tag:lifestyle:qloo:minimalist") == "lifestyle"


def test_bridges_can_be_limited_to_families_before_the_top_cut() -> None:
    a = [t(f"urn:tag:genre:music:g{i}", 0.9 - i / 100) for i in range(6)] + [t("urn:tag:lifestyle:qloo:l", 0.2)]
    assert [b.name for b in bridges(a, a)][:1] == ["g0"] and "l" not in [b.name for b in bridges(a, a)]  # top 5 are all genre
    assert [b.name for b in bridges(a, a, {"lifestyle"})] == ["l"]
    assert len(bridges(a, a, {"genre", "lifestyle"})) == 5
    assert bridges(a, a, {"keyword"}) == []


# ---- bridge potential ----


def bridge(n: int, a: float, b: float) -> Bridge:
    return Bridge(f"urn:tag:genre:x:{n}", f"b{n}", a, b)


def test_bridge_potential_is_zero_without_bridges() -> None:
    assert bridge_potential([]) == 0


def test_bridge_potential_grows_with_count_and_affinity_and_is_capped() -> None:
    one_weak = bridge_potential([bridge(0, 0.2, 0.9)])  # min affinity 0.2
    one_strong = bridge_potential([bridge(0, 0.8, 0.9)])
    three_strong = bridge_potential([bridge(i, 0.8, 0.9) for i in range(3)])
    five_perfect = bridge_potential([bridge(i, 1.0, 1.0) for i in range(5)])
    assert 0 < one_weak < one_strong < three_strong < five_perfect == 100
    assert one_strong == pytest.approx(16.0)  # 0.8 of one bridge out of the 5 that count
    assert bridge_potential([bridge(i, 3.0, 5.0) for i in range(9)]) == 100  # affinity and count are clamped
    assert bridge_potential([bridge(0, -0.5, 0.7)]) == 0  # negative affinity is no bridge


# ---- the Analyst ----


class Picker(FakeQloo):
    def __init__(self, tags: dict[str, list[Tag]], picks: list[Affinity]) -> None:
        super().__init__(tags)
        self.picks = picks
        self.pick_calls: list[tuple[str, str]] = []

    def tag_insights(self, tag_id: str, domain: str) -> list[Affinity]:
        self.pick_calls.append((tag_id, domain))
        return self.picks


def llm_plan(**over: Any):  # type: ignore[no-untyped-def]
    return lambda system, user: ("fake-model", plan(**over))


TAGS_A = [t("urn:tag:genre:music:rock", 0.9), t("urn:tag:lifestyle:qloo:outdoors", 0.5), t("urn:tag:genre:music:pop", 0.3)]
TAGS_T = [t("urn:tag:genre:music:rock", 0.7), t("urn:tag:lifestyle:qloo:outdoors", 0.8), t("urn:tag:genre:music:pop", 0.6)]
PICKS = [Affinity(f"m{i}", n, 0.5, None) for i, n in enumerate(["Movie A", "Movie B", "A", "T"])]  # "A" and "T" are the two brands


def picker() -> Picker:
    return Picker({"ida": TAGS_A, "idt": TAGS_T}, PICKS)


def test_the_family_filter_keeps_only_chosen_families() -> None:
    update, calls = make_analyst(picker(), llm_plan(tag_families=["lifestyle"], follow_up_domain=None))(state_with_cold(7))
    assert [b.id for b in update["bridges"]] == ["urn:tag:lifestyle:qloo:outdoors"]
    assert calls == 2 and update["bridge_picks"] == []
    assert update["bridge_potential"] == bridge_potential(update["bridges"])


def test_the_rule_fallback_keeps_every_nontrivial_family_and_never_follows_up() -> None:
    qloo = picker()
    update, calls = make_analyst(qloo, None)(state_with_cold(7))
    assert len(update["bridges"]) == 3 and calls == 2 and qloo.pick_calls == []
    assert update["bridge_picks"] == [] and update["bridge_potential"] > 0


def test_a_follow_up_is_one_extra_call_signalled_by_the_top_bridge() -> None:
    qloo = picker()
    update, calls = make_analyst(qloo, llm_plan())(state_with_cold(7))
    assert calls == 3 and qloo.pick_calls == [("urn:tag:genre:music:rock", "movie")]  # rock: min affinity 0.7, the strongest
    assert [(p.name, p.domain, p.tag_id, p.tag_name) for p in update["bridge_picks"]] == [
        ("Movie A", "movie", "urn:tag:genre:music:rock", "rock"),
        ("Movie B", "movie", "urn:tag:genre:music:rock", "rock"),
    ]  # the two brands themselves are not picks
    assert update["decision"] == (
        f"Overlap 0 in 7/7 domains → probed Qloo tags (genre, lifestyle): 3 bridging tastes → follow-up in movies: Movie A, Movie B (fake-model: {REASON})"
    )


def test_no_follow_up_without_a_follow_up_domain() -> None:
    qloo = picker()
    update, calls = make_analyst(qloo, llm_plan(follow_up_domain=None))(state_with_cold(7))
    assert calls == 2 and qloo.pick_calls == [] and update["bridge_picks"] == []
    assert "follow-up" not in update["decision"] and "(genre, lifestyle)" in update["decision"]


def test_no_follow_up_without_a_kept_bridge() -> None:
    qloo = Picker({"ida": [t("urn:tag:genre:music:rock", 0.9)], "idt": [t("urn:tag:genre:music:jazz", 0.9)]}, PICKS)
    update, calls = make_analyst(qloo, llm_plan())(state_with_cold(7))
    assert calls == 2 and qloo.pick_calls == [] and update["bridges"] == [] and update["bridge_potential"] == 0
    assert update["decision"].endswith(f"no bridging tastes found (fake-model: {REASON})")


def test_no_follow_up_when_the_family_filter_leaves_nothing() -> None:
    qloo = picker()
    update, calls = make_analyst(qloo, llm_plan(tag_families=["keyword"]))(state_with_cold(7))
    assert calls == 2 and qloo.pick_calls == [] and update["bridges"] == []


def test_no_follow_up_and_no_probe_when_the_plan_says_no_probe() -> None:
    qloo = picker()
    update, calls = make_analyst(qloo, llm_plan(probe_tags=False))(state_with_cold(7))
    assert calls == 0 and qloo.tag_calls == [] and qloo.pick_calls == [] and update["bridge_potential"] == 0


def test_an_empty_follow_up_is_reported_as_such() -> None:
    qloo = Picker({"ida": TAGS_A, "idt": TAGS_T}, [])
    update, calls = make_analyst(qloo, llm_plan())(state_with_cold(7))
    assert calls == 3 and update["bridge_picks"] == [] and "follow-up in movies: nothing found" in update["decision"]


def test_a_failing_follow_up_does_not_fail_the_run() -> None:
    class Down(Picker):
        def tag_insights(self, tag_id: str, domain: str) -> list[Affinity]:
            raise QlooAPIError("timed out")

    update, calls = make_analyst(Down({"ida": TAGS_A, "idt": TAGS_T}, []), llm_plan(follow_up_domain="place"))(state_with_cold(7))
    assert calls == 3 and update["bridge_picks"] == [] and len(update["bridges"]) == 3
    assert "follow-up in places: Qloo did not answer" in update["decision"]


def test_bridge_potential_never_changes_the_scores() -> None:
    state = state_with_cold(7)
    plain = score(state["profiles"]["acquirer"], state["profiles"]["target"])
    assert make_analyst(picker(), llm_plan())(state)[0]["scores"] == plain


# ---- the memo template ----


def test_the_memo_template_quotes_the_bridge_potential_and_the_picks() -> None:
    state = state_with_cold(7)
    s = score(state["profiles"]["acquirer"], state["profiles"]["target"])
    found = [bridge(0, 0.8, 0.9), bridge(1, 0.5, 0.6)]
    picks = [BridgePick("Movie A", "movie", "urn:tag:genre:x:0", "b0")]
    rationale = build_memo("A", "T", s, found, True, picks)["rationale"]
    assert f"Qloo tags bridge the two audiences: b0, b1 (bridge potential {bridge_potential(found):g}/100)." in rationale
    assert "Following the strongest bridge, b0, Qloo suggests movies: Movie A." in rationale
    assert not any("suggests" in line for line in build_memo("A", "T", s, found, True)["rationale"])
    assert "Qloo tags found no bridging tastes between the two audiences (bridge potential 0/100)." in build_memo("A", "T", s, [], True)["rationale"]


# ---- the fixture handler and the client ----


def test_the_fixture_handler_serves_a_recorded_follow_up_and_empties_the_rest(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    client = make_client(tmp_path, fixture_handler(calls))
    assert client.tag_insights("urn:tag:never:recorded", "movie") == []  # no recording: empty, not a KeyError
    assert client.tag_insights("urn:tag:never:recorded", "book") == []
    assert calls[0].url.params["signal.interests.tags"] == "urn:tag:never:recorded"
    assert calls[0].url.params["filter.type"] == "urn:entity:movie" and calls[0].url.params["take"] == "5"
    assert "signal.interests.entities" not in calls[0].url.params
    assert BRAND_IDS  # the handler still serves brand-signalled calls


def test_an_unknown_domain_is_rejected_by_tag_insights(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_client(tmp_path, fixture_handler([])).tag_insights("urn:tag:genre:x", "gadgets")
