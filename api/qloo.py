"""Small typed client for the Qloo hackathon API (taste affinities)."""

import hashlib
import json
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://hackathon.api.qloo.com"
DEFAULT_CACHE_DIR = Path(".cache/qloo")
DOMAINS = ("brand", "artist", "movie", "tv_show", "place", "destination", "book")
DEFAULT_TAKE = 50  # Qloo rejects take > 50 with HTTP 400
RETRY_DELAYS = (0.5, 1.0, 2.0, 4.0)  # seconds to wait after an HTTP 429

T = TypeVar("T")


class QlooError(Exception):
    pass


class MissingKeyError(QlooError):
    pass


class BrandNotFoundError(QlooError):
    pass


class QlooAPIError(QlooError):
    pass


class QlooParseError(QlooError):
    pass


@dataclass(frozen=True)
class Entity:
    id: str
    name: str
    popularity: float | None


@dataclass(frozen=True)
class Affinity:
    id: str
    name: str
    affinity: float
    popularity: float | None


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    affinity: float


@dataclass(frozen=True)
class Demographics:
    age: dict[str, float]  # e.g. "24_and_younger" -> affinity in -1..1
    gender: dict[str, float]  # "female" / "male" -> affinity


def _obj(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise QlooParseError(f"expected object for {what}")
    return value


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise QlooParseError(f"expected list for {what}")
    return value


def _str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise QlooParseError(f"expected non-empty string for {what}")
    return value


def _num(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise QlooParseError(f"expected number for {what}")
    try:
        number = float(value)
    except OverflowError:
        raise QlooParseError(f"number out of range for {what}") from None
    if not math.isfinite(number):
        raise QlooParseError(f"non-finite number for {what}")
    return number


def _opt_num(value: object, what: str) -> float | None:
    return None if value is None else _num(value, what)


def parse_search(payload: object) -> list[Entity]:
    items = _list(_obj(payload, "search response").get("results"), "results")
    entities = []
    for raw in items:
        item = _obj(raw, "search result")
        entities.append(
            Entity(
                id=_str(item.get("entity_id"), "entity_id"),
                name=_str(item.get("name"), "name"),
                popularity=_opt_num(item.get("popularity"), "popularity"),
            )
        )
    return entities


def parse_insights(payload: object) -> list[Affinity]:
    results = _obj(_obj(payload, "insights response").get("results"), "results")
    affinities = []
    for raw in _list(results.get("entities"), "entities"):
        item = _obj(raw, "entity")
        query = _obj(item.get("query"), "entity query")
        affinities.append(
            Affinity(
                id=_str(item.get("entity_id"), "entity_id"),
                name=_str(item.get("name"), "name"),
                affinity=_num(query.get("affinity"), "affinity"),
                popularity=_opt_num(item.get("popularity"), "popularity"),
            )
        )
    return affinities


def parse_tags(payload: object) -> list[Tag]:
    results = _obj(_obj(payload, "tags response").get("results"), "results")
    tags = []
    for raw in _list(results.get("tags"), "tags"):
        item = _obj(raw, "tag")
        query = _obj(item.get("query"), "tag query")
        tags.append(
            Tag(
                id=_str(item.get("tag_id"), "tag_id"),
                name=_str(_str(item.get("name"), "name").strip(), "name"),
                affinity=_num(query.get("affinity"), "affinity"),
            )
        )
    return tags


def _scores(value: object, what: str) -> dict[str, float]:
    return {key: _num(score, f"{what}.{key}") for key, score in _obj(value, what).items()}


def parse_demographics(payload: object) -> Demographics:
    results = _obj(_obj(payload, "demographics response").get("results"), "results")
    rows = _list(results.get("demographics"), "demographics")
    if not rows:
        raise QlooParseError("no demographics returned")
    query = _obj(_obj(rows[0], "demographics row").get("query"), "demographics query")
    return Demographics(age=_scores(query.get("age"), "age"), gender=_scores(query.get("gender"), "gender"))


def normalize_base_url(value: str | None) -> str:
    """The base URL to call: a valid http(s) URL without a trailing slash, else DEFAULT_URL (with a warning)."""
    if not value or not value.strip():
        return DEFAULT_URL
    parts = urlsplit(value.strip())
    if parts.scheme in ("http", "https") and parts.hostname:
        return value.strip().rstrip("/")
    logger.warning("QLOO_API_URL %r is not an http(s) URL with a host; using %s", value, DEFAULT_URL)
    return DEFAULT_URL


class QlooClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        http: httpx.Client | None = None,
    ) -> None:
        self._key = api_key or os.environ.get("QLOO_API_KEY")
        if not self._key:
            raise MissingKeyError("QLOO_API_KEY is not set")
        self._base = normalize_base_url(base_url or os.environ.get("QLOO_API_URL"))
        self._cache_dir = cache_dir
        self._http = http or httpx.Client(timeout=30)

    def search(self, name: str) -> Entity:
        found = self._get("/search", {"query": name, "types": "urn:entity:brand"}, parse_search)
        if not found:
            raise BrandNotFoundError(f"Qloo has no brand named {name!r}")
        return next((e for e in found if e.name.casefold() == name.casefold()), found[0])

    def insights(self, entity_id: str, domain: str, take: int = DEFAULT_TAKE) -> list[Affinity]:
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}, expected one of {DOMAINS}")
        params = {
            "filter.type": f"urn:entity:{domain}",
            "signal.interests.entities": entity_id,
            "take": str(take),
        }
        return self._get("/v2/insights", params, parse_insights)

    def demographics(self, entity_id: str) -> Demographics:
        params = {"filter.type": "urn:demographics", "signal.interests.entities": entity_id}
        return self._get("/v2/insights", params, parse_demographics)

    def tags(self, entity_id: str, take: int = DEFAULT_TAKE) -> list[Tag]:
        params = {"filter.type": "urn:tag", "signal.interests.entities": entity_id, "take": str(take)}
        return self._get("/v2/insights", params, parse_tags)

    def _get(self, path: str, params: dict[str, str], parse: Callable[[object], T]) -> T:
        cache_file = self._cache_dir / (
            hashlib.sha256(json.dumps([path, sorted(params.items())]).encode()).hexdigest() + ".json"
        )
        cached = self._read_cache(cache_file)
        if cached is not None:
            try:
                return parse(cached)
            except QlooParseError:
                pass  # stale or corrupt cache entry: refetch
        raw = self._fetch(path, params)
        parsed = parse(raw)  # only well-formed successful responses reach the cache
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(raw))
        self._prune_cache()
        return parsed

    def _prune_cache(self) -> None:
        """Keep the cache dir to VENTURETASTE_CACHE_MAX_FILES files by deleting the oldest."""
        cap = int(os.environ.get("VENTURETASTE_CACHE_MAX_FILES") or 2000)
        try:
            files = [(p.stat().st_mtime, p) for p in self._cache_dir.glob("*.json")]
            for _, old in sorted(files, key=lambda f: f[0])[: max(0, len(files) - cap)]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # a concurrent run raced us on a file; the next write prunes again

    def _fetch(self, path: str, params: dict[str, str]) -> object:
        for delay in (*RETRY_DELAYS, None):
            try:
                resp = self._http.get(
                    self._base + path, params=params, headers={"X-Api-Key": str(self._key)}
                )
            except httpx.HTTPError as exc:
                raise QlooAPIError(f"Qloo request to {path} failed: {exc!r}") from exc
            if resp.status_code != 429 or delay is None:
                break
            time.sleep(delay)
        if not resp.is_success:
            raise QlooAPIError(f"Qloo {path} returned HTTP {resp.status_code}")
        try:
            data: object = resp.json()
        except ValueError as exc:
            raise QlooParseError(f"Qloo {path} returned invalid JSON") from exc
        return data

    @staticmethod
    def _read_cache(cache_file: Path) -> object | None:
        try:
            data: object = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            return None
        return data
