"""Starts the real app with uvicorn on a temporary database for browser tests."""

import importlib
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.helpers import APP_ROOT, OTHER_EMAIL, OTHER_PASSWORD


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/e2e/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


@dataclass
class Server:
    url: str
    db_path: Path
    log_path: Path


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(directory):
    db = importlib.import_module("database.db")
    db_path = directory / "e2e.db"
    db.init_db(str(db_path))
    db.create_user(str(db_path), OTHER_EMAIL, OTHER_PASSWORD)

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = directory / "server.log"
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "--factory", "backend.app:create_app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "debug",
        ],
        cwd=APP_ROOT,
        env={**os.environ, "LOGIN_DB_PATH": str(db_path)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 15
    while True:
        if proc.poll() is not None:
            log.close()
            pytest.fail(f"Server exited early:\n{log_path.read_text()}")
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            if time.monotonic() > deadline:
                proc.kill()
                log.close()
                pytest.fail(f"Server did not start:\n{log_path.read_text()}")
            time.sleep(0.1)
    return proc, log, Server(url=url, db_path=db_path, log_path=log_path)


def _stop_server(proc, log):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


@pytest.fixture
def server(tmp_path):
    """A fresh server per test, so lockout state never leaks between tests."""
    proc, log, srv = _start_server(tmp_path)
    yield srv
    _stop_server(proc, log)


@pytest.fixture(scope="module")
def shared_server(tmp_path_factory):
    """One server per module, for tests whose login requests are intercepted."""
    proc, log, srv = _start_server(tmp_path_factory.mktemp("shared"))
    yield srv
    _stop_server(proc, log)


@pytest.fixture
def login_requests(page):
    """Every POST /api/login the page sends."""
    sent = []
    page.on(
        "request",
        lambda request: sent.append(request) if request.url.endswith("/api/login") else None,
    )
    return sent
