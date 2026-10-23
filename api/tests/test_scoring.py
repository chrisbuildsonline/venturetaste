import json
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.qloo import DOMAINS, Affinity, Demographics, parse_demographics, parse_insights
from api.scoring import (
    BrandProfile,
    Scores,
    demographic_distance,
    domain_overlap,
    score,
)

FIXTURES = Path(__file__).parent / "fixtures"


def aff(id: str, a: float) -> Affinity:
    return Affinity(id=id, name=f"name-{id}", affinity=a, popularity=None)


def demo(age: float, gender: float) -> Demographics:
    return Demographics(
        age={"24_and_younger": age, "55_and_older": age},
        gender={"female": gender, "male": gender},
    )


def load_profile(slug: str, name: str) -> BrandProfile:
    def load(file: str) -> object:
        return json.loads((FIXTURES / f"{file}.json").read_text())

    return BrandProfile(
        name=name,
        insights={d: parse_insights(load(f"insights_{slug}_{d}")) for d in DOMAINS},
        demographics=parse_demographics(load(f"demographics_{slug}")),
    )


# ---- unit ----


def test_same_brand_twice() -> None:
    p = BrandProfile(
        "X",
        {"brand": [aff("1", 0.8), aff("2", 0.4)], "movie": [aff("3", 0.5)], "book": []},
        demo(0.3, -0.2),
    )
    s = score(p, p)
    assert s.domain_overlap == {"brand": 1.0, "movie": 1.0}
    assert s.culture_clash == 0
    assert s.churn_risk == "low"
    assert s.bci == 100


def test_disjoint_tastes_and_opposite_demographics() -> None:
    a = BrandProfile("A", {"brand": [aff("1", 0.9)], "movie": [aff("2", 0.9)]}, demo(1, 1))
    b = BrandProfile("B", {"brand": [aff("3", 0.9)], "movie": [aff("4", 0.9)]}, demo(-1, -1))
    s = score(a, b)
    assert s.culture_clash >= 95
    assert s.churn_risk == "high"
    assert s.bci <= 5
    assert s.top_shared == ()
    assert len(s.top_clashing_a) == 2 and len(s.top_clashing_b) == 2


def test_both_empty_does_not_divide_by_zero() -> None:
    assert domain_overlap([], []) == 0
    assert demographic_distance(Demographics({}, {}), Demographics({}, {})) == 0
    empty = BrandProfile("E", {}, Demographics({}, {}))
    s = score(empty, empty)
    assert s.domain_overlap == {}
    assert s.top_shared == ()
    assert all(math.isfinite(x) for x in (s.bci, s.culture_clash, s.demographic_distance))


def test_weighted_jaccard_value() -> None:
    # ids 1: min .5 / max 1.0; id 2: 0 / .5 ; negative clamps to 0 -> union {1,2,3}
    a = [aff("1", 0.5), aff("2", 0.0), aff("3", -0.7)]
    b = [aff("1", 1.0), aff("2", 0.5)]
    assert domain_overlap(a, b) == pytest.approx(0.5 / 1.5, abs=1e-4)


def test_domain_present_for_one_brand_only() -> None:
    a = BrandProfile("A", {"brand": [aff("1", 0.5)], "book": [aff("9", 0.5)]}, demo(0, 0))
    b = BrandProfile("B", {"brand": [aff("1", 0.5)]}, demo(0, 0))
    s = score(a, b)
    assert s.domain_overlap == {"brand": 1.0, "book": 0.0}
    assert [t.domain for t in s.top_clashing_a] == ["book"]
    assert s.top_clashing_b == ()


def test_missing_demographic_keys_count_as_zero() -> None:
    a = Demographics({"x": 1.0}, {})
    b = Demographics({}, {"y": -1.0})
    assert demographic_distance(a, b) == pytest.approx(0.5)


