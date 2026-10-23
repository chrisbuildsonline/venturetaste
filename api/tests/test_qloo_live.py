"""Hits the real Qloo API. Run with: bun run test:live"""

from pathlib import Path

import httpx
import pytest

from api.qloo import DOMAINS, QlooClient

pytestmark = pytest.mark.live


@pytest.fixture
def requests_made() -> list[httpx.Request]:
    return []


@pytest.fixture
def qloo(tmp_path: Path, requests_made: list[httpx.Request]) -> QlooClient:
    http = httpx.Client(timeout=30, event_hooks={"request": [requests_made.append]})
    return QlooClient(cache_dir=tmp_path, http=http)


@pytest.mark.parametrize("brand", ["Nike", "Patagonia"])
def test_live_search(qloo: QlooClient, brand: str) -> None:
    entity = qloo.search(brand)
    assert entity.name == brand
    assert entity.id


def test_live_insights_cover_most_domains(qloo: QlooClient) -> None:
    nike = qloo.search("Nike")
    working = [d for d in DOMAINS if len(qloo.insights(nike.id, d)) >= 5]
    assert len(working) >= 4, working
    for domain in working:
        assert all(isinstance(a.affinity, float) for a in qloo.insights(nike.id, domain))


def test_live_demographics(qloo: QlooClient) -> None:
    demo = qloo.demographics(qloo.search("Nike").id)
    assert demo.age and demo.gender


def test_live_second_call_is_cache_hit(qloo: QlooClient, requests_made: list[httpx.Request]) -> None:
    qloo.search("Patagonia")
    assert len(requests_made) == 1
    qloo.search("Patagonia")
    assert len(requests_made) == 1
