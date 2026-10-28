"""Pure scoring of two brands from their Qloo taste profiles (no I/O, no LLM)."""

import math
from collections.abc import Callable, Collection
from dataclasses import dataclass

from api.qloo import Affinity, Demographics, Tag

# Blend: taste overlap counts 70%, audience demographics 30%.
OVERLAP_WEIGHT, DEMO_WEIGHT = 0.7, 0.3
# Culture clash blend: exclusive (clashing) taste mass 70%, audience demographic distance 30%.
CLASH_TASTE_WEIGHT = 0.7
TOP_N = 5
# Churn-risk bands on culture clash (the one place to tune them): below LOW_BELOW is low, below HIGH_FROM medium.
LOW_BELOW, HIGH_FROM = 33, 66


@dataclass(frozen=True)
class BrandProfile:
    name: str
    insights: dict[str, list[Affinity]]
    demographics: Demographics


@dataclass(frozen=True)
class SharedTaste:
    domain: str
    name: str
    affinity_a: float
    affinity_b: float


@dataclass(frozen=True)
class ClashingTaste:
    domain: str
    name: str
    affinity: float


@dataclass(frozen=True)
class Bridge:
    id: str
    name: str
    affinity_acquirer: float
    affinity_target: float


@dataclass(frozen=True)
class BridgePick:
    name: str  # an entity Qloo ties to the bridge tag
    domain: str
    tag_id: str
    tag_name: str


@dataclass(frozen=True)
class Scores:
    bci: float  # Brand Cannibalization Index, 0..100
    culture_clash: float  # 0..100
    churn_risk: str  # "low" | "medium" | "high"
    demographic_distance: float  # 0..1
    domain_overlap: dict[str, float]  # 0..1 per domain, for the radar chart
    top_shared: tuple[SharedTaste, ...]
    top_clashing_a: tuple[ClashingTaste, ...]  # strong for a, absent for b
    top_clashing_b: tuple[ClashingTaste, ...]  # strong for b, absent for a


def _clamp(x: float, hi: float) -> float:
    return 0.0 if not math.isfinite(x) else max(0.0, min(hi, x))


