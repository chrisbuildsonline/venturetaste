from collections.abc import Iterator

import pytest

from api.main import reset_rate_limit


@pytest.fixture(autouse=True)
def _fresh_rate_limit() -> Iterator[None]:
    reset_rate_limit()
    yield


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never reach a real LLM; the llm-marked test turns it back on."""
    monkeypatch.setenv("VENTURETASTE_LLM", "off")