def test_bands() -> None:
    def band(overlap_ids: int) -> str:
        shared = [aff(str(i), 1.0) for i in range(overlap_ids)]
        a = BrandProfile("A", {"brand": shared + [aff("a", 1.0)] * (10 - overlap_ids)}, demo(0, 0))
        b = BrandProfile("B", {"brand": shared + [aff("b", 1.0)] * (10 - overlap_ids)}, demo(0, 0))
        return score(a, b).churn_risk

    assert band(10) == "low"
    assert band(0) == "high"


def test_top_lists_capped_and_ordered() -> None:
    ids = [str(i) for i in range(8)]
    a = BrandProfile("A", {"brand": [aff(i, 0.1 * (int(i) + 1)) for i in ids]}, demo(0, 0))
    b = BrandProfile("B", {"brand": [aff(i, 0.9) for i in ids[:7]] + [aff("z", 0.5)]}, demo(0, 0))
    s = score(a, b)
    assert len(s.top_shared) == 5
    mins = [min(t.affinity_a, t.affinity_b) for t in s.top_shared]
    assert mins == sorted(mins, reverse=True)
    assert [t.name for t in s.top_clashing_a] == ["name-7"]
    assert [t.name for t in s.top_clashing_b] == ["name-z"]


def named(id: str, name: str, a: float) -> Affinity:
    return Affinity(id=id, name=name, affinity=a, popularity=None)


def test_brands_themselves_are_left_out_of_every_list() -> None:
    a = BrandProfile(
        "Nike", {"brand": [named("1", "Adidas", 0.9), named("2", "nike", 0.8), named("3", "Puma", 0.7)]}, demo(0, 0)
    )
    b = BrandProfile(
        "Adidas", {"brand": [named("1", "Adidas", 0.9), named("2", "Nike", 0.8), named("4", "Reebok", 0.6)]}, demo(0, 0)
    )
    s = score(a, b)
    assert s.top_shared == ()
    assert [t.name for t in s.top_clashing_a] == ["Puma"]
    assert [t.name for t in s.top_clashing_b] == ["Reebok"]


def test_duplicate_names_keep_the_highest_affinity() -> None:
    a = BrandProfile(
        "A",
        {"place": [named("1", "Rio de Janeiro", 0.4), named("2", "rio de janeiro", 0.9), named("3", "Lima", 0.5)]},
        demo(0, 0),
    )
    b = BrandProfile(
        "B", {"place": [named("7", "Oslo", 0.5), named("8", "Oslo", 0.2), named("9", "Lima", 0.3)]}, demo(0, 0)
    )
    s = score(a, b)
    assert [(t.name, t.affinity) for t in s.top_clashing_a] == [("rio de janeiro", 0.9), ("Lima", 0.5)]
    assert [(t.name, t.affinity) for t in s.top_clashing_b] == [("Oslo", 0.5), ("Lima", 0.3)]


# ---- property ----

NAMES = st.sampled_from(["P", "p", "Q", "x", "X", "y"])
NAMED_AFFS = st.lists(
    st.builds(named, st.sampled_from(list("abcdefgh")), NAMES, st.floats(-1, 1, allow_nan=False)),
    max_size=8,
)
NAMED_PROFILES = st.builds(
    BrandProfile,
    st.sampled_from(["P", "Q"]),
    st.dictionaries(st.sampled_from(DOMAINS), NAMED_AFFS, max_size=7),
    st.just(Demographics({}, {})),
)


@given(a=NAMED_PROFILES, b=NAMED_PROFILES)
def test_lists_have_no_duplicates_or_brand_self_reference(a: BrandProfile, b: BrandProfile) -> None:
    s = score(a, b)
    brands = {a.name.casefold(), b.name.casefold()}
    for items in (s.top_shared, s.top_clashing_a, s.top_clashing_b):
        keys = [(t.domain, t.name.casefold()) for t in items]
        assert len(keys) == len(set(keys))
        assert not brands & {name for _, name in keys}

