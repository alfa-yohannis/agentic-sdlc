"""Tests for Runner: the team's folders and status, stopping and clearing, and a whole run with the fake CLI.

The stop tests start lock_holder.py in a process of its own to play a running
runner, so they also check that a stop request reaches another process on
this operating system.
"""

import os
import subprocess
import sys
import time

import pytest

import run_agents
from conftest import LOCK_HOLDER


def start_lock_holder(runner: run_agents.Runner, options: list[str]) -> subprocess.Popen:
    """Start lock_holder.py with the options, as a runner in the runner's runtime folder. Return once it holds the lock."""
    script = str(LOCK_HOLDER)
    folder = str(runner.runtime_dir)
    command = [sys.executable, script, folder]
    command.extend(options)
    child = subprocess.Popen(command)
    for attempt in range(100):
        if runner.lock.holder():
            return child
        time.sleep(0.1)
    child.kill()
    raise AssertionError("The lock holder did not take the lock.")


def test_agent_names_lists_only_folders_with_an_agent_json_sorted(runner):
    """agent_names() lists the folders that have an agent.json, sorted, and skips the others."""
    names = runner.agent_names()
    assert names == ["amy", "ben"]


def test_status_reports_no_runner_and_offline_agents(runner):
    """status() reports that no runner runs, and every agent as offline."""
    status = runner.status()
    assert status["running"] is False
    assert status["pid"] is None
    for agent in status["agents"]:
        assert agent["status"] == "offline"


def test_status_reports_a_running_runner_and_the_saved_agent_status(runner):
    """While a runner holds the lock, status() reports its pid and each agent's saved status."""
    child = start_lock_holder(runner, [])
    try:
        files = runner.agent_files()[0]
        files.runtime.mkdir(parents=True)
        files.write_state({"status": "working", "pid": 42})
        status = runner.status()
        assert status["running"] is True
        assert status["pid"] > 0
        assert status["agents"][0]["status"] == "working"
    finally:
        runner.stop(timeout=15)
        child.wait(timeout=15)


def test_stop_returns_at_once_when_no_runner_runs(runner):
    """stop() returns True right away when no runner holds the lock."""
    stopped = runner.stop(timeout=1)
    assert stopped is True


def test_stop_asks_the_runner_to_stop_and_waits_until_it_has(runner):
    """stop() sends a stop request to the runner in another process, which then exits normally and frees the lock."""
    child = start_lock_holder(runner, [])
    stopped = runner.stop(timeout=15)
    exit_code = child.wait(timeout=15)
    assert stopped is True
    assert exit_code == 0
    assert runner.lock.holder() is None


def test_stop_kills_a_runner_that_does_not_stop_in_time(runner):
    """stop() kills a runner that ignores the stop request, and returns False."""
    child = start_lock_holder(runner, ["--stubborn"])
    stopped = runner.stop(timeout=1)
    exit_code = child.wait(timeout=15)
    assert stopped is False
    assert exit_code != 0


def test_clear_deletes_the_session_files_and_the_messages(runner, broker):
    """clear() deletes every agent's session files and every message on the broker."""
    files = runner.agent_files()[0]
    files.runtime.mkdir(parents=True)
    files.write_state({"session_id": "old", "turns": 4})
    broker.publish("human", "amy", "Hello")
    runner.clear()
    assert files.read_state() == {}
    assert broker.read()["total"] == 0


def test_start_refuses_without_the_claude_cli(runner, monkeypatch):
    """start() raises RunnerError when it cannot find the Claude CLI."""
    monkeypatch.setattr(run_agents, "CLAUDE_BIN", "no-such-claude-cli")
    with pytest.raises(run_agents.RunnerError, match="Cannot find the Claude CLI"):
        runner.start()


def test_start_refuses_while_another_runner_holds_the_lock(runner, fake_cli):
    """start() raises RunnerError when another runner holds the lock."""
    other = run_agents.RunnerLock(runner.lock.path, runner.platform)
    other.acquire()
    try:
        with pytest.raises(run_agents.RunnerError, match="already running"):
            runner.start()
    finally:
        other.release()


class StopAfterAcknowledgement:
    """Asks the runner to stop as soon as one message has been acknowledged, the way --stop would."""

    def __init__(self, runner: run_agents.Runner, message_id: str) -> None:
        """Remember the runner to stop and the message to wait for."""
        self.runner = runner
        self.message_id = message_id

    def on_ack(self, message_id: str) -> None:
        """If the acknowledged message is the awaited one, send this process, the runner, a stop request."""
        if message_id != self.message_id:
            return
        pid = os.getpid()
        self.runner.platform.request_stop(pid)


def test_a_whole_run_answers_the_inbox_and_stops_on_request(runner, broker, fake_cli, restore_signals, capsys):
    """start() runs both agents with the fake CLI, answers the message in amy's inbox, and stops when asked.

    Afterwards the lock is free, amy has one turn, every group exists, and
    the broker's client is closed.
    """
    broker.fake_async.add_batch("agent:amy", [("1-0", {"from": "human", "to": "amy", "text": "Hello Amy"})])
    stopper = StopAfterAcknowledgement(runner, "1-0")
    broker.fake_async.on_ack = stopper.on_ack
    runner.start()
    status = runner.status()
    assert status["running"] is False
    assert status["agents"][0]["turns"] == 1
    assert broker.fake_async.acked == ["1-0"]
    assert broker.fake_async.groups == {"agent:amy", "agent:ben"}
    assert broker.fake_async.closed is True
    output = capsys.readouterr().out
    assert "Starting 2 agents: amy, ben" in output
    assert "[amy] <- human: Hello Amy" in output
    assert "All agents stopped." in output
