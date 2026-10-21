"""Tests for the web server's API.

The server under test uses the test team and the fake broker. Where it
starts a runner, it starts lock_holder.py instead, which holds the runner's
lock until it is asked to stop.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import run_agents
from conftest import LOCK_HOLDER

# Stands in for agents/run_agents.py when the server under test starts the runner.
RUNNER_SHIM = '''"""Run lock_holder.py in place of the runner, with the paths and options from the environment."""
import os
import runpy
import sys

# Windows drops a variable whose value is empty, so the options may be missing.
options_text = os.environ.get("SDLC_TEST_OPTIONS", "")
options = options_text.split()
sys.argv = [os.environ["SDLC_TEST_LOCK_HOLDER"], os.environ["SDLC_TEST_RUNTIME"]] + options
runpy.run_path(sys.argv[0], run_name="__main__")
'''


@pytest.fixture
def runner_process(runner, monkeypatch) -> main.RunnerProcess:
    """Point the server at the test runner, and return the RunnerProcess the server now uses."""
    runner_process = main.RunnerProcess(runner)
    monkeypatch.setattr(main, "runner", runner)
    monkeypatch.setattr(main, "runner_process", runner_process)
    return runner_process


@pytest.fixture
def client(runner_process) -> TestClient:
    """Return a test client for the server's app."""
    return TestClient(main.app)


@pytest.fixture
def lock_holder_as_runner(tmp_path, runner, monkeypatch) -> None:
    """Make the server start lock_holder.py, in the test runtime folder, where it would start agents/run_agents.py."""
    folder = tmp_path / "server_agents"
    folder.mkdir()
    shim = folder / "run_agents.py"
    shim.write_text(RUNNER_SHIM, encoding="utf-8")
    holder = str(LOCK_HOLDER)
    runtime = str(runner.runtime_dir)
    monkeypatch.setattr(main, "AGENTS_DIR", folder)
    monkeypatch.setenv("SDLC_TEST_LOCK_HOLDER", holder)
    monkeypatch.setenv("SDLC_TEST_RUNTIME", runtime)
    monkeypatch.setenv("SDLC_TEST_OPTIONS", "")


def agent_names(status: dict) -> list[str]:
    """Return the name of every agent in a status answer."""
    names = []
    for agent in status["agents"]:
        names.append(agent["name"])
    return names


def test_the_page_is_served(client):
    """GET / returns the monitor page."""
    response = client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text


def test_agents_reports_the_team_and_no_runner(client):
    """GET /api/agents lists every agent, and says that no runner runs."""
    response = client.get("/api/agents")
    status = response.json()
    assert response.status_code == 200
    assert status["running"] is False
    assert agent_names(status) == ["amy", "ben"]


def test_a_message_from_the_page_goes_to_the_broker(client, broker):
    """POST /api/messages publishes the stripped text from the human, and returns the message id."""
    response = client.post("/api/messages", json={"to": "amy", "text": "  Please begin  "})
    assert response.status_code == 200
    message = broker.read()["messages"][0]
    assert response.json()["id"] == message["id"]
    assert message["from"] == "human"
    assert message["text"] == "Please begin"


def test_a_message_to_an_unknown_recipient_or_without_text_is_refused(client, broker):
    """POST /api/messages answers 400 for an unknown recipient or an empty text, and sends nothing."""
    unknown = client.post("/api/messages", json={"to": "zed", "text": "hi"})
    empty = client.post("/api/messages", json={"to": "all", "text": "   "})
    assert unknown.status_code == 400
    assert empty.status_code == 400
    assert broker.read()["total"] == 0


def test_a_message_while_the_broker_is_down_is_refused(client, broker):
    """POST /api/messages answers 503 when the broker is not running."""
    broker.client.up = False
    response = client.post("/api/messages", json={"to": "amy", "text": "hi"})
    assert response.status_code == 503


def test_messages_returns_the_stream_after_an_id(client, broker):
    """GET /api/messages returns every message, or only those after the id in `after`."""
    broker.publish("human", "amy", "first")
    broker.publish("human", "amy", "second")
    everything = client.get("/api/messages").json()
    later = client.get("/api/messages", params={"after": "1-0"}).json()
    assert everything["total"] == 2
    assert len(everything["messages"]) == 2
    assert later["messages"][0]["text"] == "second"


def test_reset_without_a_runner_clears_sessions_and_messages(client, runner, broker):
    """POST /api/reset clears the agents' session files and the messages even when no runner runs."""
    files = runner.agent_files()[0]
    files.runtime.mkdir(parents=True)
    files.write_state({"session_id": "old", "turns": 2})
    broker.publish("human", "amy", "old message")
    response = client.post("/api/reset")
    assert response.status_code == 200
    assert response.json()["agents"][0]["turns"] == 0
    assert broker.read()["total"] == 0


def test_start_leaves_a_running_runner_alone(client, runner, runner_process):
    """POST /api/start starts no second runner while one holds the lock."""
    other = run_agents.RunnerLock(runner.lock.path, runner.platform)
    other.acquire()
    try:
        response = client.post("/api/start")
        assert response.status_code == 200
        assert response.json()["running"] is True
        assert runner_process.process is None
    finally:
        other.release()


def test_start_starts_the_runner_and_reset_stops_it(client, runner_process, lock_holder_as_runner):
    """POST /api/start starts the runner in the background and waits for it; POST /api/reset stops it."""
    started = client.post("/api/start")
    assert started.status_code == 200
    assert started.json()["running"] is True
    process = runner_process.process
    assert process is not None
    stopped = client.post("/api/reset")
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False
    exit_code = process.wait(timeout=15)
    assert exit_code == 0


def test_start_reports_why_the_runner_exited(client, lock_holder_as_runner, monkeypatch):
    """POST /api/start answers 500, with the end of the runner's output, when the runner exits instead of starting."""
    monkeypatch.setenv("SDLC_TEST_OPTIONS", "--fail")
    response = client.post("/api/start")
    detail = response.json()["detail"]
    assert response.status_code == 500
    assert detail.startswith("The runner exited:")
    assert "Something went wrong before the lock." in detail


def test_log_tail_joins_the_last_lines_of_the_runner_log(runner_process):
    """log_tail() says "no output" without a log, and joins the last lines of the log otherwise."""
    assert runner_process.log_tail() == "no output"
    log_path: Path = runner_process.runner.log_file
    log_path.parent.mkdir(parents=True)
    log_path.write_text("one\ntwo\nthree\nfour\nfive\nsix\n", encoding="utf-8")
    assert runner_process.log_tail(lines=2) == "five six"
