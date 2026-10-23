from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.qloo import (
    DOMAINS,
    BrandNotFoundError,
    MissingKeyError,
    QlooAPIError,
    QlooClient,
    QlooParseError,
    parse_demographics,
    parse_insights,
    parse_search,
)
from api.tests.qloo_fake import BASE, BRAND_IDS, fixture_handler, make_client


@pytest.fixture
def calls() -> list[httpx.Request]:
    return []


@pytest.fixture
def qloo(tmp_path: Path, calls: list[httpx.Request]) -> QlooClient:
    return make_client(tmp_path, fixture_handler(calls))


@pytest.mark.parametrize("brand", ["Nike", "Patagonia"])
def test_search_finds_brand(qloo: QlooClient, brand: str) -> None:
    entity = qloo.search(brand)
    assert entity.name == brand
    assert entity.id in BRAND_IDS
    assert entity.popularity is not None and 0 < entity.popularity <= 1


@pytest.mark.parametrize("brand", ["nike", "patagonia"])
@pytest.mark.parametrize("domain", DOMAINS)
def test_insights_parse_entities_with_affinity(qloo: QlooClient, brand: str, domain: str) -> None:
    entity_id = next(i for i, s in BRAND_IDS.items() if s == brand)
    affinities = qloo.insights(entity_id, domain)
    assert len(affinities) >= 5
    for a in affinities:
        assert a.id and a.name
        assert isinstance(a.affinity, float)


def test_insights_sends_key_and_filter(qloo: QlooClient, calls: list[httpx.Request]) -> None:
    entity_id = next(iter(BRAND_IDS))
    qloo.insights(entity_id, "artist")
    req = calls[0]
    assert req.headers["x-api-key"] == "test-key"
    assert req.url.params["filter.type"] == "urn:entity:artist"
    assert req.url.params["signal.interests.entities"] == entity_id


def test_insights_rejects_unknown_domain(qloo: QlooClient) -> None:
    with pytest.raises(ValueError):
        qloo.insights("abc", "gadgets")


def test_demographics(qloo: QlooClient) -> None:
    entity_id = next(i for i, s in BRAND_IDS.items() if s == "nike")
    demo = qloo.demographics(entity_id)
    assert demo.age["24_and_younger"] == pytest.approx(0.29)
    assert demo.gender["male"] == pytest.approx(0.32)
    assert set(demo.gender) == {"female", "male"}


def test_cache_hit_skips_network(tmp_path: Path, calls: list[httpx.Request]) -> None:
    first = make_client(tmp_path, fixture_handler(calls))
    a = first.search("Nike")
    assert len(calls) == 1
    assert first.search("Nike") == a
    second = make_client(tmp_path, fixture_handler(calls))  # fresh client, same cache dir
    assert second.search("Nike") == a
    assert len(calls) == 1
    second.insights(a.id, "brand")
    second.insights(a.id, "brand")
    assert len(calls) == 2


def test_missing_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    with pytest.raises(MissingKeyError):
        QlooClient(cache_dir=tmp_path)


def test_key_read_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QLOO_API_KEY", "from-env")
    monkeypatch.setenv("QLOO_API_URL", BASE)
    calls: list[httpx.Request] = []
    http = httpx.Client(transport=httpx.MockTransport(fixture_handler(calls)))
    QlooClient(cache_dir=tmp_path, http=http).search("Nike")
    assert calls[0].headers["x-api-key"] == "from-env"
    assert str(calls[0].url).startswith(BASE)


def test_empty_search_names_the_brand(qloo: QlooClient) -> None:
    with pytest.raises(BrandNotFoundError, match="Zorblax"):
        qloo.search("Zorblax")


def test_http_500_is_api_error(tmp_path: Path) -> None:
    client = make_client(tmp_path, lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(QlooAPIError):
        client.search("Nike")


def test_timeout_is_api_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(QlooAPIError):
        make_client(tmp_path, handler).search("Nike")


def test_rate_limit_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, calls: list[httpx.Request]
) -> None:
    naps: list[float] = []
    monkeypatch.setattr("api.qloo.time.sleep", naps.append)
    ok = fixture_handler(calls)
    state = {"left": 2}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["left"]:
            state["left"] -= 1
            return httpx.Response(429)
        return ok(request)

    assert make_client(tmp_path, handler).search("Nike").name == "Nike"
    assert len(naps) == 2


def test_rate_limit_gives_up_as_api_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("api.qloo.time.sleep", lambda s: None)
    with pytest.raises(QlooAPIError, match="429"):
        make_client(tmp_path, lambda r: httpx.Response(429)).search("Nike")


def test_failures_are_not_cached(tmp_path: Path, calls: list[httpx.Request]) -> None:
    ok = fixture_handler(calls)
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500)
        return ok(request)

    client = make_client(tmp_path, handler)
    with pytest.raises(QlooAPIError):
        client.search("Nike")
    state["fail"] = False
    assert client.search("Nike").name == "Nike"
    assert len(calls) == 1


def test_bad_json_and_bad_shape_are_parse_errors_and_not_cached(tmp_path: Path) -> None:
    bodies = [httpx.Response(200, text="<html>"), httpx.Response(200, json={"oops": 1})]
    client = make_client(tmp_path, lambda r: bodies.pop(0))
    with pytest.raises(QlooParseError):
        client.search("Nike")
    with pytest.raises(QlooParseError):
        client.search("Nike")
    assert not list(tmp_path.glob("*.json"))


# Fuzz: anything goes in, only a result or QlooParseError comes out.
KEYS = st.sampled_from(
    ["results", "entities", "demographics", "entity_id", "name", "popularity", "query",
     "affinity", "age", "gender", "x"]
)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(KEYS, children, max_size=5),
    max_leaves=25,
)


@pytest.mark.parametrize("parser", [parse_search, parse_insights, parse_demographics])
@given(payload=JSON)
def test_parsers_only_raise_parse_error(parser: Callable[[object], object], payload: object) -> None:
    try:
        parser(payload)
    except QlooParseError:
        pass


ITEM = st.dictionaries(KEYS, JSON | st.dictionaries(KEYS, JSON, max_size=3), max_size=5)
RESULTS = (
    st.dictionaries(KEYS, JSON, max_size=3)
    | st.lists(ITEM, max_size=3)
    | st.fixed_dictionaries(
        {"entities": st.lists(ITEM, max_size=3), "demographics": st.lists(ITEM, max_size=2)}
    )
)


@pytest.mark.parametrize("parser", [parse_search, parse_insights, parse_demographics])
@given(payload=st.fixed_dictionaries({"results": RESULTS}))
def test_parsers_survive_partial_results(
    parser: Callable[[object], object], payload: object
) -> None:
    try:
        parser(payload)
    except QlooParseError:
        pass
