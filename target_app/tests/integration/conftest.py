import importlib

import pytest


@pytest.fixture
def app(seeded_db, fake_clock):
    backend_app = importlib.import_module("backend.app")
    return backend_app.create_app(db_path=seeded_db, clock=fake_clock)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def new_client(app):
    """Factory for extra clients with their own cookie jar (a new browser session)."""
    from fastapi.testclient import TestClient

    return lambda: TestClient(app)
