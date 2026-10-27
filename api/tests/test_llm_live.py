import time
from pathlib import Path

import pytest

from api import llm
from api.fixtures import fixture_handler, make_client
from api.pipeline import run_diligence

pytestmark = pytest.mark.llm


def test_real_llm_plans_and_writes_a_cited_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTURETASTE_LLM", raising=False)
    model = llm.model()
    # A cold Ollama needs a while to load the weights; the pipeline would time out and fall back, so load them first.
    warm_start = time.perf_counter()
    for _ in range(6):
        if llm.chat_json("Answer with the JSON object {}.", "{}") is not None:
            break
    print(f"\nwarm-up {time.perf_counter() - warm_start:.1f}s")
    start = time.perf_counter()
    replies: list[llm.Reply | None] = []

    def recording(system: str, user: str) -> llm.Reply | None:
        replies.append(llm.chat_json(system, user))
        return replies[-1]

    report = run_diligence(make_client(tmp_path, fixture_handler([])), "Nike", "Adidas", llm=recording)
    seconds = time.perf_counter() - start
    print("\nraw replies:", replies)
    trace = {t["agent"]: t for t in report["trace"]}
    print(f"\nmodel={model} run={seconds:.1f}s analyst={trace['Analyst']['ms']}ms partner={trace['Partner']['ms']}ms")
    print("analyst:", trace["Analyst"]["decision"])
    print("partner:", {k: v for k, v in trace["Partner"].items() if k != "agent"})
    print("memo:", report["memo"])

    assert trace["Analyst"]["planner"] == "llm" and trace["Analyst"]["model"] == model
    assert trace["Partner"]["planner"] == "llm", trace["Partner"]
    assert report["memo"]["author"] == model
    assert report["memo"]["rationale"] and report["memo"]["risks"]
    # every cite was checked by the pipeline; also check from outside that the memo names real Qloo entities
    known = {t["name"] for t in report["top_shared"]} | {t["name"] for side in report["top_clashing"].values() for t in side}
    known |= {b["name"] for b in report["bridges"]} | {b["name"] for b in report["brands"].values()}
    text = " ".join(report["memo"]["rationale"] + report["memo"]["risks"])
    assert any(name in text for name in known)
    assert report["memo"]["verdict"] == "Proceed"  # the verdict comes from the scores, not the model
