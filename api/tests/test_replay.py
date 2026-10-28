import json
import re
from pathlib import Path
from typing import Any

import pytest

from api import llm
from api.fixtures import fixture_handler, make_client
from api.pipeline import MEMO_SYSTEM, PLAN_SYSTEM, Plan, Rejected, _check_memo, _check_plan, run_diligence
from api.presets import PRESETS
from api.qloo import QlooClient

MODEL = "fake-model"


def client(tmp_path: Path) -> QlooClient:
    return make_client(tmp_path / "qloo", fixture_handler([]))


def trace_of(report: dict[str, Any], agent: str) -> dict[str, Any]:
    return next(t for t in report["trace"] if t["agent"] == agent)


def capture(tmp_path: Path, acquirer: str, target: str) -> list[tuple[str, str]]:
    """The (system, user) prompts the pipeline sends for a pair."""
    asked: list[tuple[str, str]] = []

    def spy(system: str, user: str) -> llm.Reply | None:
        asked.append((system, user))
        return None

    run_diligence(client(tmp_path), acquirer, target, llm=spy)
    return asked


def valid_memo(tmp_path: Path, acquirer: str, target: str) -> dict[str, Any]:
    plain = run_diligence(client(tmp_path), acquirer, target)
    first = plain["top_shared"][0]["name"]
    return {
        "rationale": [{"text": f"Both audiences love {first}.", "cites": [first]}, {"text": "The BCI of 53.9 shows heavy overlap.", "cites": []}],
        "risks": [{"text": f"Fans of {first} may be cannibalized.", "cites": [first]}],
    }


def write_replay(path: Path, asked: list[tuple[str, str]], replies: list[dict[str, Any]], model: str = MODEL) -> None:
    entries = {llm.prompt_hash(s, u): {"model": model, "reply": r, "pair": "Nike + Adidas", "step": "plan" if s == PLAN_SYSTEM else "memo"} for (s, u), r in zip(asked, replies, strict=True)}
    path.write_text(json.dumps(entries))


@pytest.fixture
def replay_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_replay.json"
    monkeypatch.setattr(llm, "REPLAY_FILE", path)
    return path


# ---- the wrapper ----


def test_a_live_reply_is_never_labelled_recorded(replay_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_replay(replay_file, [("s", "u")], [{"a": 1}])
    monkeypatch.setattr(llm, "chat_json", lambda s, u: ("live-model", {"b": 2}))
    reply = llm.chat_json_or_replay("s", "u")
    assert reply == ("live-model", {"b": 2}) and not isinstance(reply, llm.Recorded)


def test_exact_pair_replays_when_the_llm_is_off(replay_file: Path) -> None:
    write_replay(replay_file, [("s", "u")], [{"a": 1}], model="qwen2.5:7b")
    reply = llm.chat_json_or_replay("s", "u")
    assert isinstance(reply, llm.Recorded) and reply == ("qwen2.5:7b", {"a": 1})
    assert llm.chat_json_or_replay("s", "u2") is None  # one changed character, no replay


def test_missing_or_broken_replay_file_is_just_no_replay(replay_file: Path) -> None:
    assert llm.chat_json_or_replay("s", "u") is None
    replay_file.write_text("not json")
    assert llm.chat_json_or_replay("s", "u") is None


# ---- through the pipeline ----


def test_replayed_plan_and_memo_are_labelled_recorded_and_pass_the_checks(tmp_path: Path, replay_file: Path) -> None:
    asked = capture(tmp_path, "Nike", "Adidas")
    assert [s for s, _ in asked] == [PLAN_SYSTEM, MEMO_SYSTEM]
    write_replay(replay_file, asked, [{"probe_tags": False, "reason": "most domains overlap"}, valid_memo(tmp_path, "Nike", "Adidas")])
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=llm.chat_json_or_replay)
    analyst, partner = trace_of(report, "Analyst"), trace_of(report, "Partner")
    assert analyst["planner"] == "llm" and analyst["recorded"] is True and analyst["model"] == MODEL
    assert partner["planner"] == "llm" and partner["recorded"] is True
    assert "(recorded fake-model: most domains overlap)" in analyst["decision"]
    assert report["memo"]["author"] == "recorded fake-model"
    assert report["memo"]["rationale"][1] == "The BCI of 53.9 shows heavy overlap."


def test_a_live_run_has_no_recorded_flag(tmp_path: Path) -> None:
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=lambda s, u: (MODEL, {"probe_tags": False, "reason": "most domains overlap"}))
    assert "recorded" not in trace_of(report, "Analyst")


def test_a_pair_with_no_recording_falls_back_to_rule_and_template(tmp_path: Path, replay_file: Path) -> None:
    asked = capture(tmp_path, "Nike", "Adidas")
    write_replay(replay_file, asked, [{"probe_tags": False, "reason": "x"}, valid_memo(tmp_path, "Nike", "Adidas")])
    report = run_diligence(client(tmp_path), "Adidas", "Nike", llm=llm.chat_json_or_replay)  # reversed: different prompts
    analyst, partner = trace_of(report, "Analyst"), trace_of(report, "Partner")
    assert (analyst["planner"], analyst["fallback"]) == ("rule", "LLM unreachable")
    assert (partner["planner"], partner["fallback"]) == ("template", "LLM unreachable")
    assert "recorded" not in analyst and "recorded" not in partner and report["memo"]["author"] == "template"


