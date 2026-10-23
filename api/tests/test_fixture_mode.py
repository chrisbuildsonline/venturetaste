import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_fixture_mode_runs_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 200
    assert res.json()["memo"]["verdict"] == "Proceed"


def test_fixture_mode_unknown_brand_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 422


def test_without_the_flag_a_missing_key_is_still_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 503
