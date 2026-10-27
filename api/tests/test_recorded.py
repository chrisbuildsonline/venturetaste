import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.fixtures import BASE, fixture_handler, make_client
from api.main import app, get_qloo
from api.qloo import QlooClient

BODY = {"acquirer": "Nike", "target": "Adidas"}


def status_client(tmp_path: Path, status: int) -> QlooClient:
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json={})))
    return QlooClient(api_key="rejected-key", base_url=BASE, cache_dir=tmp_path, http=http)


@pytest.fixture
def reject(tmp_path: Path) -> Callable[[int], TestClient]:
    def use(status: int) -> TestClient:
        app.dependency_overrides[get_qloo] = lambda: status_client(tmp_path, status)
        return TestClient(app)

    return use


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    yield
    app.dependency_overrides.clear()


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_on_a_preset_pair_replays_recorded_answers(
    reject: Callable[[int], TestClient], tmp_path: Path, status: int
) -> None:
    res = reject(status).post("/api/diligence", json=BODY)
    assert res.status_code == 200, res.text
    report = res.json()
    assert "rejected" in report["recorded"]["reason"]
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path / "fx", fixture_handler([]))
    fixture_run = TestClient(app).post("/api/diligence", json=BODY).json()
    assert "recorded" not in fixture_run
    assert report["scores"]["bci"] == fixture_run["scores"]["bci"] == 53.9


def test_rejected_key_stream_ends_in_a_recorded_result(reject: Callable[[int], TestClient]) -> None:
    res = reject(401).post("/api/diligence/stream", json=BODY)
    events = parse_sse(res.text)
    assert res.status_code == 200
    assert "error" not in [e for e, _ in events]
    kind, data = events[-1]
    assert kind == "result" and data["scores"]["bci"] == 53.9
    assert "rejected" in data["recorded"]["reason"]


@pytest.fixture
def dead_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_LLM", "on")
    monkeypatch.setenv("VENTURETASTE_LLM_URL", "http://127.0.0.1:9/v1")


def test_rejected_key_and_dead_llm_answers_within_5_seconds(reject: Callable[[int], TestClient], dead_llm: None) -> None:
    api = reject(401)
    start = time.monotonic()
    res = api.post("/api/diligence", json=BODY)
    assert time.monotonic() - start < 5
    assert res.status_code == 200, res.text
    assert "rejected" in res.json()["recorded"]["reason"]


def test_rejected_key_and_dead_llm_stream_ends_in_result_within_5_seconds(reject: Callable[[int], TestClient], dead_llm: None) -> None:
    api = reject(401)
    start = time.monotonic()
    events = parse_sse(api.post("/api/diligence/stream", json=BODY).text)
    assert time.monotonic() - start < 5
    assert events[-1][0] == "result" and "rejected" in events[-1][1]["recorded"]["reason"]


def test_missing_key_on_a_preset_pair_replays_recorded_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/diligence", json={"acquirer": "patagonia", "target": "The North Face"})
    assert res.status_code == 200, res.text
    assert "No Qloo API key is set" in res.json()["recorded"]["reason"]


def test_missing_key_stream_ends_in_a_recorded_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    events = parse_sse(TestClient(app).post("/api/diligence/stream", json=BODY).text)
    assert "error" not in [e for e, _ in events]
    assert events[-1][0] == "result" and "No Qloo API key" in events[-1][1]["recorded"]["reason"]


def test_fixture_mode_marks_every_result_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    api = TestClient(app)
    assert "fixture mode" in api.post("/api/diligence", json=BODY).json()["recorded"]["reason"]
    events = parse_sse(api.post("/api/diligence/stream", json=BODY).text)
    assert "fixture mode" in events[-1][1]["recorded"]["reason"]


def test_unknown_brand_with_a_rejected_key_is_the_friendly_502(reject: Callable[[int], TestClient]) -> None:
    res = reject(401).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 502
    assert res.json() == {"detail": "Taste data from Qloo is temporarily unavailable. Please try again in a moment."}


def test_unknown_brand_with_a_rejected_key_streams_the_error(reject: Callable[[int], TestClient]) -> None:
    events = parse_sse(reject(401).post("/api/diligence/stream", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"}).text)
    kind, data = events[-1]
    assert kind == "error" and data["status"] == 502


def test_unknown_brand_with_no_key_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 503
    res = TestClient(app).post("/api/diligence/stream", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 503


@pytest.mark.parametrize("status", [429, 500, 503])
def test_other_qloo_failures_do_not_fall_back(reject: Callable[[int], TestClient], status: int) -> None:
    res = reject(status).post("/api/diligence", json=BODY)
    assert res.status_code == 502
    assert "recorded" not in res.text
    kind, data = parse_sse(reject(status).post("/api/diligence/stream", json=BODY).text)[-1]
    assert kind == "error" and data["status"] == 502


def test_a_valid_key_run_has_no_recorded_field(tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    assert "recorded" not in TestClient(app).post("/api/diligence", json=BODY).json()


def test_the_key_is_never_returned(reject: Callable[[int], TestClient]) -> None:
    assert "rejected-key" not in reject(401).post("/api/diligence", json=BODY).text
    assert "rejected-key" not in reject(500).post("/api/diligence", json=BODY).text
