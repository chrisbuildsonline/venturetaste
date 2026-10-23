"""Pure scoring of two brands from their Qloo taste profiles (no I/O, no LLM)."""

import math
from dataclasses import dataclass

from api.qloo import Affinity, Demographics

# Blend: taste overlap counts 70%, audience demographics 30%.
OVERLAP_WEIGHT, DEMO_WEIGHT = 0.7, 0.3
TOP_N = 5


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


def _band(clash: float) -> str:
    return "low" if clash < 33 else "medium" if clash < 66 else "high"


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

    shared = list({(t.domain, t.name): t for t in shared}.values())
    shared.sort(key=lambda t: (-min(t.affinity_a, t.affinity_b), t.domain, t.name))
    clash_a = list(dict.fromkeys(clash_a))
    clash_b = list(dict.fromkeys(clash_b))
    clash_a.sort(key=lambda t: (-t.affinity, t.domain, t.name))
    clash_b.sort(key=lambda t: (-t.affinity, t.domain, t.name))

    clash = round(100 * _clamp(OVERLAP_WEIGHT * (1 - mean_overlap) + DEMO_WEIGHT * dist, 1.0), 1)
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