FINITE = st.floats(min_value=-1, max_value=1, allow_nan=False)
AFFS = st.lists(
    st.builds(aff, st.sampled_from(list("abcdefgh")), st.floats(-1, 1, allow_nan=False)),
    max_size=8,
)
DEMOS = st.builds(
    Demographics,
    st.dictionaries(st.sampled_from(["a1", "a2", "a3"]), FINITE, max_size=3),
    st.dictionaries(st.sampled_from(["female", "male"]), FINITE, max_size=2),
)
PROFILES = st.builds(
    BrandProfile,
    st.just("P"),
    st.dictionaries(st.sampled_from(DOMAINS), AFFS, max_size=7),
    DEMOS,
)


def all_numbers(s: Scores) -> list[float]:
    nums = [s.bci, s.culture_clash, s.demographic_distance, *s.domain_overlap.values()]
    for t in s.top_shared:
        nums += [t.affinity_a, t.affinity_b]
    for c in (*s.top_clashing_a, *s.top_clashing_b):
        nums.append(c.affinity)
    return nums


@given(a=PROFILES, b=PROFILES)
def test_scores_bounded_and_finite(a: BrandProfile, b: BrandProfile) -> None:
    s = score(a, b)
    assert all(math.isfinite(x) for x in all_numbers(s))
    assert 0 <= s.bci <= 100
    assert 0 <= s.culture_clash <= 100
    assert 0 <= s.demographic_distance <= 1
    assert all(0 <= v <= 1 for v in s.domain_overlap.values())
    assert s.churn_risk in ("low", "medium", "high")
    assert len(s.top_shared) <= 5 and len(s.top_clashing_a) <= 5 and len(s.top_clashing_b) <= 5


@given(a=PROFILES, b=PROFILES)
def test_deterministic(a: BrandProfile, b: BrandProfile) -> None:
    assert score(a, b) == score(a, b)


@given(a=AFFS, b=AFFS)
def test_overlap_symmetric(a: list[Affinity], b: list[Affinity]) -> None:
    assert domain_overlap(a, b) == domain_overlap(b, a)


@given(a=DEMOS, b=DEMOS)
def test_demographic_distance_symmetric(a: Demographics, b: Demographics) -> None:
    assert demographic_distance(a, b) == demographic_distance(b, a)


@given(p=PROFILES)
def test_same_brand_never_clashes_more_than_nothing_shared(p: BrandProfile) -> None:
    s = score(p, p)
    assert all(v in (0.0, 1.0) for v in s.domain_overlap.values())
    assert s.demographic_distance == 0


# ---- real data ----


def test_nike_vs_patagonia() -> None:
    nike = load_profile("nike", "Nike")
    pata = load_profile("patagonia", "Patagonia")
    s = score(nike, pata)
    assert all(math.isfinite(x) for x in all_numbers(s))
    assert 0 <= s.bci <= 100 and 0 <= s.culture_clash <= 100
    assert set(s.domain_overlap) <= set(DOMAINS)
    assert (s.bci, s.culture_clash, s.churn_risk) == (24.5, 75.5, "high")  # snapshot
    # at take=50 the two brands share only one brand entity
    assert s.domain_overlap == {**dict.fromkeys(DOMAINS, 0.0), "brand": 0.0099}
    assert s.demographic_distance == 0.1881
    assert [(t.domain, t.name) for t in s.top_shared] == [("brand", "GoPro")]

    nike_names = {a.name for d in DOMAINS for a in nike.insights[d]}
    pata_names = {a.name for d in DOMAINS for a in pata.insights[d]}
    assert all(c.name in nike_names for c in s.top_clashing_a)
    assert all(c.name in pata_names for c in s.top_clashing_b)
    assert s.top_clashing_a and s.top_clashing_b
    # swapping brands keeps the symmetric numbers
    r = score(pata, nike)
    assert r.domain_overlap == s.domain_overlap
    assert r.demographic_distance == s.demographic_distance
