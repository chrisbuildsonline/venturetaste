"""J5d API polish: same-brand check before Qloo, friendly no-key 422, replayed runs, trivial tags."""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.fixtures import fixture_handler, make_client
from api.main import app, get_qloo, screen_row
from api.presets import preset_brands
from api.qloo import Tag
from api.scoring import bridges


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    yield
    app.dependency_overrides.clear()


def sse_events(text: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    out = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def counting(tmp_path: Path) -> list[httpx.Request]:
    calls: list[httpx.Request] = []
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler(calls))
    return calls


SAME = [("Nike", "nike"), ("Nike", " NIKE "), ("The North Face", "the-north-face"), ("McDonald's", "MCDONALD'S ")]


@pytest.mark.parametrize(("a", "t"), SAME)
def test_same_brand_is_422_with_zero_qloo_calls(counting: list[httpx.Request], a: str, t: str) -> None:
    api = TestClient(app)
    res = api.post("/api/diligence", json={"acquirer": a, "target": t})
    assert res.status_code == 422 and "two different brands" in res.json()["detail"]
    res = api.post("/api/diligence/stream", json={"acquirer": a, "target": t})
    assert res.status_code == 422 and "two different brands" in res.json()["detail"]
    assert counting == []
    row = screen_row(None, a, t)
    assert row["ok"] is False and row["status"] == 422 and "two different brands" in row["detail"]
    assert not counting


def test_same_brand_makes_no_call_at_all(counting: list[httpx.Request]) -> None:
    TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "nike"})
    TestClient(app).post("/api/diligence/stream", json={"acquirer": "Nike", "target": "nike"})
    assert counting == []


def test_no_key_non_preset_is_422_listing_recorded_brands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    api = TestClient(app)
    body = {"acquirer": "Tesla", "target": "Ford"}
    for path in ("/api/diligence", "/api/diligence/stream"):
        res = api.post(path, json=body)
        assert res.status_code == 422, path
        detail = res.json()["detail"]
        assert detail.startswith("No Qloo API key is set on this server, so only recorded brands work: ")
        assert all(b in detail for b in preset_brands())
        assert detail.endswith("Set QLOO_API_KEY to try any brand.")


def test_no_key_discover_and_screen_rows_say_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    api = TestClient(app)
    res = api.post("/api/discover", json={"acquirer": "Zara"})
    assert res.status_code == 422
    assert "only recorded brands work: Nike, Patagonia, Starbucks." in res.json()["detail"]
    rows = api.post("/api/screen", json={"acquirer": "Nike", "targets": ["Adidas", "Zzqx Nonbrand"]}).json()["rows"]
    assert rows[1]["status"] == 422 and "only recorded brands work" in rows[1]["detail"]


def test_replayed_run_reports_zero_qloo_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    api = TestClient(app)
    body = {"acquirer": "Nike", "target": "Adidas"}
    trace = api.post("/api/diligence", json=body).json()["trace"]
    assert [t["qloo_calls"] for t in trace] == [0, 0, 0, 0]
    assert all(t["replayed"] is True for t in trace)
    events = sse_events(api.post("/api/diligence/stream", json=body).text)
    done = [d for e, d in events if e == "agent" and d["status"] == "ok"]
    assert len(done) == 4 and all(d["qloo_calls"] == 0 and d["replayed"] is True for d in done)


def test_live_run_keeps_real_counts(counting: list[httpx.Request]) -> None:
    trace = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"}).json()["trace"]
    assert [t["qloo_calls"] for t in trace] == [2, 16, 3, 0]  # the recorded Nike + Adidas plan probes tags and follows up
    assert not any("replayed" in t for t in trace)


def test_bridges_drop_trivial_tags() -> None:
    def tags(aff: float) -> list[Tag]:
        return [
            Tag("urn:tag:inclusivity:place:identifies_as_women_owned", "Identifies as women-owned", aff),
            Tag("urn:tag:keyword:media:friendship", "friendship", aff),
            Tag("urn:tag:cost_description:place:expensive", "Expensive", aff),
            Tag("urn:tag:keyword:qloo:sustainability", "sustainability", aff),
        ]

    assert [b.name for b in bridges(tags(1.0), tags(0.9))] == ["sustainability"]
