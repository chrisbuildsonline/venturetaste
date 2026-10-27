"""Find acquisition targets: the acquirer's Qloo brand affinities, ranked by how close their category is."""

from typing import Any

from api.presets import slug
from api.qloo import Affinity, Entity, QlooClient, TagRef

MAX_CANDIDATES = 5  # keep in step with MAX_TARGETS in web/app/screen.ts
SOURCE = "Qloo consumer-brand affinities (urn:entity:brand)"
# Qloo's own brand_type tag. Everything else (Entertainment: clubs and leagues, Media, Nonprofit, or untagged) is no deal target.
BUYABLE_TYPES = {"Product Brand", "Corporate Brand", "Retail Brand", "Service Brand"}

# score = AFFINITY_WEIGHT * affinity + ADJACENCY_WEIGHT * adjacency, both 0..1 (see README, "Find targets")
AFFINITY_WEIGHT = 0.5
ADJACENCY_WEIGHT = 0.5
# Qloo tag families that say what a brand sells: industry, brand genre, product category.
CATEGORY_TAGS = ("urn:tag:industry:qloo", "urn:tag:genre:brand", "urn:tag:product_category:qloo")
SUBSIDIARY_TAG = "urn:tag:subsidiary:qloo"
MAX_SHARED_NAMED = 3
# Words that say "company" or "line", not which brand: "Jordan Brand" has to match "Air Jordan Product Line".
GENERIC_WORDS = {"brand", "brands", "product", "line", "lines", "inc", "company", "co", "corp", "corporation", "group", "the", "llc", "ltd"}


def _tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in slug(name).split("_") if w and w not in GENERIC_WORDS)


def same_brand(a: str, b: str) -> bool:
    """One name's distinctive words all appear in the other's ("Nike" / "Nike SB", "Jordan Brand" / "Air Jordan Product Line")."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta) and bool(tb) and (ta <= tb or tb <= ta)


def _subsidiaries(tags: tuple[TagRef, ...]) -> list[str]:
    return [name for kind, _, name in tags if kind.startswith(SUBSIDIARY_TAG)]


def _categories(tags: tuple[TagRef, ...]) -> dict[str, str]:
    """tag id -> display name, in Qloo's order, for the category families only."""
    return {tag_id: name for kind, tag_id, name in tags if kind.startswith(CATEGORY_TAGS)}


def _related(acquirer: Entity, a: Affinity) -> bool:
    """The candidate is the acquirer, part of it, or its parent."""
    return (
        a.id == acquirer.id
        or same_brand(acquirer.name, a.name)
        or any(same_brand(sub, a.name) for sub in _subsidiaries(acquirer.tags))
        or any(same_brand(sub, acquirer.name) for sub in _subsidiaries(a.tags))
    )


def _reason(shared_names: list[str], affinity: float) -> str:
    shared = f"Shares {', '.join(shared_names[:MAX_SHARED_NAMED])}" if shared_names else "No shared categories"
    return f"{shared} · affinity {affinity:.2f}"


def pick_candidates(acquirer: Entity, affinities: list[Affinity]) -> list[dict[str, Any]]:
    """Consumer brands only, minus the acquirer, its own lines, its parent and repeats; best blend of affinity and category overlap first, capped at MAX_CANDIDATES."""
    mine = _categories(acquirer.tags)
    seen: set[str] = set()
    scored: list[dict[str, Any]] = []
    for a in affinities:
        key = slug(a.name)
        # ponytail: token containment also drops unrelated brands that contain the acquirer's words; rare, and cheaper than a brand-tree lookup
        if not BUYABLE_TYPES.intersection(a.brand_types) or _related(acquirer, a) or key in seen:
            continue
        seen.add(key)
        theirs = _categories(a.tags)
        shared = mine.keys() & theirs.keys()
        adjacency = len(shared) / len(mine) if shared else 0.0  # share of the acquirer's categories the candidate covers
        names: dict[str, str] = {}  # dedupe by name: "Footwear" is both an industry and a genre
        for tag_id, name in mine.items():
            if tag_id in shared:
                names.setdefault(name.casefold(), name)
        scored.append(
            {
                "name": a.name,
                "affinity": a.affinity,
                "adjacency": round(adjacency, 4),
                "score": round(AFFINITY_WEIGHT * a.affinity + ADJACENCY_WEIGHT * adjacency, 4),
                "reason": _reason(list(names.values()), a.affinity),
            }
        )
    scored.sort(key=lambda c: -c["score"])  # stable: ties keep Qloo's order
    return scored[:MAX_CANDIDATES]


def discover(client: QlooClient, name: str) -> dict[str, Any]:
    acquirer = client.search(name)
    candidates = pick_candidates(acquirer, client.insights(acquirer.id, "brand"))
    return {"acquirer": acquirer.name, "candidates": candidates, "source": SOURCE}
