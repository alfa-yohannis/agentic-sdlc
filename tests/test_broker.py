"""Tests for Broker, the Redis stream that carries the messages. They use the in-memory FakeRedis."""

import subprocess

import pytest

import run_agents
from fakes import FakeBroker


def no_program(name: str) -> None:
    """Stand in for shutil.which() on a computer that has none of the programs it is asked for."""
    return None


def docker_installed(name: str) -> str:
    """Stand in for shutil.which() on a computer that has Docker."""
    return "docker"


class FakeDocker:
    """Stands in for subprocess.run() when the broker runs `docker compose`.

    It records every command. With exit code 0, it brings the fake broker up,
    as the real container would.
    """

    def __init__(self, broker: FakeBroker, exit_code: int) -> None:
        """Remember the broker to bring up and the exit code to report."""
        self.broker = broker
        self.exit_code = exit_code
        self.commands = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess:
        """Record the command, bring the broker up if the exit code is 0, and report the exit code."""
        self.commands.append(command)
        if self.exit_code == 0:
            self.broker.client.up = True
        return subprocess.CompletedProcess(command, self.exit_code)


def publish_texts(broker: FakeBroker, count: int) -> None:
    """Publish `count` messages from the human to amy: "message 0", "message 1", and so on."""
    for number in range(count):
        text = f"message {number}"
        broker.publish("human", "amy", text)


def texts_of(result: dict) -> list[str]:
    """Return the text of every message in a Broker.read() result."""
    texts = []
    for message in result["messages"]:
        texts.append(message["text"])
    return texts


def test_publish_adds_a_message_with_sender_recipient_text_and_time():
    """publish() appends one entry with the from, to, text, and ts fields, and returns its id."""
    broker = FakeBroker()
    message_id = broker.publish("human", "amy", "Hello")
    entries = broker.client.streams["test:messages"]
    stored_id, fields = entries[0]
    assert stored_id == message_id
    assert fields["from"] == "human"
    assert fields["to"] == "amy"
    assert fields["text"] == "Hello"
    assert "ts" in fields


def test_read_returns_the_newest_messages_oldest_first():
    """read() without an id returns the newest `limit` messages, oldest first, and the stream's length."""
    broker = FakeBroker()
    publish_texts(broker, 5)
    result = broker.read(limit=3)
    assert texts_of(result) == ["message 2", "message 3", "message 4"]
    assert result["broker"] is True
    assert result["total"] == 5


def test_read_after_an_id_returns_only_later_messages():
    """read(after) returns only the messages that came after the given id, each with its id."""
    broker = FakeBroker()
    publish_texts(broker, 3)
    result = broker.read(after="1-0")
    assert texts_of(result) == ["message 1", "message 2"]
    assert result["messages"][0]["id"] == "2-0"


def test_read_reports_a_broker_that_is_down():
    """read() reports broker False, with no messages, instead of failing when the broker is down."""
    broker = FakeBroker()
    broker.client.up = False
    result = broker.read()
    assert result == {"broker": False, "total": 0, "messages": []}


def test_clear_deletes_every_message():
    """clear() deletes the stream, so read() finds no messages."""
    broker = FakeBroker()
    publish_texts(broker, 2)
    broker.clear()
    result = broker.read()
    assert result["total"] == 0


def test_clear_does_nothing_when_the_broker_is_down():
    """clear() does not fail when the broker is down."""
    broker = FakeBroker()
    broker.client.up = False
    broker.clear()


def test_without_the_redis_package_the_broker_explains_what_is_missing():
    """Without a Redis client, the broker raises RunnerError with a message for the user."""
    broker = FakeBroker()
    broker.client = None
    with pytest.raises(run_agents.RunnerError, match="Redis client is missing"):
        broker.publish("human", "amy", "Hello")


def test_ensure_running_does_nothing_when_the_broker_answers(monkeypatch):
    """ensure_running() starts no container when the broker answers already."""
    broker = FakeBroker()
    docker = FakeDocker(broker, 0)
    monkeypatch.setattr(run_agents.subprocess, "run", docker.run)
    broker.ensure_running()
    assert docker.commands == []


def test_ensure_running_explains_when_docker_is_missing(monkeypatch):
    """ensure_running() raises RunnerError when the broker is down and Docker is not installed."""
    broker = FakeBroker()
    broker.client.up = False
    monkeypatch.setattr(run_agents.shutil, "which", no_program)
    with pytest.raises(run_agents.RunnerError, match="Docker is not available"):
        broker.ensure_running()


def test_ensure_running_explains_when_docker_cannot_start_the_broker(monkeypatch):
    """ensure_running() raises RunnerError when `docker compose up` fails, for example because Docker is not running."""
    broker = FakeBroker()
    broker.client.up = False
    docker = FakeDocker(broker, 1)
    monkeypatch.setattr(run_agents.shutil, "which", docker_installed)
    monkeypatch.setattr(run_agents.subprocess, "run", docker.run)
    with pytest.raises(run_agents.RunnerError, match="Make sure Docker is running"):
        broker.ensure_running()


def test_ensure_running_starts_the_container_and_waits_for_the_broker(monkeypatch):
    """ensure_running() runs `docker compose up -d` with the broker's compose file, then returns once the broker answers."""
    broker = FakeBroker()
    broker.client.up = False
    docker = FakeDocker(broker, 0)
    monkeypatch.setattr(run_agents.shutil, "which", docker_installed)
    monkeypatch.setattr(run_agents.subprocess, "run", docker.run)
    broker.ensure_running()
    compose_file = str(run_agents.BROKER_COMPOSE)
    assert docker.commands == [["docker", "compose", "-f", compose_file, "up", "-d"]]
