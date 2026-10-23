from collections.abc import Iterator

import pytest

from api.main import reset_rate_limit


@pytest.fixture(autouse=True)
def _fresh_rate_limit() -> Iterator[None]:
    reset_rate_limit()
    yield
