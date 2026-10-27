from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "README.md").read_text()


def test_readme_links_the_public_repo_and_the_license() -> None:
    assert "https://github.com/chrisbuildsonline/venturetaste" in README
    assert "(LICENSE)" in README


def test_readme_documents_the_recorded_field() -> None:
    assert "`recorded`" in README
