import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api import main
from api.main import app, get_qloo
from api.tests.qloo_fake import fixture_handler, make_client

BODY = {"acquirer": "Nike", "target": "Adidas"}
PATHS = ["/api/diligence", "/api/diligence/stream"]


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_RATE_LIMIT", "3")
    main.reset_rate_limit()


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", PATHS)
def test_429_after_limit_with_retry_after(api: TestClient, path: str) -> None:
    for _ in range(3):
        assert api.post(path, json=BODY).status_code == 200
    res = api.post(path, json=BODY)
    assert res.status_code == 429
    assert "text/event-stream" not in res.headers["content-type"]
    assert "Too many" in res.json()["detail"]
    assert 1 <= int(res.headers["retry-after"]) <= 60


def test_limit_is_shared_by_both_endpoints(api: TestClient) -> None:
    for _ in range(3):
        api.post("/api/diligence", json=BODY)
    assert api.post("/api/diligence/stream", json=BODY).status_code == 429


def test_other_ip_is_not_limited(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    try:
        a = TestClient(app, client=("1.1.1.1", 5000))
        b = TestClient(app, client=("2.2.2.2", 5000))
        for _ in range(3):
            a.post("/api/diligence", json=BODY)
        assert a.post("/api/diligence", json=BODY).status_code == 429
        assert b.post("/api/diligence", json=BODY).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_ipv6_keyed_by_64_and_mapped_ipv4_by_ipv4(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    try:

        def post(host: str) -> int:
            return TestClient(app, client=(host, 5000)).post("/api/diligence", json=BODY).status_code

        for i in range(3):
            assert post(f"2001:db8:1:2::{i + 1}") == 200  # same /64, different addresses
        assert post("2001:db8:1:2:ffff::9") == 429
        assert post("2001:db8:1:3::1") == 200  # different /64
        for _ in range(3):
            assert post("1.2.3.4") == 200
        assert post("::ffff:1.2.3.4") == 429  # same client as 1.2.3.4
    finally:
        app.dependency_overrides.clear()


TRUSTED ="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"  # keep in step with the Dockerfile


def test_limit_is_per_real_client_behind_a_trusted_proxy(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    try:
        wrapped: Any = ProxyHeadersMiddleware(cast(Any, app), trusted_hosts=TRUSTED)  # uvicorn and starlette ASGI types differ
        proxied = TestClient(wrapped, client=("172.18.0.2", 4000))

        def post(forwarded: str) -> int:
            return proxied.post("/api/diligence", json=BODY, headers={"X-Forwarded-For": forwarded}).status_code

        for i in range(3):
            assert post(f"spoof{i}, 8.8.8.8") == 200  # a new leftmost value each time must not reset the limit
        assert post("another-spoof, 8.8.8.8") == 429
        assert post("6.6.6.6, 9.9.9.9") == 200  # a different real client has its own limit
    finally:
        app.dependency_overrides.clear()


def test_window_expires(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(main, "_clock", lambda: now[0])
    for _ in range(3):
        api.post("/api/diligence", json=BODY)
    assert api.post("/api/diligence", json=BODY).status_code == 429
    now[0] += 61
    assert api.post("/api/diligence", json=BODY).status_code == 200


def test_default_limit_is_30(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTURETASTE_RATE_LIMIT")
    codes = [api.post("/api/diligence", json={"acquirer": "", "target": ""}).status_code for _ in range(31)]
    assert codes[:30] == [422] * 30 and codes[30] == 429


def test_cache_cap_prunes_oldest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_CACHE_MAX_FILES", "3")
    for i in range(5):
        old = tmp_path / f"old{i}.json"
        old.write_text("{}")
        os.utime(old, (1000 + i, 1000 + i))
    client = make_client(tmp_path, fixture_handler([]))
    client.search("Nike")
    names = {p.name for p in tmp_path.glob("*.json")}
    assert len(names) == 3
    assert {"old3.json", "old4.json"} <= names  # the two newest old files and the fresh write survive
