from __future__ import annotations

import pytest

from database import Database


@pytest.fixture
def database(tmp_path):
    db = Database(path=str(tmp_path / "fastats.sqlite"))
    db.migrate()
    return db

