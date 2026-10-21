"""Shared setup for the tests: import paths, a test team of two agents, and fakes.

The tests import the runner's modules from agents/ and the web server from
server/, the same way the server does. None of them needs a real broker,
Docker, or the Claude CLI: in-memory fakes stand in for Redis (fakes.py), and
a small script stands in for the CLI (fake_claude.py).
"""

import json
import os
import signal
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
AGENTS_PATH = str(REPO_ROOT / "agents")
SERVER_PATH = str(REPO_ROOT / "server")
sys.path.insert(0, AGENTS_PATH)
sys.path.insert(0, SERVER_PATH)

import run_agents  # noqa: E402
from fakes import FakeBroker  # noqa: E402

FAKE_CLAUDE = TESTS_DIR / "fake_claude.py"
LOCK_HOLDER = TESTS_DIR / "lock_holder.py"

AMY_CONFIG = {
    "label": "Agent A",
    "role": "Tester",
    "tools": ["Read", "Bash"],
    "allow": ["Bash(cd *)", "Bash(python3 -m venv *)", "Bash(.venv/bin/python *)"],
}
BEN_CONFIG = {"label": "Agent B", "role": "Developer"}


def write_agent(team: Path, name: str, config: dict) -> None:
    """Create the agent's folder in the team folder, with an agent.json that holds the config."""
    folder = team / name
    folder.mkdir(parents=True)
    text = json.dumps(config)
    path = folder / "agent.json"
    path.write_text(text, encoding="utf-8")


def fake_command(agent: run_agents.Agent) -> list[str]:
    """Return the command line that starts the fake CLI for the agent's session, in place of Agent.command()."""
    script = str(FAKE_CLAUDE)
    session_id = agent.state["session_id"]
    return [sys.executable, script, session_id]


@pytest.fixture
def team_dir(tmp_path: Path) -> Path:
    """Create a team folder with two agents, amy and ben, and one folder that is no agent. Return the team folder."""
    team = tmp_path / "team"
    write_agent(team, "amy", AMY_CONFIG)
    write_agent(team, "ben", BEN_CONFIG)
    not_an_agent = team / "shared_context"
    not_an_agent.mkdir()
    return team


@pytest.fixture
def runtime_dir(tmp_path: Path) -> Path:
    """Return the path of the runtime folder for the test. The code under test creates it."""
    return tmp_path / "runtime"


@pytest.fixture
def broker() -> FakeBroker:
    """Return a broker whose Redis clients are in-memory fakes."""
    return FakeBroker()


@pytest.fixture
def runner(team_dir: Path, runtime_dir: Path, broker: FakeBroker) -> run_agents.Runner:
    """Return a Runner for the test team, the test runtime folder, and the fake broker."""
    return run_agents.Runner(agents_dir=team_dir, runtime_dir=runtime_dir, broker=broker)


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every agent start the fake CLI instead of the Claude CLI, and make the CLI check pass."""
    monkeypatch.setattr(run_agents.Agent, "command", fake_command)
    monkeypatch.setattr(run_agents, "CLAUDE_BIN", sys.executable)


@pytest.fixture
def restore_signals():
    """Put back the signal handlers that a test replaced, such as the runner's handler for Ctrl+C."""
    numbers = [signal.SIGINT, signal.SIGTERM]
    if os.name == "nt":
        numbers.append(signal.SIGBREAK)
    saved = {}
    for number in numbers:
        saved[number] = signal.getsignal(number)
    yield
    for number, handler in saved.items():
        signal.signal(number, handler)
