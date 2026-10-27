"""Record checked LLM replies to api/fixture_data/llm_replay.json. Run: bun run record:llm (bun run llm:up first).

Runs the real pipeline with the LLM live on the fixture Qloo answers for every preset, screen and discovered pair, and on
live Qloo for the preset pairs. Only replies that pass the pipeline's own checks are kept, keyed by the prompt hash."""

import json
import sys
import time
from typing import Any

from api.llm import REPLAY_FILE, chat_json, prompt_hash
from api.main import fixture_client
from api.pipeline import MEMO_SYSTEM, PLAN_SYSTEM, run_diligence
from api.presets import DISCOVERED, PRESETS, SCREENS
from api.qloo import MissingKeyError, QlooClient, QlooError

ATTEMPTS = 4  # a cold Ollama needs 20-50 s to load the weights, so the first calls time out


def fixture_pairs() -> list[tuple[str, str]]:
    pairs = [(p.acquirer, p.target) for p in PRESETS]
    pairs += [(s.acquirer, t) for s in SCREENS for t in s.targets]
    pairs += [(a, t) for a, targets in DISCOVERED.items() for t in targets]
    return list(dict.fromkeys(pairs))


def record(client: QlooClient, acquirer: str, target: str, source: str, replay: dict[str, Any]) -> None:
    calls: list[tuple[str, str, str, tuple[str, dict[str, Any]] | None]] = []  # step, system, user, reply

    def llm(system: str, user: str) -> tuple[str, dict[str, Any]] | None:
        reply = None
        for attempt in range(ATTEMPTS):
            reply = chat_json(system, user)
            if reply is not None:
                break
            time.sleep(5 * (attempt + 1))
        calls.append(("plan" if system == PLAN_SYSTEM else "memo", system, user, reply))
        return reply

    label = f"{acquirer} + {target} ({source})"
    try:
        report = run_diligence(client, acquirer, target, llm=llm)
    except QlooError as exc:
        print(f"{label}: skipped, Qloo failed: {exc}")
        return
    trace = {t["agent"]: t for t in report["trace"]}
    for step, agent in (("plan", "Analyst"), ("memo", "Partner")):
        item = trace[agent]
        call = next((c for c in calls if c[0] == step), None)
        if item["planner"] != "llm" or call is None or call[3] is None:
            print(f"{label} {step}: rejected, {item.get('fallback')}")
            if call is not None and call[3] is not None:
                print(f"    {json.dumps(call[3][1])}")
            continue
        key = prompt_hash(call[1], call[2])
        status = "recorded" if key not in replay else "recorded (same prompt as an earlier pair)"
        model, reply = call[3]
        replay[key] = {"model": model, "reply": reply, "pair": f"{acquirer} + {target}", "step": step}
        print(f"{label} {step}: {status}")
        print(f"    {item['decision'] if step == 'plan' else json.dumps(reply)}")


def main() -> int:
    replay: dict[str, Any] = {}
    dry = sys.argv[1:] == ["presets"]  # quick prompt check: the three presets on fixtures, nothing written
    for acquirer, target in fixture_pairs()[: len(PRESETS) if dry else None]:
        record(fixture_client(), acquirer, target, "fixtures", replay)
    if dry:
        return 0
    try:
        live = QlooClient()
    except MissingKeyError:
        print("QLOO_API_KEY not set: skipped the live Qloo pairs")
    else:
        for p in PRESETS:
            record(live, p.acquirer, p.target, "live Qloo", replay)
    if not replay:
        print("nothing recorded (is the LLM up? bun run llm:up); left the replay file as it was")
        return 1
    REPLAY_FILE.write_text(json.dumps(replay, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(replay)} replies to {REPLAY_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
