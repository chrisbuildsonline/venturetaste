import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api import main
from api.fixtures import fixture_handler, make_client
from api.main import app, get_qloo
from api.presets import SCREENS

NIKE = SCREENS[0]
BODY = {"acquirer": NIKE.acquirer, "targets": list(NIKE.targets)}
TRUSTED = "127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"  # keep in step with the Dockerfile


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_RATE_LIMIT", "2")
    main.reset_rate_limit()


@pytest.fixture(autouse=True)
def fixtures_backend(tmp_path: Path) -> Iterator[None]:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def api() -> TestClient:
    return TestClient(app)  # client host is "testclient": not loopback, so it is limited


def test_screen_returns_ok_rows_in_input_order(api: TestClient) -> None:
    res = api.post("/api/screen", json=BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["acquirer"] == NIKE.acquirer
    assert [r["target"] for r in body["rows"]] == list(NIKE.targets)
    for row in body["rows"]:
        assert row["ok"] is True
        assert isinstance(row["bci"], (int, float)) and isinstance(row["clash"], (int, float))
        assert row["churn"] and row["verdict"] in {"Proceed", "Proceed with conditions", "Pass"}


def test_screen_row_matches_the_diligence_result(api: TestClient) -> None:
    row = api.post("/api/screen", json=BODY).json()["rows"][0]
    full = api.post("/api/diligence", json={"acquirer": NIKE.acquirer, "target": row["target"]}).json()
    assert row["bci"] == full["scores"]["bci"]
    assert row["clash"] == full["scores"]["culture_clash"]
    assert row["churn"] == full["scores"]["churn_risk"]
    assert row["verdict"] == full["memo"]["verdict"]


def test_a_screen_costs_one_hit_and_the_third_is_429(api: TestClient) -> None:
    five = {"acquirer": NIKE.acquirer, "targets": ["Adidas", "Puma", "Gucci", "Lululemon", "Patagonia"]}
    assert api.post("/api/screen", json=five).status_code == 200
    assert api.post("/api/screen", json=five).status_code == 200
    res = api.post("/api/screen", json=five)
    assert res.status_code == 429
    assert 1 <= int(res.headers["retry-after"]) <= 60


def test_one_bad_target_becomes_an_error_row(api: TestClient) -> None:
    res = api.post("/api/screen", json={"acquirer": "Nike", "targets": ["Adidas", "Zzqx Nonbrand", "Puma"]})
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert [r["target"] for r in rows] == ["Adidas", "Zzqx Nonbrand", "Puma"]
    assert [r["ok"] for r in rows] == [True, False, True]
    assert rows[1]["status"] == 422 and "Qloo has no brand named" in rows[1]["detail"]


def test_a_surprise_exception_is_a_clean_error_row(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(client: Any, body: Any) -> dict[str, Any]:
        raise RuntimeError("secret internal text")

    monkeypatch.setattr(main, "run_result", boom)
    rows = api.post("/api/screen", json=BODY).json()["rows"]
    assert all(r["ok"] is False and r["status"] == 502 for r in rows)
    assert "secret internal text" not in str(rows)


def test_missing_key_still_replays_recorded_pairs(api: TestClient) -> None:
    app.dependency_overrides[get_qloo] = lambda: None
    rows = api.post("/api/screen", json=BODY).json()["rows"]
    assert all(r["ok"] for r in rows)
    assert all(r["recorded"] for r in rows)
    rows = api.post("/api/screen", json={"acquirer": "Nike", "targets": ["Adidas", "Zzqx Nonbrand"]}).json()["rows"]
    assert rows[0]["ok"] is True
    assert rows[1]["ok"] is False and rows[1]["status"] == 503


@pytest.mark.parametrize(
    "targets",
    [["Adidas"], ["a", "b", "c", "d", "e", "f"], ["Adidas", "adidas", " ADIDAS "], ["Adidas", "Nike", "nike"], ["Adidas", "", "  "]],
    ids=["one", "six", "duplicates", "acquirer-excluded", "blanks"],
)
def test_target_count_is_2_to_5_after_cleaning(api: TestClient, targets: list[str]) -> None:
    assert api.post("/api/screen", json={"acquirer": "Nike", "targets": targets}).status_code == 422


def test_blanks_and_duplicates_are_dropped_before_counting(api: TestClient) -> None:
    res = api.post("/api/screen", json={"acquirer": "Nike", "targets": ["Adidas", "", "adidas", "Puma", "NIKE"]})
    assert res.status_code == 200
    assert [r["target"] for r in res.json()["rows"]] == ["Adidas", "Puma"]


def test_targets_run_concurrently(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def slow(client: Any, body: Any) -> dict[str, Any]:
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.2)
        with lock:
            state["now"] -= 1
        return {"scores": {"bci": 1, "culture_clash": 1, "churn_risk": "low"}, "memo": {"verdict": "Pass"}}

    monkeypatch.setattr(main, "run_result", slow)
    assert api.post("/api/screen", json=BODY).status_code == 200
    assert 1 < state["peak"] <= 3


def test_loopback_clients_are_not_limited() -> None:
    for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        local = TestClient(app, client=(host, 5000))
        assert [local.post("/api/screen", json=BODY).status_code for _ in range(4)] == [200] * 4, host


def test_a_spoofed_loopback_forwarded_for_is_not_exempt() -> None:
    wrapped: Any = ProxyHeadersMiddleware(cast(Any, app), trusted_hosts=TRUSTED)
    proxied = TestClient(wrapped, client=("172.18.0.2", 4000))
    for forwarded in ("127.0.0.1", "127.0.0.1", "::1", "127.0.0.1, 127.0.0.1"):
        assert proxied.post("/api/screen", json=BODY, headers={"X-Forwarded-For": forwarded}).status_code in (200, 429)
    assert proxied.post("/api/screen", json=BODY, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 429
