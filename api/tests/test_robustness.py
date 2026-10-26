"""A bad QLOO_API_URL or a failing upstream must give plain-language errors, never httpx text."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api import main
from api.main import app, get_qloo
from api.qloo import DEFAULT_URL, QlooClient, normalize_base_url

FRIENDLY = "Taste data from Qloo is temporarily unavailable. Please try again in a moment."
BODY = {"acquirer": "Nike", "target": "Adidas"}


@pytest.mark.parametrize(
    "value",
    ["set by orchestrator", "hackathon.api.qloo.com", "ftp://x", "", "   ", "https://", "http:///path", None],
)
def test_bad_urls_fall_back_to_the_default(value: str | None, caplog: pytest.LogCaptureFixture) -> None:
    assert normalize_base_url(value) == DEFAULT_URL
    if value and value.strip():
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://qloo.example.com", "https://qloo.example.com"),
        ("https://qloo.example.com/", "https://qloo.example.com"),
        ("http://127.0.0.1:9000/base/", "http://127.0.0.1:9000/base"),
    ],
)
def test_valid_urls_are_kept(value: str, expected: str, caplog: pytest.LogCaptureFixture) -> None:
    assert normalize_base_url(value) == expected
    assert caplog.records == []


def test_client_uses_the_fallback_for_a_placeholder_env_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.setenv("QLOO_API_URL", "set by orchestrator")
    assert QlooClient()._base == DEFAULT_URL


def failing(exc: Exception, tmp_path: Path) -> Callable[[], QlooClient]:
    def raise_it(request: httpx.Request) -> httpx.Response:
        raise exc

    http = httpx.Client(transport=httpx.MockTransport(raise_it))
    return lambda: QlooClient(api_key="k", base_url="https://qloo.test", cache_dir=tmp_path, http=http)


@pytest.fixture
def web() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def assert_clean(text: str) -> None:
    for bad in ("httpx", "Error(", "<", "UnsupportedProtocol", "ConnectError", "Traceback"):
        assert bad not in text


ERRORS = [
    httpx.ConnectError("connection refused"),
    httpx.UnsupportedProtocol("Request URL is missing an 'http://' or 'https://' protocol."),
    httpx.ReadTimeout("timed out"),
]


@pytest.mark.parametrize("exc", ERRORS, ids=lambda e: type(e).__name__)
def test_transport_failure_is_a_friendly_502(exc: Exception, web: TestClient, tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = failing(exc, tmp_path)
    res = web.post("/api/diligence", json=BODY)
    assert res.status_code == 502
    assert res.json() == {"detail": FRIENDLY}
    assert_clean(res.text)


@pytest.mark.parametrize("exc", ERRORS, ids=lambda e: type(e).__name__)
def test_transport_failure_is_a_friendly_sse_error(exc: Exception, web: TestClient, tmp_path: Path) -> None:
    app.dependency_overrides[get_qloo] = failing(exc, tmp_path)
    res = web.post("/api/diligence/stream", json=BODY)
    assert res.status_code == 200
    assert_clean(res.text.split("event: error", 1)[1])
    assert res.text.rstrip().endswith("}")
    last = res.text.strip().split("\n")[-1]
    assert json.loads(last.removeprefix("data: ")) == {"status": 502, "detail": FRIENDLY}


def test_bad_upstream_status_and_body_do_not_leak(web: TestClient, tmp_path: Path) -> None:
    for response in (httpx.Response(500, text="<html>boom</html>"), httpx.Response(200, json={"oops": 1})):
        http = httpx.Client(transport=httpx.MockTransport(lambda r, response=response: response))
        app.dependency_overrides[get_qloo] = lambda: QlooClient(api_key="k", base_url="https://q.test", cache_dir=tmp_path / "c", http=http)
        res = web.post("/api/diligence", json=BODY)
        assert (res.status_code, res.json()) == (502, {"detail": FRIENDLY})
        stream = web.post("/api/diligence/stream", json=BODY).text
        assert json.loads(stream.strip().split("\n")[-1].removeprefix("data: ")) == {"status": 502, "detail": FRIENDLY}


def test_unexpected_exception_in_the_stream_is_friendly(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object) -> Iterator[tuple[str, object]]:
        raise RuntimeError("secret <internal> detail")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "stream_diligence", boom)
    app.dependency_overrides[get_qloo] = lambda: QlooClient(api_key="k", base_url="https://q.test")
    res = web.post("/api/diligence/stream", json=BODY)
    assert "secret" not in res.text and "RuntimeError" not in res.text
    assert json.loads(res.text.strip().split("\n")[-1].removeprefix("data: ")) == {"status": 502, "detail": FRIENDLY}


def test_human_written_errors_are_kept(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    unknown = web.post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert unknown.status_code == 422 and "Zzqx Nonbrand" in unknown.json()["detail"]
    same = web.post("/api/diligence", json={"acquirer": "Nike", "target": "nike"})
    assert same.status_code == 422 and "two different brands" in same.json()["detail"]
    monkeypatch.delenv("VENTURETASTE_FIXTURES")
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    missing = web.post("/api/diligence", json=BODY)
    assert missing.status_code == 503 and "QLOO_API_KEY" in missing.json()["detail"]


def test_health_reports_config_without_the_key(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QLOO_API_KEY", "super-secret")
    monkeypatch.setenv("QLOO_API_URL", "set by orchestrator")
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    res = web.get("/api/health")
    assert res.json() == {"ok": True, "qloo_key": True, "qloo_url": DEFAULT_URL, "fixtures": False}
    assert "super-secret" not in res.text

    monkeypatch.delenv("QLOO_API_KEY")
    monkeypatch.setenv("QLOO_API_URL", "https://qloo.example.com/")
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    assert web.get("/api/health").json() == {
        "ok": True,
        "qloo_key": False,
        "qloo_url": "https://qloo.example.com",
        "fixtures": True,
    }
