"""Demo brand pairs, verified live at take=50. Shared by the API, the UI and the fixture recorder."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    acquirer: str
    target: str
    kind: str  # "synergy" | "mixed" | "clash"


PRESETS = (
    Preset("nike-adidas", "Nike + Adidas", "Nike", "Adidas", "synergy"),
    Preset("patagonia-north-face", "Patagonia + The North Face", "Patagonia", "The North Face", "mixed"),
    Preset("patagonia-gucci", "Patagonia + Gucci", "Patagonia", "Gucci", "clash"),
)


@dataclass(frozen=True)
class Screen:
    id: str
    label: str
    acquirer: str
    targets: tuple[str, ...]


SCREENS = (Screen("nike-targets", "Nike: 4 targets", "Nike", ("Adidas", "Puma", "Lululemon", "Gucci")),)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def preset_brands() -> list[str]:
    deals = {b for p in PRESETS for b in (p.acquirer, p.target)}
    return sorted(deals | {b for s in SCREENS for b in (s.acquirer, *s.targets)})
