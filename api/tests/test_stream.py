import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_qloo
from api.pipeline import run_diligence, stream_diligence
from api.fixtures import fixture_handler, make_client

AGENTS = ["Scout", "Cartographer", "Analyst", "Partner"]


@pytest.fixture
def calls() -> list[httpx.Request]:
    return []


@pytest.fixture
def api(tmp_path: Path, calls: list[httpx.Request]) -> Iterator[TestClient]:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler(calls))
    yield TestClient(app)
    app.dependency_overrides.clear()


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_event_order_is_running_ok_pairs_then_result(tmp_path: Path) -> None:
    client = make_client(tmp_path, fixture_handler([]))
    events = list(stream_diligence(client, "Nike", "Adidas"))
    expected = []
    for name in AGENTS:
        expected += [("agent", name, "running"), ("agent", name, "ok")]
    got = [(e, d.get("agent"), d.get("status")) for e, d in events[:-1]]
    assert got == expected
    assert events[-1][0] == "result"
    ok = {d["agent"]: d for e, d in events if e == "agent" and d["status"] == "ok"}
    assert all(d["ms"] >= 0 for d in ok.values())
    assert [ok[a]["qloo_calls"] for a in AGENTS] == [2, 16, 0, 0]


def test_result_equals_run_diligence(tmp_path: Path) -> None:
    streamed = list(stream_diligence(make_client(tmp_path, fixture_handler([])), "Nike", "Adidas"))[-1][1]
    plain = run_diligence(make_client(tmp_path, fixture_handler([])), "Nike", "Adidas")
    for report in (streamed, plain):
        for t in report["trace"]:
            t["ms"] = 0
    assert streamed == plain


def test_stream_is_lazy(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    stream = stream_diligence(make_client(tmp_path, fixture_handler(calls)), "Nike", "Adidas")
    assert next(stream) == ("agent", {"agent": "Scout", "status": "running"})
    assert calls == []
    event, data = next(stream)
    assert (event, data["agent"], data["qloo_calls"]) == ("agent", "Scout", 2)
    assert next(stream) == ("agent", {"agent": "Cartographer", "status": "running"})
    assert len(calls) == 2  # Cartographer has not run yet


def test_error_event_for_unknown_brand(api: TestClient) -> None:
    res = api.post("/api/diligence/stream", json={"acquirer": "Nike", "target": "zzqx notabrand"})
    events = parse_sse(res.text)
    assert res.status_code == 200
    assert events[0] == ("agent", {"agent": "Scout", "status": "running"})
    kind, data = events[-1]
    assert kind == "error" and data["status"] == 422 and "zzqx notabrand" in data["detail"]
    assert len(events) == 2


def test_error_event_for_same_brand(api: TestClient) -> None:
    events = parse_sse(api.post("/api/diligence/stream", json={"acquirer": "Nike", "target": "nike"}).text)
    kind, data = events[-1]
    assert kind == "error" and data["status"] == 422 and "two different brands" in data["detail"]


def test_error_event_for_missing_key(tmp_path: Path) -> None:
    from api.qloo import MissingKeyError, QlooClient

    def no_key() -> QlooClient:
        raise MissingKeyError("QLOO_API_KEY is not set")

    app.dependency_overrides[get_qloo] = no_key
    try:
        res = TestClient(app).post("/api/diligence/stream", json={"acquirer": "Nike", "target": "Adidas"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 503  # dependency fails before streaming starts


def test_endpoint_streams_sse(api: TestClient) -> None:
    res = api.post("/api/diligence/stream", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    assert res.headers["x-accel-buffering"] == "no"
    events = parse_sse(res.text)
    assert [e for e, _ in events] == ["agent"] * 8 + ["result"]
    assert events[-1][1]["memo"]["verdict"] == "Proceed"


@pytest.mark.parametrize("body", [{}, {"acquirer": "Nike"}, {"acquirer": "  ", "target": "Adidas"}])
def test_invalid_body_is_422_before_streaming(api: TestClient, body: dict[str, str]) -> None:
    res = api.post("/api/diligence/stream", json=body)
    assert res.status_code == 422
    assert "text/event-stream" not in res.headers["content-type"]
