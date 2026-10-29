from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.fixtures import fixture_handler, make_client
from api.main import app, get_qloo
from api.pipeline import fit_type
from api.scoring import Scores, _band


def scores(bci: float, clash: float) -> Scores:
    return Scores(bci, clash, _band(clash), 0.3, {}, (), (), ())


@pytest.mark.parametrize(
    ("bci", "clash", "kind"),
    [
        (49.9, 66.0, "complementary"),  # high churn, bci just under 50
        (50.0, 66.0, "overlapping"),  # bci at 50 wins even with high churn
        (80.0, 90.0, "overlapping"),
        (30.0, 65.9, "adjacent"),  # clash just under 66 is medium churn
        (30.0, 66.0, "complementary"),
        (49.9, 10.0, "adjacent"),
        (50.0, 10.0, "overlapping"),
    ],
)
def test_fit_rule_boundaries(bci: float, clash: float, kind: str) -> None:
    fit = fit_type(scores(bci, clash))
    assert fit["type"] == kind
    assert fit["label"] == kind.capitalize()
    assert fit["note"] and "—" not in fit["note"]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_qloo] = lambda: make_client(tmp_path, fixture_handler([]))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_diligence_response_has_fit(api: TestClient) -> None:
    res = api.post("/api/diligence", json={"acquirer": "Nike", "target": "Adidas"})
    assert res.status_code == 200
    fit = res.json()["fit"]
    assert fit["type"] == "overlapping" and fit["label"] == "Overlapping" and fit["note"]


def test_stream_result_has_fit(api: TestClient) -> None:
    res = api.post("/api/diligence/stream", json={"acquirer": "Nike", "target": "Converse"})
    assert res.status_code == 200
    import json

    frames = res.text.strip().split("\n\n")
    event, data = [line.split(": ", 1)[1] for line in frames[-1].split("\n")]
    assert event == "result"
    assert json.loads(data)["fit"]["type"] == "complementary"


def test_backtest_fit_per_deal() -> None:
    rows = TestClient(app).get("/api/backtest").json()["deals"]
    got = {f"{r['acquirer']} + {r['target']}": r["fit"]["type"] for r in rows}
    assert got == {
        "Nike + Converse": "complementary",
        "Vans + Supreme": "adjacent",
        "Coach + Michael Kors": "adjacent",
        "Adidas + Reebok": "adjacent",
        "Vans + The North Face": "complementary",
        "Coach + Kate Spade": "adjacent",
        "Estée Lauder + Tom Ford": "complementary",
        "Nike + Umbro": "adjacent",
        "Coach + Stuart Weitzman": "adjacent",
        "Michael Kors + Versace": "adjacent",
        "Walmart + Bonobos": "complementary",
    }
    assert all(r["fit"]["label"] and r["fit"]["note"] for r in rows)
