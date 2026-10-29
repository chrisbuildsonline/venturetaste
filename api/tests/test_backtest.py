from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.backtest import DEALS
from api.fixtures import FIXTURES, fixture_handler, make_client
from api.main import app
from api.presets import slug
from api.qloo import QlooClient
from api.scoring import BrandProfile, score

README = (Path(__file__).resolve().parents[2] / "README.md").read_text()


def profile(client: QlooClient, name: str) -> BrandProfile:
    entity = client.search(name)
    insights = {d: client.insights(entity.id, d) for d in ("brand", "artist", "movie", "tv_show", "place", "destination", "book")}
    return BrandProfile(entity.name, insights, client.demographics(entity.id))


def test_every_deal_brand_has_recorded_fixtures() -> None:
    for d in DEALS:
        for brand in (d.acquirer, d.target):
            for kind in ("search", "demographics", "tags"):
                assert (FIXTURES / f"{kind}_{slug(brand)}.json").exists(), (kind, brand)
            assert (FIXTURES / f"insights_{slug(brand)}_brand.json").exists()


def test_backtest_rows_equal_score_on_recorded_fixtures(tmp_path: Path) -> None:
    res = TestClient(app).get("/api/backtest")
    assert res.status_code == 200
    body = res.json()
    assert "sanity check" in body["note"]
    assert [r["year"] for r in body["deals"]] == [d.year for d in DEALS]
    client = make_client(tmp_path, fixture_handler([]))
    for row, d in zip(body["deals"], DEALS, strict=True):
        s = score(profile(client, d.acquirer), profile(client, d.target))
        assert (row["acquirer"], row["target"]) == (d.acquirer, d.target)
        assert row["outcome"] == d.outcome and row["outcome_class"] == d.outcome_class
        assert row["bci"] == s.bci
        assert row["clash"] == s.culture_clash
        assert row["churn"] == s.churn_risk
        assert row["verdict"] in ("Proceed", "Proceed with conditions", "Pass")


def test_full_diligence_on_every_backtest_pair_works_keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VENTURETASTE_FIXTURES", "1")
    rows = TestClient(app).get("/api/backtest").json()["deals"]
    for row in rows:
        res = TestClient(app).post("/api/diligence", json={"acquirer": row["acquirer"], "target": row["target"]})
        assert res.status_code == 200, res.text
        d = res.json()
        assert "recorded" in d
        assert (d["scores"]["bci"], d["scores"]["culture_clash"], d["memo"]["verdict"]) == (row["bci"], row["clash"], row["verdict"])


def test_readme_backtest_table_matches_the_api() -> None:
    rows = TestClient(app).get("/api/backtest").json()["deals"]
    section = README.split("## Backtest on real deals", 1)[1].split("\n## ", 1)[0]
    table = [[c.strip() for c in line.strip().strip("|").split("|")] for line in section.splitlines() if line.startswith("|")][2:]
    assert len(table) == len(rows)
    for cells, row in zip(table, rows, strict=True):
        assert cells == [
            f"{row['acquirer_label']} + {row['target_label']}", str(row["year"]), row["outcome"],
            str(row["bci"]), str(row["clash"]), row["churn"], row["verdict"], row["fit"]["label"],
        ]
    assert "anecdote" in section and "BCI 50, clash 66" in section
    assert "sanity check" in section and "have not been backtested" not in README