def test_a_tampered_recording_citing_an_unknown_entity_gets_the_template(tmp_path: Path, replay_file: Path) -> None:
    asked = capture(tmp_path, "Nike", "Adidas")
    bad = valid_memo(tmp_path, "Nike", "Adidas")
    bad["risks"].append({"text": "Fans of Zorp Cola dislike it.", "cites": ["Zorp Cola"]})
    write_replay(replay_file, asked, [{"probe_tags": False, "reason": "most domains overlap"}, bad])
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=llm.chat_json_or_replay)
    partner = trace_of(report, "Partner")
    assert partner["planner"] == "template" and "recorded" not in partner
    assert partner["fallback"] == "LLM cited unknown entity 'Zorp Cola'" and report["memo"]["author"] == "template"
    assert trace_of(report, "Analyst")["recorded"] is True  # the good half still replays


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_every_preset_replays_recorded_for_both_agents(tmp_path: Path, preset: Any) -> None:
    """Fixture mode, LLM unreachable: fails when a prompt change leaves api/fixture_data/llm_replay.json stale."""
    report = run_diligence(client(tmp_path), preset.acquirer, preset.target, llm=llm.chat_json_or_replay)
    for agent in ("Analyst", "Partner"):
        step = trace_of(report, agent)
        assert (step["planner"], step.get("recorded")) == ("llm", True), step
    assert report["memo"]["author"] == f"recorded {llm.DEFAULT_MODEL}"


def test_the_nike_adidas_recording_probes_and_follows_up_with_no_llm_and_no_key(tmp_path: Path) -> None:
    """The demo shows the widened plan offline: chosen families, a scored bridge list and the follow-up's picks."""
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=llm.chat_json_or_replay)
    analyst = trace_of(report, "Analyst")
    assert report["probed_tags"] is True and analyst["qloo_calls"] == 3 and analyst["recorded"] is True
    assert re.search(r"probed Qloo tags \([a-z_, ]+\): \d bridging tastes? → follow-up in \w+: ", analyst["decision"]), analyst["decision"]
    assert report["bridges"] and 0 < report["bridge_potential"] <= 100
    assert report["bridge_picks"] and {p["tag_id"] for p in report["bridge_picks"]} == {report["bridges"][0]["id"]}


def test_the_docker_image_ships_the_replay_file() -> None:
    root = llm.REPLAY_FILE.parents[2]
    ignored = (root / ".dockerignore").read_text().split()
    assert llm.REPLAY_FILE.is_file() and not any(i.startswith(("api/fixture_data", "api/")) and not i.startswith("api/tests") for i in ignored)
    assert "COPY --chown=app api/ api/" in (root / "Dockerfile").read_text()


# ---- the reason must agree with the data ----


@pytest.mark.parametrize(
    ("reason", "overlapping"),
    [
        ("Low overlap in most domains.", 6),
        ("There is little overlap between the audiences.", 4),
        ("Overlap is limited, so probe.", 4),
        ("No overlap across domains.", 5),
        ("Minimal overlap so far.", 7),
        ("Strong overlap in most domains.", 0),
        ("Broad overlap across the audiences.", 3),
        ("Overlap is high.", 1),
    ],
)
def test_a_reason_that_contradicts_the_overlap_counts_is_rejected(reason: str, overlapping: int) -> None:
    with pytest.raises(Rejected):
        _check_plan({"probe_tags": True, "reason": reason}, overlapping, 7)


@pytest.mark.parametrize(
    ("reason", "overlapping"),
    [
        ("Low overlap in most domains.", 2),
        ("No overlap at all, so probe for bridging tastes.", 0),
        ("Strong overlap in most domains.", 6),
        ("Overlap in 6 of 7 domains, no need to probe.", 6),
        ("Audiences are far apart.", 3),
    ],
)
def test_a_reason_that_agrees_with_the_counts_is_kept(reason: str, overlapping: int) -> None:
    assert _check_plan({"probe_tags": False, "reason": reason}, overlapping, 7) == Plan(False, (), None, reason)


def test_a_memo_claiming_shared_tastes_is_rejected_when_the_audiences_share_none() -> None:
    claim = {"rationale": [{"cites": ["Moab"], "text": "Both audiences share a taste for Moab."}], "risks": [{"cites": ["Moab"], "text": "Moab is a risk."}]}
    with pytest.raises(Rejected):
        _check_memo(claim, {"moab"}, shared=False)
    assert _check_memo(claim, {"moab"}, shared=True)["rationale"]
    honest = {**claim, "rationale": [{"cites": ["Moab"], "text": "Moab and Gucci audiences share no tastes."}]}
    assert _check_memo(honest, {"moab"}, shared=False)["rationale"]


def test_the_plan_facts_and_prompt_carry_the_overlap_count(tmp_path: Path) -> None:
    system, user = capture(tmp_path, "Nike", "Adidas")[0]
    assert json.loads(user)["domains_with_overlap"] == 6
    assert "domains_with_overlap" in system and "agree" in system
