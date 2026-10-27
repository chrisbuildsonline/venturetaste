import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from api import llm
from api.fixtures import fixture_handler, make_client
from api.pipeline import run_diligence
from api.qloo import QlooClient

MODEL = "fake-model"


def client(tmp_path: Path) -> QlooClient:
    return make_client(tmp_path, fixture_handler([]))


def fake(*replies: dict[str, Any] | None) -> Any:
    """A fake LLM: answers the calls in order, remembers what it was asked."""
    queue = list(replies)
    asked: list[tuple[str, str]] = []

    def call(system: str, user: str) -> tuple[str, dict[str, Any]] | None:
        asked.append((system, user))
        reply = queue.pop(0)
        return None if reply is None else (MODEL, reply)

    call.asked = asked  # type: ignore[attr-defined]
    return call


def trace_of(report: dict[str, Any], agent: str) -> dict[str, Any]:
    return next(t for t in report["trace"] if t["agent"] == agent)


def names(report: dict[str, Any]) -> list[str]:
    return [t["name"] for t in report["top_shared"]]


# ---- the planner ----


def test_planner_says_probe_so_the_probe_runs_on_a_warm_pair(tmp_path: Path) -> None:
    llm_ = fake({"probe_tags": True, "reason": "audiences look far apart"}, None)
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=llm_)
    analyst = trace_of(report, "Analyst")
    assert report["probed_tags"] is True and analyst["qloo_calls"] == 2
    assert analyst["planner"] == "llm" and analyst["model"] == MODEL
    assert MODEL in analyst["decision"] and "audiences look far apart" in analyst["decision"]


def test_planner_says_no_so_a_cold_pair_skips_the_probe(tmp_path: Path) -> None:
    llm_ = fake({"probe_tags": False, "reason": "nothing to bridge"}, None)
    report = run_diligence(client(tmp_path), "Patagonia", "Gucci", llm=llm_)
    analyst = trace_of(report, "Analyst")
    assert report["probed_tags"] is False and analyst["qloo_calls"] == 0
    assert analyst["planner"] == "llm"


def test_planner_gets_the_overlap_numbers_and_brand_names(tmp_path: Path) -> None:
    llm_ = fake({"probe_tags": False, "reason": "x"}, None)
    run_diligence(client(tmp_path), "Patagonia", "Gucci", llm=llm_)
    prompt = llm_.asked[0][1]
    assert "Patagonia" in prompt and "Gucci" in prompt and "brand" in prompt and "cold" in prompt


@pytest.mark.parametrize("garbage", [{}, {"probe_tags": "yes", "reason": "x"}, {"probe_tags": True}, {"probe_tags": True, "reason": ""}])
def test_garbage_plan_falls_back_to_the_rule(tmp_path: Path, garbage: dict[str, Any]) -> None:
    report = run_diligence(client(tmp_path), "Patagonia", "Gucci", llm=fake(garbage, None))
    analyst = trace_of(report, "Analyst")
    assert report["probed_tags"] is True  # 7 cold domains: the rule probes
    assert analyst["planner"] == "rule" and analyst["fallback"]


def test_unreachable_llm_falls_back_to_the_rule(tmp_path: Path) -> None:
    report = run_diligence(client(tmp_path), "Nike", "Adidas", llm=fake(None, None))
    analyst = trace_of(report, "Analyst")
    assert report["probed_tags"] is False
    assert analyst["planner"] == "rule" and analyst["fallback"] == "LLM unreachable"


