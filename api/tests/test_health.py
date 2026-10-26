import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_health_shows_only_scheme_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    monkeypatch.setenv("QLOO_API_URL", "https://user:pw@example.com:8443/base/?key=x")
    assert client.get("/api/health").json()["qloo_url"] == "https://example.com:8443"
    monkeypatch.setenv("QLOO_API_URL", "https://user:pw@example.com/?key=x")
    assert client.get("/api/health").json()["qloo_url"] == "https://example.com"