def _weights(items: list[Affinity]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        out[item.id] = max(out.get(item.id, 0.0), _clamp(item.affinity, math.inf))
    return out


def domain_overlap(a: list[Affinity], b: list[Affinity]) -> float:
    """Weighted Jaccard over entity ids, weight = affinity clamped at 0."""
    wa, wb = _weights(a), _weights(b)
    ids = sorted(wa.keys() | wb.keys())
    top = sum(max(wa.get(i, 0.0), wb.get(i, 0.0)) for i in ids)
    if top == 0:
        return 0.0
    return _clamp(sum(min(wa.get(i, 0.0), wb.get(i, 0.0)) for i in ids) / top, 1.0)


def _own_exclusive(mine: dict[str, float], other: dict[str, float]) -> float | None:
    """Share of my positive affinity mass on entities the other brand lacks entirely; None if I have no mass."""
    total = sum(mine.values())
    if not total > 0 or not math.isfinite(total):
        return None
    return _clamp(sum(w for i, w in mine.items() if i not in other) / total, 1.0)


def exclusive_mass(a: list[Affinity], b: list[Affinity]) -> float:
    """Clashing-taste mass of one domain, 0..1: mean over the two brands (those with taste mass) of the
    share of their affinity that sits on entities the other brand does not list at all."""
    wa, wb = _weights(a), _weights(b)
    shares = [s for s in (_own_exclusive(wa, wb), _own_exclusive(wb, wa)) if s is not None]
    return sum(shares) / len(shares) if shares else 0.0


def demographic_distance(a: Demographics, b: Demographics) -> float:
    """Mean absolute difference over the union of age and gender keys, halved to land in 0..1."""
    va, vb = {**a.age, **a.gender}, {**b.age, **b.gender}
    keys = sorted(va.keys() | vb.keys())
    if not keys:
        return 0.0

    def val(v: dict[str, float], k: str) -> float:
        x = v.get(k, 0.0)
        return x if math.isfinite(x) else 0.0

    return _clamp(sum(abs(val(va, k) - val(vb, k)) for k in keys) / len(keys) / 2, 1.0)


def _clean[T: (SharedTaste, ClashingTaste)](items: list[T], brands: set[str], strength: Callable[[T], float]) -> list[T]:
    """Drop the two brands themselves, rank by strength, keep the strongest of each (domain, name)."""
    ranked = sorted(
        (t for t in items if t.name.casefold() not in brands),
        key=lambda t: (-strength(t), t.domain, t.name),
    )
    kept: dict[tuple[str, str], T] = {}
    for t in ranked:
        kept.setdefault((t.domain, t.name.casefold()), t)
    return list(kept.values())


# Qloo tag families that say nothing about taste: place attributes (ownership, price, payment, star rating, dishes)
# and film-plot keywords ("friendship", "21st century"). Dropped by id prefix, so no per-brand list.
TRIVIAL_TAGS = (
    "urn:tag:inclusivity:",
    "urn:tag:cost_description:",
    "urn:tag:credit_card:",
    "urn:tag:hotel_rating:",
    "urn:tag:specialty_dish:",
    "urn:tag:keyword:media:",
)


def tag_family(tag_id: str) -> str:
    """The third URN segment of a Qloo tag id: urn:tag:genre:music:rock -> genre."""
    return tag_id.split(":")[2] if tag_id.count(":") >= 2 else ""


def bridges(a: list[Tag], b: list[Tag], families: Collection[str] | None = None) -> list[Bridge]:
    """Tags both brands have, strongest common affinity first, minus trivial ones and (when given) outside `families`.
    Feeds bridge_potential(), never score()."""
    theirs = {t.id: t.affinity for t in b}
    found = [
        Bridge(t.id, t.name, t.affinity, theirs[t.id])
        for t in a
        if t.id in theirs and not t.id.startswith(TRIVIAL_TAGS) and (families is None or tag_family(t.id) in families)
    ]
    found.sort(key=lambda x: (-min(x.affinity_acquirer, x.affinity_target), x.name.casefold(), x.id))
    return found[:TOP_N]


def bridge_potential(found: list[Bridge]) -> float:
    """0..100: each bridge counts its weaker audience's affinity (clamped to 0..1) and TOP_N perfect bridges make 100.
    Deterministic and separate from BCI and culture clash."""
    return round(100 * sum(_clamp(min(b.affinity_acquirer, b.affinity_target), 1.0) for b in found[:TOP_N]) / TOP_N, 1)


def _band(clash: float) -> str:
    return "low" if clash < LOW_BELOW else "medium" if clash < HIGH_FROM else "high"


def score(a: BrandProfile, b: BrandProfile) -> Scores:
    domains = sorted(d for d in a.insights.keys() | b.insights.keys() if a.insights.get(d) or b.insights.get(d))
    overlaps = {d: domain_overlap(a.insights.get(d, []), b.insights.get(d, [])) for d in domains}
    mean_overlap = sum(overlaps.values()) / len(overlaps) if overlaps else 0.0
    dist = demographic_distance(a.demographics, b.demographics)

    shared: list[SharedTaste] = []
    clash_a: list[ClashingTaste] = []
    clash_b: list[ClashingTaste] = []
    for d in domains:
        la, lb = a.insights.get(d, []), b.insights.get(d, [])
        wa, wb = _weights(la), _weights(lb)
        for x in la:
            if x.id in wb:
                if min(wa[x.id], wb[x.id]) > 0:
                    shared.append(SharedTaste(d, x.name, round(wa[x.id], 4), round(wb[x.id], 4)))
            elif wa[x.id] > 0:
                clash_a.append(ClashingTaste(d, x.name, round(wa[x.id], 4)))
        clash_b += [ClashingTaste(d, y.name, round(wb[y.id], 4)) for y in lb if y.id not in wa and wb[y.id] > 0]

    brands = {a.name.casefold(), b.name.casefold()}
    shared = _clean(shared, brands, lambda t: min(t.affinity_a, t.affinity_b))
    clash_a = _clean(clash_a, brands, lambda t: t.affinity)
    clash_b = _clean(clash_b, brands, lambda t: t.affinity)

    # Culture clash is NOT 100 - BCI: BCI counts shared mass (weighted Jaccard), clash counts the mass each
    # audience puts on entities the other lacks. Shared ids with unequal weights lower BCI but do not clash.
    mean_exclusive = sum(exclusive_mass(a.insights.get(d, []), b.insights.get(d, [])) for d in domains) / len(domains) if domains else 0.0
    clash = round(100 * _clamp(CLASH_TASTE_WEIGHT * mean_exclusive + DEMO_WEIGHT * dist, 1.0), 1)
    bci = round(100 * _clamp(OVERLAP_WEIGHT * mean_overlap + DEMO_WEIGHT * (1 - dist), 1.0), 1)
    return Scores(
        bci=bci,
        culture_clash=clash,
        churn_risk=_band(clash),
        demographic_distance=round(dist, 4),
        domain_overlap={d: round(v, 4) for d, v in overlaps.items()},
        top_shared=tuple(shared[:TOP_N]),
        top_clashing_a=tuple(clash_a[:TOP_N]),
        top_clashing_b=tuple(clash_b[:TOP_N]),
    )