def test_the_planner_never_changes_the_scores(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    planned = run_diligence(client(tmp_path), "Nike", "Adidas", llm=fake({"probe_tags": True, "reason": "x"}, None))
    assert planned["scores"] == plain["scores"] and planned["domain_overlap"] == plain["domain_overlap"]


# ---- the memo writer ----


def valid_memo(report: dict[str, Any]) -> dict[str, Any]:
    first, second = names(report)[:2]
    return {
        "rationale": [
            {"text": f"Both audiences love {first} and {second}.", "cites": [first.upper(), second]},
            {"text": "The BCI of 53.9 shows heavy overlap.", "cites": []},
        ],
        "risks": [{"text": f"Fans of {first} may be cannibalized.", "cites": [first]}],
    }


def with_memo(tmp_path: Path, memo: dict[str, Any] | None) -> dict[str, Any]:
    return run_diligence(client(tmp_path), "Nike", "Adidas", llm=fake({"probe_tags": False, "reason": "x"}, memo))


def test_valid_memo_is_used_and_attributed(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    report = with_memo(tmp_path, valid_memo(plain))
    memo = report["memo"]
    assert memo["author"] == MODEL
    assert set(memo) == {"verdict", "headline", "rationale", "risks", "author"}
    assert memo["verdict"] == plain["memo"]["verdict"] and memo["headline"] == plain["memo"]["headline"]
    assert memo["rationale"][1] == "The BCI of 53.9 shows heavy overlap."
    assert all(isinstance(r, str) for r in memo["rationale"] + memo["risks"])
    partner = trace_of(report, "Partner")
    assert partner["planner"] == "llm" and partner["model"] == MODEL


def test_memo_sees_the_scores_and_the_real_entities(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    llm_ = fake({"probe_tags": False, "reason": "x"}, valid_memo(plain))
    run_diligence(client(tmp_path), "Nike", "Adidas", llm=llm_)
    prompt = llm_.asked[1][1]
    assert names(plain)[0] in prompt and str(plain["scores"]["bci"]) in prompt and plain["memo"]["verdict"] in prompt


def test_unknown_cite_rejects_the_whole_memo(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    bad = valid_memo(plain)
    bad["risks"].append({"text": "Fans of Zorp Cola dislike it.", "cites": ["Zorp Cola"]})
    report = with_memo(tmp_path, bad)
    assert report["memo"] == {**plain["memo"], "author": "template"}
    partner = trace_of(report, "Partner")
    assert partner["planner"] == "template" and partner["fallback"] == "LLM cited unknown entity 'Zorp Cola'"


def test_cite_missing_from_its_text_is_rejected(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    bad = valid_memo(plain)
    bad["rationale"][0]["text"] = "Both audiences share some tastes."
    report = with_memo(tmp_path, bad)
    assert report["memo"]["author"] == "template"
    assert "not in its text" in trace_of(report, "Partner")["fallback"]


def test_no_cites_and_no_number_is_rejected(tmp_path: Path) -> None:
    plain = run_diligence(client(tmp_path), "Nike", "Adidas")
    bad = valid_memo(plain)
    bad["rationale"][1] = {"text": "Vibes are good.", "cites": []}
    assert with_memo(tmp_path, bad)["memo"]["author"] == "template"


@pytest.mark.parametrize(
    "broken",
    [{}, {"rationale": [], "risks": []}, {"rationale": "x", "risks": "y"}, {"rationale": [{"text": "a 1"}], "risks": [{"text": "b 2", "cites": []}]}],
)
def test_malformed_memo_uses_the_template(tmp_path: Path, broken: dict[str, Any]) -> None:
    report = with_memo(tmp_path, broken)
    assert report["memo"]["author"] == "template" and trace_of(report, "Partner")["fallback"]


def test_no_llm_answer_uses_the_template(tmp_path: Path) -> None:
    report = with_memo(tmp_path, None)
    partner = trace_of(report, "Partner")
    assert report["memo"]["author"] == "template"
    assert partner["planner"] == "template" and partner["fallback"] == "LLM unreachable"


def test_run_without_an_llm_is_all_template(tmp_path: Path) -> None:
    report = run_diligence(client(tmp_path), "Nike", "Adidas")
    assert report["memo"]["author"] == "template"
    assert trace_of(report, "Analyst")["planner"] == "rule" and trace_of(report, "Partner")["planner"] == "template"


# ---- api/llm.py ----


def test_off_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_LLM", "off")

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("network call while off")

    monkeypatch.setattr(httpx, "post",boom)
    assert llm.chat_json("s", "u") is None


def test_connection_refused_returns_none_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTURETASTE_LLM", raising=False)
    monkeypatch.setenv("VENTURETASTE_LLM_URL", "http://127.0.0.1:9/v1")
    start = time.perf_counter()
    assert llm.chat_json("s", "u") is None
    assert time.perf_counter() - start < 3


def test_chat_json_parses_the_reply_and_sends_the_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content.decode()
        content = '<think>hmm</think>{"a": 1}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.delenv("VENTURETASTE_LLM", raising=False)
    monkeypatch.setenv("VENTURETASTE_LLM_URL", "http://llm.test/v1")
    monkeypatch.setenv("VENTURETASTE_LLM_MODEL", "m1")
    monkeypatch.setenv("VENTURETASTE_LLM_API_KEY", "sekret")

    def post(url: str, **kwargs: Any) -> httpx.Response:
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post",post)
    assert llm.chat_json("s", "u") == ("m1", {"a": 1})
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sekret"
    assert '"temperature":0' in seen["body"].replace(" ", "") and "json_object" in seen["body"]


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_bad_json_returns_none(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    monkeypatch.delenv("VENTURETASTE_LLM", raising=False)

    def post(url: str, **kwargs: Any) -> httpx.Response:
        handler = lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})  # noqa: E731
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post",post)
    assert llm.chat_json("s", "u") is None
