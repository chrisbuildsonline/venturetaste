"""Find acquisition targets: the acquirer's top brand affinities in Qloo's taste graph."""

from typing import Any

from api.presets import slug
from api.qloo import Affinity, Entity, QlooClient

MAX_CANDIDATES = 5  # keep in step with MAX_TARGETS in web/app/screen.ts
SOURCE = "Qloo consumer-brand affinities (urn:entity:brand)"
# Qloo's own brand_type tag. Everything else (Entertainment: clubs and leagues, Media, Nonprofit, or untagged) is no deal target.
BUYABLE_TYPES = {"Product Brand", "Corporate Brand", "Retail Brand", "Service Brand"}


def pick_candidates(acquirer: Entity, affinities: list[Affinity]) -> list[dict[str, Any]]:
    """Qloo's order, consumer brands only, minus the acquirer, its sub-brands ("Nike SB") and repeats, capped at MAX_CANDIDATES."""
    own = slug(acquirer.name)
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    for a in affinities:
        key = slug(a.name)
        # ponytail: a substring match also drops unrelated brands whose name contains the acquirer's; rare, and cheaper than a brand-tree lookup
        if not BUYABLE_TYPES.intersection(a.brand_types) or a.id == acquirer.id or (own and own in key) or key in seen:
            continue
        seen.add(key)
        picked.append({"name": a.name, "affinity": a.affinity})
    return picked[:MAX_CANDIDATES]


def discover(client: QlooClient, name: str) -> dict[str, Any]:
    acquirer = client.search(name)
    candidates = pick_candidates(acquirer, client.insights(acquirer.id, "brand"))
    return {"acquirer": acquirer.name, "candidates": candidates, "source": SOURCE}
