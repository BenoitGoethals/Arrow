from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_db() -> Iterator[None]:
    """Point the app at a temporary SQLite file before any backend imports."""
    tmpdir = tempfile.mkdtemp(prefix="arrow-test-")
    os.environ.setdefault("ARROW_TEST_DB", os.path.join(tmpdir, "test.db"))
    yield


@pytest.fixture
def client() -> Iterator:
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.storage.database import init_db

    init_db()
    with TestClient(app) as c:
        yield c
