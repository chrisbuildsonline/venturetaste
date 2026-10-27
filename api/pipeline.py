"""Four-agent diligence pipeline (LangGraph): Scout, Cartographer, Analyst, Partner.

Scores, the verdict and the headline are deterministic and never depend on an LLM. An optional LLM (api/llm.py,
local Ollama by default) does two things: the Analyst asks it whether to probe Qloo tags, and the Partner asks it
to write the memo's rationale and risks. Every entity the LLM cites is checked against what Qloo returned; any
unusable answer (LLM off, unreachable, bad JSON, unknown cite) falls back to the COLD_DOMAINS_TO_PROBE rule and
the build_memo template, and the trace says which one decided.
"""

import json
import operator
import re
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from api.llm import Llm, Recorded
from api.qloo import DOMAINS, Demographics, Entity, QlooClient, QlooError, QlooParseError, Tag
from api.scoring import BrandProfile, Bridge, Scores, bridges, score

AGENTS = ("Scout", "Cartographer", "Analyst", "Partner")
SIDES = ("acquirer", "target")
MAX_WORKERS = 6
COLD_DOMAINS_TO_PROBE = 4  # this many of the 7 domains with zero overlap sends the Analyst to Qloo tags
PROCEED_BCI = 50  # synergy deals at or above this BCI get a clean "Proceed"
NAMED = 3  # entities quoted per sentence in the memo
TRACE_KEYS = ("decision", "planner", "model", "recorded", "fallback")  # step update keys that go on the trace item, not into the state


class NoTasteDataError(QlooError):
    pass


class SameBrandError(QlooError):
    pass


class State(TypedDict, total=False):
    acquirer: str
    target: str
    entities: dict[str, Entity]
    profiles: dict[str, BrandProfile]
    scores: Scores
    bridges: list[Bridge]
    probed_tags: bool
    memo: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], operator.add]


Step = Callable[[State], tuple[dict[str, Any], int]]  # state update, Qloo calls made


