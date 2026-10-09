import importlib

import pytest

from tests.helpers import OTHER_EMAIL, OTHER_PASSWORD, FakeClock


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def db_path(tmp_path):
    """Path to a temporary SQLite file. Never the real database."""
    return str(tmp_path / "test.db")


@pytest.fixture
def db_module():
    return importlib.import_module("database.db")


@pytest.fixture
def seeded_db(db_module, db_path):
    """Temporary database with the demo user and a second user."""
    db_module.init_db(db_path)
    db_module.create_user(db_path, OTHER_EMAIL, OTHER_PASSWORD)
    return db_path
