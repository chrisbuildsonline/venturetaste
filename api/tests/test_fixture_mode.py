import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.presets import SCREENS, Screen, preset_brands


def test_fixture_mode_runs_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 200
    assert res.json()["memo"]["verdict"] == "Proceed"


def test_screens_endpoint_serves_the_preset() -> None:
    screens = TestClient(app).get("/api/screens").json()
    assert [s["id"] for s in screens] == [s.id for s in SCREENS]
    assert all(2 <= len(s["targets"]) <= 5 and s["acquirer"] and s["label"] for s in screens)


def test_preset_brands_include_the_screen_brands() -> None:
    brands = set(preset_brands())
    assert {s.acquirer for s in SCREENS} | {t for s in SCREENS for t in s.targets} <= brands


@pytest.mark.parametrize("screen", SCREENS, ids=lambda s: s.id)
def test_fixture_mode_runs_every_screen_target(monkeypatch: pytest.MonkeyPatch, screen: Screen) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    api = TestClient(app)
    for target in screen.targets:
        res = api.post("/api/diligence", json={"acquirer": screen.acquirer, "target": target})
        assert res.status_code == 200, (target, res.text)
        assert res.json()["memo"]["verdict"] in {"Proceed", "Proceed with conditions", "Pass"}


def test_fixture_mode_unknown_brand_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 422


def test_without_the_flag_a_missing_key_is_still_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VENTURETASTE_FIXTURES", raising=False)
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    res = TestClient(app).post("/api/diligence", json={"acquirer": "Nike", "target": "Zzqx Nonbrand"})
    assert res.status_code == 422  # a preset pair would replay recorded answers instead, see test_recorded.py
