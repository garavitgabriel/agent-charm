from collections.abc import Iterator

import pytest
from fake_service import Fake, serve


@pytest.fixture
def fake() -> Iterator[tuple[Fake, str]]:
    with serve() as served:
        yield served
