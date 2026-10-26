"""Four-agent diligence pipeline (LangGraph): Scout, Cartographer, Analyst, Partner. No LLM."""

import operator
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from api.qloo import DOMAINS, Demographics, Entity, QlooClient, QlooError, QlooParseError, Tag
from api.scoring import BrandProfile, Bridge, Scores, bridges, score

AGENTS = ("Scout", "Cartographer", "Analyst", "Partner")
SIDES = ("acquirer", "target")
MAX_WORKERS = 6
COLD_DOMAINS_TO_PROBE = 4  # this many of the 7 domains with zero overlap sends the Analyst to Qloo tags
PROCEED_BCI = 50  # synergy deals at or above this BCI get a clean "Proceed"
NAMED = 3  # entities quoted per sentence in the memo


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
    A step can put a "decision" string in its update: it goes on the trace item, not into the state."""

    def node(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        update, calls = step(state)
        ms = round((time.perf_counter() - start) * 1000)
        extra = {"decision": update.pop("decision")} if "decision" in update else {}
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


def make_analyst(client: TagSource) -> Step:
    def analyst(state: State) -> tuple[dict[str, Any], int]:
        profiles = state["profiles"]
        s = score(profiles["acquirer"], profiles["target"])
        cold = sum(1 for v in full_overlap(s).values() if v == 0)
        if cold < COLD_DOMAINS_TO_PROBE:
            decision = f"Overlap in {len(DOMAINS) - cold}/{len(DOMAINS)} domains → no tag probe needed"
            return {"scores": s, "bridges": [], "probed_tags": False, "decision": decision}, 0
        entities = state["entities"]
        tags_a, tags_b = _parallel([partial(client.tags, entities[side].id) for side in SIDES])
        found = bridges(tags_a, tags_b)
        n = f"{len(found)} bridging taste{'' if len(found) == 1 else 's'}" if found else "no bridging tastes found"
        decision = f"Overlap 0 in {cold}/{len(DOMAINS)} domains → probed Qloo tags: {n}"
        return {"scores": s, "bridges": found, "probed_tags": True, "decision": decision}, 2

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


def partner(state: State) -> tuple[dict[str, Any], int]:
    names = {side: state["profiles"][side].name for side in SIDES}
    memo = build_memo(names["acquirer"], names["target"], state["scores"], state["bridges"], state["probed_tags"])
    return {"memo": memo}, 0


def build_graph(client: QlooClient) -> Any:
    graph = StateGraph(State)
    steps: list[tuple[str, Step]] = [
        ("Scout", make_scout(client)),
        ("Cartographer", make_cartographer(client)),
        ("Analyst", make_analyst(client)),
        ("Partner", partner),
    ]
    for name, step in steps:
        node: Any = _agent(name, step)  # langgraph's overloads reject a plain State callable
        graph.add_node(name, node)
    graph.add_edge(START, steps[0][0])
    for (a, _), (b, _) in zip(steps, steps[1:], strict=False):
        graph.add_edge(a, b)
    graph.add_edge(steps[-1][0], END)
    return graph.compile()


def stream_diligence(client: QlooClient, acquirer: str, target: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Lazily yield ("agent", {...}) as each agent starts and finishes, then ("result", report). QlooErrors propagate."""
    yield "agent", {"agent": AGENTS[0], "status": "running"}
    state: dict[str, Any] = {"acquirer": acquirer, "target": target, "trace": []}
    for chunk in build_graph(client).stream(state, stream_mode="updates"):
        for update in chunk.values():
            state |= {**update, "trace": state["trace"] + update["trace"]}
            item = update["trace"][0]
            yield "agent", item
            if item["agent"] != AGENTS[-1]:
                yield "agent", {"agent": AGENTS[AGENTS.index(item["agent"]) + 1], "status": "running"}
    yield "result", _report(state, acquirer, target)


def run_diligence(client: QlooClient, acquirer: str, target: str) -> dict[str, Any]:
    return next(data for event, data in stream_diligence(client, acquirer, target) if event == "result")


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