def _agent(name: str, step: Step) -> Callable[[State], dict[str, Any]]:
    """Wrap a step so it appends its name, status, duration and Qloo call count to the trace.
    A step can put TRACE_KEYS in its update: they go on the trace item, not into the state."""

    def node(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        update, calls = step(state)
        ms = round((time.perf_counter() - start) * 1000)
        extra = {k: update.pop(k) for k in TRACE_KEYS if k in update}
        return {**update, "trace": [{"agent": name, "status": "ok", "ms": ms, "qloo_calls": calls, **extra}]}

    return node


def _parallel[T](tasks: list[Callable[[], T]]) -> list[T]:
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        return [f.result() for f in [pool.submit(task) for task in tasks]]


def make_scout(client: QlooClient) -> Step:
    def scout(state: State) -> tuple[dict[str, Any], int]:
        acquirer, target = _parallel(
            [lambda: client.search(state["acquirer"]), lambda: client.search(state["target"])]
        )
        if acquirer.id == target.id:
            raise SameBrandError(f"Pick two different brands: {state['acquirer']!r} and {state['target']!r} are both {acquirer.name!r}")
        return {"entities": {"acquirer": acquirer, "target": target}}, 2

    return scout


def make_cartographer(client: QlooClient) -> Step:
    def demographics(entity_id: str) -> Demographics:
        try:
            return client.demographics(entity_id)
        except QlooParseError:
            return Demographics(age={}, gender={})  # Qloo knows the brand but not its audience

    def cartographer(state: State) -> tuple[dict[str, Any], int]:
        entities = state["entities"]
        tasks: list[Callable[[], Any]] = []
        for side in SIDES:
            entity_id = entities[side].id
            tasks += [partial(client.insights, entity_id, d) for d in DOMAINS]
            tasks.append(partial(demographics, entity_id))
        results = iter(_parallel(tasks))
        profiles = {}
        for side in SIDES:
            insights = {d: next(results) for d in DOMAINS}
            profiles[side] = BrandProfile(entities[side].name, insights, next(results))
            if not any(insights.values()):
                raise NoTasteDataError(f"Qloo has no taste data for {entities[side].name!r}")
        return {"profiles": profiles}, len(tasks)

    return cartographer


class TagSource(Protocol):
    def tags(self, entity_id: str) -> list[Tag]: ...


class Rejected(Exception):
    """The LLM answered, but not with something usable."""


def _ask[T](llm: Llm | None, system: str, user: str, check: Callable[[dict[str, Any]], T], fallback: str) -> tuple[T | None, dict[str, Any]]:
    """The checked LLM answer (or None) and the trace fields saying who decided; `fallback` names the non-LLM way."""
    if llm is None:
        return None, {"planner": fallback, "fallback": "LLM off"}
    reply = llm(system, user)
    if reply is None:
        return None, {"planner": fallback, "fallback": "LLM unreachable"}
    model, raw = reply
    try:
        return check(raw), {"planner": "llm", "model": model, **({"recorded": True} if isinstance(reply, Recorded) else {})}
    except Rejected as exc:
        return None, {"planner": fallback, "fallback": str(exc)}


def _credit(who: dict[str, Any]) -> str:
    """The model's name, marked as recorded when the reply was replayed rather than live."""
    return f"recorded {who['model']}" if who.get("recorded") else str(who["model"])


PLAN_SYSTEM = (
    "You are the Analyst on an M&A taste-diligence team. You get the taste overlap between two consumer brands' audiences "
    "per domain (0 to 1), how many domains have some overlap (domains_with_overlap) and how many have none (cold_domains). "
    "Decide whether to spend two extra Qloo calls probing taste tags to look for bridging tastes between the audiences. "
    "The reason must agree with those counts: do not call the overlap low when most domains have overlap, "
    "and do not call it high when most domains have none. "
    'Answer with JSON only: {"probe_tags": true or false, "reason": "one short sentence"}.'
)
LOW_OVERLAP = re.compile(
    r"\b(?:low|little|limited|minimal|weak|no)\s+(?:\w+\s+)?overlap|\boverlap\s+(?:is\s+|are\s+|looks\s+|seems\s+)?(?:low|limited|minimal|weak|absent)\b",
    re.IGNORECASE,
)
HIGH_OVERLAP = re.compile(
    r"\b(?:high|strong|broad|significant|substantial|extensive|large)\s+(?:\w+\s+)?overlap|\boverlap\s+(?:is\s+|are\s+|looks\s+|seems\s+)?(?:high|strong|broad|significant)\b",
    re.IGNORECASE,
)


def _check_plan(raw: dict[str, Any], overlapping: int, domains: int) -> tuple[bool, str]:
    probe, reason = raw.get("probe_tags"), raw.get("reason")
    if not isinstance(probe, bool) or not isinstance(reason, str) or not reason.strip():
        raise Rejected("LLM plan was not {probe_tags: bool, reason: str}")
    if overlapping * 2 >= domains and LOW_OVERLAP.search(reason):
        raise Rejected(f"LLM reason says overlap is low but {overlapping}/{domains} domains overlap")
    if overlapping * 2 < domains and HIGH_OVERLAP.search(reason):
        raise Rejected(f"LLM reason says overlap is high but only {overlapping}/{domains} domains overlap")
    return probe, reason.strip()[:200]


def make_analyst(client: TagSource, llm: Llm | None = None) -> Step:
    def analyst(state: State) -> tuple[dict[str, Any], int]:
        profiles = state["profiles"]
        s = score(profiles["acquirer"], profiles["target"])
        overlap = full_overlap(s)
        cold = sum(1 for v in overlap.values() if v == 0)
        facts = {
            "acquirer": profiles["acquirer"].name,
            "target": profiles["target"].name,
            "domain_overlap": {d: round(v, 3) for d, v in overlap.items()},
            "domains_with_overlap": len(DOMAINS) - cold,
            "cold_domains": cold,
            "domains": len(DOMAINS),
        }
        plan, who = _ask(llm, PLAN_SYSTEM, json.dumps(facts), lambda raw: _check_plan(raw, len(DOMAINS) - cold, len(DOMAINS)), "rule")
        probe, reason = plan if plan else (cold >= COLD_DOMAINS_TO_PROBE, "")
        found: list[Bridge] = []
        if probe:
            entities = state["entities"]
            tags_a, tags_b = _parallel([partial(client.tags, entities[side].id) for side in SIDES])
            found = bridges(tags_a, tags_b)
            n = f"{len(found)} bridging taste{'' if len(found) == 1 else 's'}" if found else "no bridging tastes found"
            decision = f"Overlap 0 in {cold}/{len(DOMAINS)} domains → probed Qloo tags: {n}"
        else:
            decision = f"Overlap in {len(DOMAINS) - cold}/{len(DOMAINS)} domains → no tag probe needed"
        if plan:
            decision += f" ({_credit(who)}: {reason})"
        return {"scores": s, "bridges": found, "probed_tags": probe, "decision": decision, **who}, 2 if probe else 0

    return analyst


SINGULAR = {
    "brand": "Brand",
    "artist": "Artist",
    "movie": "Movie",
    "tv_show": "TV show",
    "place": "Place",
    "destination": "Destination",
    "book": "Book",
}
PLURAL = {
    "brand": "brands",
    "artist": "artists",
    "movie": "movies",
    "tv_show": "TV shows",
    "place": "places",
    "destination": "destinations",
    "book": "books",
}


def _names(items: Any) -> str:
    return ", ".join(f"{i.name} ({SINGULAR[i.domain]})" for i in items[:NAMED])


def full_overlap(s: Scores) -> dict[str, float]:
    """Overlap for all seven domains; a domain scoring left out (no data for either brand) is 0."""
    return {d: s.domain_overlap.get(d, 0.0) for d in DOMAINS}


def build_memo(
    acquirer: str, target: str, s: Scores, found: list[Bridge] | None = None, probed: bool = False
) -> dict[str, Any]:
    """Deterministic deal memo: templated from the scores and the real Qloo entities behind them."""
    verdict = "Pass" if s.churn_risk == "high" else "Proceed" if s.bci >= PROCEED_BCI else "Proceed with conditions"
    rationale = []
    if s.top_shared:
        rationale.append(f"Both audiences share tastes for {_names(s.top_shared)}.")
    overlap = full_overlap(s)
    best = max(DOMAINS, key=lambda d: overlap[d])
    if overlap[best] > 0:
        rationale.append(f"Strongest taste overlap is in {PLURAL[best]} ({overlap[best]:.0%} weighted overlap).")
    else:
        rationale.append("Qloo finds no shared taste entities in any domain.")
    if found:
        rationale.append(f"Qloo tags bridge the two audiences: {', '.join(b.name for b in found[:NAMED])}.")
    elif probed:
        rationale.append("Qloo tags found no bridging tastes between the two audiences.")
    rationale.append(f"Audience demographic distance is {s.demographic_distance:.2f} (0 means identical).")

    risks = [f"Culture clash is {s.culture_clash}%, so churn risk is {s.churn_risk}."]
    if s.bci >= PROCEED_BCI and s.top_shared:
        risks.append(f"Audiences overlap heavily (BCI {s.bci}), so expect cannibalization around {_names(s.top_shared)}.")
    for name, other, clashing in ((acquirer, target, s.top_clashing_a), (target, acquirer, s.top_clashing_b)):
        if clashing:
            risks.append(f"{name}'s audience favours {_names(clashing)}, which {other}'s audience does not.")
    cold = [d for d in DOMAINS if overlap[d] == 0]
    if cold:
        risks.append(f"No shared taste in {', '.join(PLURAL[d] for d in cold)}, so cross-selling there starts from scratch.")
    headline = f"{verdict}: {acquirer} + {target} scores BCI {s.bci} with {s.churn_risk} churn risk."
    return {"verdict": verdict, "headline": headline, "rationale": rationale, "risks": risks}


MEMO_SYSTEM = (
    "You are the Partner on an M&A taste-diligence team writing the rationale and risks of a deal memo for two consumer "
    "brands. The verdict is already decided; do not change it. Use only the scores and the Qloo entities you are given. "
    'Answer with JSON only: {"rationale": [{"cites": [str], "text": str}], "risks": [{"cites": [str], "text": str}]}. '
    "Write 2 or 3 short items per list, each of one of three kinds, and say only what the data says. "
    "Code checks every item and throws the whole memo away on one violation: a name in cites must be in allowed_cites and must be "
    "written in that item's text exactly as in cites, and a name written in the text but not in cites is fine. cites has at most 3 names. "
    "Kind 1, a shared taste (rationale): the text names one to three entities from top_shared, and cites lists exactly those. "
    "If the facts have first_rationale_item, the audiences share NO tastes: copy that item verbatim as your first rationale item "
    "and make it the only rationale item; never write that the audiences share or love anything. "
    "Kind 2, a clash (risks): the text names one to three entities from one list of top_clashing and says that the audience of the brand "
    "in the list's name (favoured_by_<brand>) favours them but the other brand's audience does not; cites lists exactly those. "
    "Kind 3, the score: copy score_item from the facts verbatim as the last item of risks; it is the only item that quotes a score. "
    'Example of kind 1: {"cites": ["<name 1>", "<name 2>"], "text": "Both audiences share a taste for <name 1> and <name 2>."} '
    "with the placeholders replaced by names from allowed_cites or by the numbers and labels in the facts. "
    "Never leave a name in cites that the text does not contain. Do not write about bridges, ownership, history, products, "
    "mergers or what an audience likes beyond top_shared and top_clashing, and never describe the overlap or the BCI with an adjective such as high, low, moderate or strong; quote the number instead."
)


SHARED_CLAIM = re.compile(r"\bboth audiences\b|\bshare an? tastes?\b|\baudiences? (?:also )?(?:share|love)\b", re.IGNORECASE)


def _check_memo(raw: dict[str, Any], known: set[str], shared: bool = True) -> dict[str, list[str]]:
    memo: dict[str, list[str]] = {}
    for key in ("rationale", "risks"):
        items = raw.get(key)
        if not isinstance(items, list) or not items:
            raise Rejected(f"LLM memo has no {key}")
        texts = []
        for item in items:
            text = item.get("text") if isinstance(item, dict) else None
            cites = item.get("cites") if isinstance(item, dict) else None
            if not isinstance(text, str) or not text.strip() or not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
                raise Rejected(f"LLM memo {key} item is not {{text, cites}}")
            for c in cites:
                if c.casefold() not in known:
                    raise Rejected(f"LLM cited unknown entity {c!r}")
                if c.casefold() not in text.casefold():
                    raise Rejected(f"LLM cite {c!r} is not in its text")
            if key == "rationale" and not shared and SHARED_CLAIM.search(text) and "no tastes" not in text:
                raise Rejected("LLM memo claims shared tastes but the audiences share none")
            if not cites and not re.search(r"\d", text):
                raise Rejected(f"LLM memo {key} item cites no entity and no number")
            texts.append(text.strip())
        memo[key] = texts
    return memo


def make_partner(llm: Llm | None = None) -> Step:
    def partner(state: State) -> tuple[dict[str, Any], int]:
        names = {side: state["profiles"][side].name for side in SIDES}
        s, found = state["scores"], state["bridges"]
        template = build_memo(names["acquirer"], names["target"], s, found, state["probed_tags"])
        shared = [{"name": t.name, "domain": t.domain} for t in s.top_shared]
        clashing = {
            side: [{"name": t.name, "domain": t.domain} for t in c]
            for side, c in zip(SIDES, (s.top_clashing_a, s.top_clashing_b), strict=True)
        }
        # Qloo entities behind this run: shared and distinctive tastes, bridging tags, and the two brands themselves
        known = {n.casefold() for n in [*(e["name"] for e in [*shared, *clashing["acquirer"], *clashing["target"]]), *(b.name for b in found), *names.values()]}
        # the model sees only the first NAMED of each list (like the template): it copies long lists into cites without writing them
        shared, clashing = shared[:NAMED], {side: c[:NAMED] for side, c in clashing.items()}
        allowed = list(dict.fromkeys([*(e["name"] for e in [*shared, *clashing["acquirer"], *clashing["target"]]), *(b.name for b in found[:NAMED]), *names.values()]))
        facts = {
            "acquirer": names["acquirer"],
            "target": names["target"],
            "verdict": template["verdict"],
            "scores": {"bci": s.bci, "culture_clash": s.culture_clash, "churn_risk": s.churn_risk, "demographic_distance": s.demographic_distance},
            "domain_overlap": {d: round(v, 3) for d, v in full_overlap(s).items()},
            "top_shared": shared,
            "top_clashing": {"favoured_by_" + names[side]: items for side, items in clashing.items()},
            "bridges": [b.name for b in found[:NAMED]],
            "allowed_cites": allowed,
            "score_item": {"cites": [], "text": f"Culture clash is {s.culture_clash}%, so churn risk is {s.churn_risk}."},
        }
        if not shared:
            facts["first_rationale_item"] = {"cites": list(names.values()), "text": f"{names['acquirer']} and {names['target']} audiences share no tastes (BCI {s.bci})."}
        written, who = _ask(llm, MEMO_SYSTEM, json.dumps(facts), lambda raw: _check_memo(raw, known, bool(s.top_shared)), "template")
        memo = {**template, **written, "author": _credit(who)} if written else {**template, "author": "template"}
        return {"memo": memo, **who}, 0

    return partner


def build_graph(client: QlooClient, llm: Llm | None = None) -> Any:
    graph = StateGraph(State)
    steps: list[tuple[str, Step]] = [
        ("Scout", make_scout(client)),
        ("Cartographer", make_cartographer(client)),
        ("Analyst", make_analyst(client, llm)),
        ("Partner", make_partner(llm)),
    ]
    for name, step in steps:
        node: Any = _agent(name, step)  # langgraph's overloads reject a plain State callable
        graph.add_node(name, node)
    graph.add_edge(START, steps[0][0])
    for (a, _), (b, _) in zip(steps, steps[1:], strict=False):
        graph.add_edge(a, b)
    graph.add_edge(steps[-1][0], END)
    return graph.compile()


def stream_diligence(client: QlooClient, acquirer: str, target: str, llm: Llm | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    """Lazily yield ("agent", {...}) as each agent starts and finishes, then ("result", report). QlooErrors propagate."""
    yield "agent", {"agent": AGENTS[0], "status": "running"}
    state: dict[str, Any] = {"acquirer": acquirer, "target": target, "trace": []}
    for chunk in build_graph(client, llm).stream(state, stream_mode="updates"):
        for update in chunk.values():
            state |= {**update, "trace": state["trace"] + update["trace"]}
            item = update["trace"][0]
            yield "agent", item
            if item["agent"] != AGENTS[-1]:
                yield "agent", {"agent": AGENTS[AGENTS.index(item["agent"]) + 1], "status": "running"}
    yield "result", _report(state, acquirer, target)


def run_diligence(client: QlooClient, acquirer: str, target: str, llm: Llm | None = None) -> dict[str, Any]:
    return next(data for event, data in stream_diligence(client, acquirer, target, llm) if event == "result")


def _report(state: dict[str, Any], acquirer: str, target: str) -> dict[str, Any]:
    s = state["scores"]
    return {
        "brands": {
            "acquirer": {"query": acquirer, **asdict(state["entities"]["acquirer"])},
            "target": {"query": target, **asdict(state["entities"]["target"])},
        },
        "scores": {
            "bci": s.bci,
            "culture_clash": s.culture_clash,
            "churn_risk": s.churn_risk,
            "demographic_distance": s.demographic_distance,
        },
        "domain_overlap": full_overlap(s),
        "top_shared": [asdict(t) for t in s.top_shared],
        "top_clashing": {
            "acquirer": [asdict(t) for t in s.top_clashing_a],
            "target": [asdict(t) for t in s.top_clashing_b],
        },
        "demographics": {side: asdict(state["profiles"][side].demographics) for side in SIDES},
        "bridges": [asdict(b) for b in state["bridges"]],
        "probed_tags": state["probed_tags"],
        "memo": state["memo"],
        "trace": state["trace"],
    }
