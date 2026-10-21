"""Tests for AgentFiles and Agent: an agent's files, its command line, and how it handles messages and events.

The last tests run real sessions with the fake CLI (fake_claude.py).
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

import os_support
import run_agents
from conftest import FAKE_CLAUDE
from fakes import FakeBroker


def make_files(team_dir: Path, runtime_dir: Path, name: str = "amy") -> run_agents.AgentFiles:
    """Return the AgentFiles of the named agent in the test team."""
    folder = team_dir / name
    return run_agents.AgentFiles(folder, runtime_dir)


def make_agent(team_dir: Path, runtime_dir: Path, broker: FakeBroker, name: str = "amy") -> run_agents.Agent:
    """Return the named agent of the test team, with the platform of this computer and the fake broker."""
    files = make_files(team_dir, runtime_dir, name)
    platform = os_support.current_platform(runtime_dir)
    return run_agents.Agent(files, platform, broker, broker.fake_async)


def option_value(cmd: list[str], option: str) -> str:
    """Return the value that follows the option in a command line."""
    position = cmd.index(option)
    return cmd[position + 1]


def read_events(files: run_agents.AgentFiles) -> list[dict]:
    """Return every event in the agent's events.jsonl."""
    path = files.runtime / "events.jsonl"
    text = path.read_text(encoding="utf-8")
    events = []
    for line in text.splitlines():
        event = json.loads(line)
        events.append(event)
    return events


# AgentFiles


def test_status_is_offline_while_no_runner_runs(team_dir, runtime_dir):
    """status(False) reports offline and no pid, whatever session.json says, but keeps the session and turns."""
    files = make_files(team_dir, runtime_dir)
    files.runtime.mkdir(parents=True)
    files.write_state({"status": "idle", "pid": 42, "session_id": "abc", "turns": 2})
    status = files.status(False)
    assert status["status"] == "offline"
    assert status["pid"] is None
    assert status["session_id"] == "abc"
    assert status["turns"] == 2
    assert status["label"] == "Agent A"
    assert status["role"] == "Tester"


def test_status_reports_the_saved_state_while_the_runner_runs(team_dir, runtime_dir):
    """status(True) reports the status and pid in session.json."""
    files = make_files(team_dir, runtime_dir)
    files.runtime.mkdir(parents=True)
    files.write_state({"status": "working", "pid": 42})
    status = files.status(True)
    assert status["status"] == "working"
    assert status["pid"] == 42


def test_log_appends_events_with_the_time(team_dir, runtime_dir):
    """log() appends one JSON line per event to events.jsonl, with a ts field added."""
    files = make_files(team_dir, runtime_dir)
    files.runtime.mkdir(parents=True)
    files.log({"type": "runtime", "text": "first"})
    files.log({"type": "runtime", "text": "second"})
    events = read_events(files)
    assert len(events) == 2
    assert events[1]["text"] == "second"
    assert "ts" in events[0]


def test_clear_deletes_the_runtime_files(team_dir, runtime_dir):
    """clear() deletes session.json, events.jsonl, and stderr.log."""
    files = make_files(team_dir, runtime_dir)
    files.runtime.mkdir(parents=True)
    for name in ("session.json", "events.jsonl", "stderr.log"):
        path = files.runtime / name
        path.write_text("x")
    files.clear()
    entries = files.runtime.iterdir()
    left = list(entries)
    assert left == []


# Agent: state and command line


def test_a_new_agent_gets_a_new_session_and_its_runtime_folder(team_dir, runtime_dir, broker):
    """Without a saved session, the agent picks a new session id, has no turns, and creates its runtime folder."""
    agent = make_agent(team_dir, runtime_dir, broker)
    assert agent.state["session_id"]
    assert agent.state["turns"] == 0
    assert agent.files.runtime.is_dir()
    assert agent.session_started() is False


def test_an_agent_keeps_its_saved_session(team_dir, runtime_dir, broker):
    """With a saved session, the agent keeps its id, and knows that the session has started."""
    files = make_files(team_dir, runtime_dir)
    files.runtime.mkdir(parents=True)
    files.write_state({"session_id": "saved-id", "turns": 3})
    agent = make_agent(team_dir, runtime_dir, broker)
    assert agent.state["session_id"] == "saved-id"
    assert agent.session_started() is True


def test_command_creates_a_new_session_until_the_first_message(team_dir, runtime_dir, broker):
    """command() uses --session-id for a session that never had a message, and --resume after one."""
    agent = make_agent(team_dir, runtime_dir, broker)
    session_id = agent.state["session_id"]
    first = agent.command()
    assert option_value(first, "--session-id") == session_id
    assert "--resume" not in first
    agent.state["started"] = True
    later = agent.command()
    assert option_value(later, "--resume") == session_id


def test_command_passes_the_name_tools_and_permission_mode(team_dir, runtime_dir, broker):
    """command() names the session after the agent, joins its tools, and uses acceptEdits by default."""
    agent = make_agent(team_dir, runtime_dir, broker)
    cmd = agent.command()
    assert cmd[0] == run_agents.CLAUDE_BIN
    assert option_value(cmd, "--name") == "amy"
    assert option_value(cmd, "--tools") == "Read,Bash"
    assert option_value(cmd, "--permission-mode") == "acceptEdits"


def test_command_adds_the_team_context_and_the_platform_note(team_dir, runtime_dir, broker):
    """command() appends team.md and the platform's note to the system prompt."""
    agent = make_agent(team_dir, runtime_dir, broker)
    cmd = agent.command()
    prompt = option_value(cmd, "--append-system-prompt")
    team_context = run_agents.TEAM_CONTEXT.read_text(encoding="utf-8")
    assert prompt == team_context + agent.platform.prompt_note


def test_command_creates_the_folders_under_add_dirs(team_dir, runtime_dir, broker, tmp_path, monkeypatch):
    """command() creates every folder listed under add_dirs, inside the repository, and passes it with --add-dir."""
    monkeypatch.setattr(run_agents, "REPO_ROOT", tmp_path)
    agent = make_agent(team_dir, runtime_dir, broker)
    agent.config["add_dirs"] = ["target_app"]
    cmd = agent.command()
    folder = tmp_path / "target_app"
    assert folder.is_dir()
    assert option_value(cmd, "--add-dir") == str(folder)


def test_settings_allow_send_message_and_the_adapted_rules(team_dir, runtime_dir, broker):
    """settings() allows send_message and every rule from agent.json, as this platform adapts it."""
    agent = make_agent(team_dir, runtime_dir, broker)
    text = agent.settings()
    settings = json.loads(text)
    allow = settings["permissions"]["allow"]
    expected = ["mcp__team__send_message"]
    for rule in agent.config["allow"]:
        adapted = agent.platform.adapt_rule(rule)
        expected.append(adapted)
    assert allow == expected


def test_mcp_config_starts_the_team_server_for_this_agent(team_dir, runtime_dir, broker):
    """mcp_config() starts team_mcp.py with this Python, and tells it the agent, the broker, and the stream."""
    agent = make_agent(team_dir, runtime_dir, broker)
    text = agent.mcp_config()
    config = json.loads(text)
    server = config["mcpServers"]["team"]
    script = str(run_agents.TEAM_MCP)
    assert server["command"] == sys.executable
    assert server["args"] == [script]
    assert server["env"] == {
        "SDLC_AGENT": "amy",
        "SDLC_BROKER_URL": broker.url,
        "SDLC_STREAM": broker.stream,
    }


def test_environment_drops_the_variables_of_a_parent_claude_code_session(team_dir, runtime_dir, broker, monkeypatch):
    """environment() leaves out variables such as CLAUDECODE, and keeps the others."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("SDLC_TEST_VARIABLE", "kept")
    agent = make_agent(team_dir, runtime_dir, broker)
    environment = agent.environment()
    assert "CLAUDECODE" not in environment
    assert environment["SDLC_TEST_VARIABLE"] == "kept"


# Agent: messages and events


async def take_messages(agent: run_agents.Agent) -> None:
    """Pass the agent four messages: one to it, one to all, one from itself, and one to someone else."""
    await agent.take("1-0", {"from": "human", "to": "amy", "text": "for amy"})
    await agent.take("2-0", {"from": "ben", "to": "all", "text": "for all"})
    await agent.take("3-0", {"from": "amy", "to": "all", "text": "from amy herself"})
    await agent.take("4-0", {"from": "human", "to": "ben", "text": "for ben"})


def test_take_queues_messages_for_the_agent_and_acknowledges_the_rest(team_dir, runtime_dir, broker):
    """take() queues messages to the agent or to all from others, and acknowledges the others at once."""
    agent = make_agent(team_dir, runtime_dir, broker)
    scenario = take_messages(agent)
    asyncio.run(scenario)
    queued = list(agent.inbox)
    assert queued == [("human", "for amy", "1-0"), ("ben", "for all", "2-0")]
    assert broker.fake_async.acked == ["3-0", "4-0"]


async def read_inbox_once(agent: run_agents.Agent) -> None:
    """Run read_inbox() until the fake client has no batch left for the agent."""
    stopping = asyncio.Event()
    agent.redis.stop_when_empty = stopping
    await agent.create_group()
    await agent.read_inbox(stopping)


def test_read_inbox_reads_unfinished_messages_first_then_new_ones(team_dir, runtime_dir, broker):
    """read_inbox() asks for unfinished messages from id 0 first, then from the last id it got, and queues them."""
    agent = make_agent(team_dir, runtime_dir, broker)
    broker.fake_async.add_batch("agent:amy", [("5-0", {"from": "human", "to": "amy", "text": "unfinished"})])
    scenario = read_inbox_once(agent)
    asyncio.run(scenario)
    assert broker.fake_async.cursors[0] == "0"
    assert broker.fake_async.cursors[1] == "5-0"
    queued = list(agent.inbox)
    assert queued == [("human", "unfinished", "5-0")]


async def create_group_twice(agent: run_agents.Agent) -> None:
    """Create the agent's consumer group twice."""
    await agent.create_group()
    await agent.create_group()


def test_create_group_accepts_a_group_that_exists(team_dir, runtime_dir, broker):
    """create_group() does not fail when the group exists already, as it does after a restart."""
    agent = make_agent(team_dir, runtime_dir, broker)
    scenario = create_group_twice(agent)
    asyncio.run(scenario)
    assert broker.fake_async.groups == {"agent:amy"}


def test_requeue_unanswered_puts_the_message_back_in_front(team_dir, runtime_dir, broker):
    """requeue_unanswered() puts the message in flight back at the front of the queue."""
    agent = make_agent(team_dir, runtime_dir, broker)
    agent.send("human", "second", "2-0")
    agent.in_flight = ("human", "first", "1-0")
    agent.requeue_unanswered()
    queued = list(agent.inbox)
    assert queued == [("human", "first", "1-0"), ("human", "second", "2-0")]
    assert agent.in_flight is None


async def finish_a_turn(agent: run_agents.Agent) -> None:
    """Finish a turn for message 7-0 with a result event that reports a new session id."""
    agent.in_flight = ("human", "hello", "7-0")
    await agent.finish_turn({"type": "result", "session_id": "reported-id"})


def test_finish_turn_counts_the_turn_and_acknowledges_the_message(team_dir, runtime_dir, broker):
    """finish_turn() counts the turn, keeps the reported session id, sets idle, acknowledges, and ends the turn."""
    agent = make_agent(team_dir, runtime_dir, broker)
    scenario = finish_a_turn(agent)
    asyncio.run(scenario)
    assert agent.state["turns"] == 1
    assert agent.state["session_id"] == "reported-id"
    assert agent.status == "idle"
    assert broker.fake_async.acked == ["7-0"]
    assert agent.turn_over.is_set()
    saved = agent.files.read_state()
    assert saved["turns"] == 1


def test_show_block_saves_what_the_agent_did_last(team_dir, runtime_dir, broker, capsys):
    """show_block() prints text and tool calls, and saves them as the last activity."""
    agent = make_agent(team_dir, runtime_dir, broker)
    agent.show_block({"type": "text", "text": "  Writing the tests.\nMore."})
    assert agent.state["activity"] == "Writing the tests."
    agent.show_block({"type": "tool_use", "name": "mcp__team__send_message", "input": {"to": "ben"}})
    assert agent.state["activity"] == "sent a message to ben"
    agent.show_block({"type": "tool_use", "name": "Read", "input": {"file_path": "notes.md"}})
    assert agent.state["activity"] == "Read notes.md"
    output = capsys.readouterr().out
    assert "[amy] Writing the tests." in output
    assert "[amy] -> Read notes.md" in output


# Agent: whole sessions with the fake CLI


async def run_until_turns(agent: run_agents.Agent, turns: int) -> None:
    """Run the agent's session until it has finished the given number of turns, then stop it."""
    stopping = asyncio.Event()
    keeping = agent.keep_alive(stopping)
    task = asyncio.create_task(keeping)
    for attempt in range(300):
        if agent.state.get("turns", 0) >= turns:
            break
        await asyncio.sleep(0.05)
    stopping.set()
    await asyncio.wait_for(task, timeout=30)


def test_a_session_answers_a_message_and_closes_on_stop(team_dir, runtime_dir, broker, fake_cli):
    """The agent starts the fake CLI, writes the message to it, logs the answer, acknowledges, and closes the CLI."""
    agent = make_agent(team_dir, runtime_dir, broker)
    agent.send("human", "Hello → ✓", "1-0")
    scenario = run_until_turns(agent, 1)
    asyncio.run(scenario)
    assert agent.state["turns"] == 1
    assert broker.fake_async.acked == ["1-0"]
    assert agent.status == "offline"
    assert agent.proc.returncode is not None
    kinds = []
    for event in read_events(agent.files):
        kinds.append(event["type"])
    assert "assistant" in kinds
    assert "result" in kinds


def crash_once_command(agent: run_agents.Agent) -> list[str]:
    """Return the fake CLI's command line with --crash-once, and a marker file in the agent's runtime folder."""
    script = str(FAKE_CLAUDE)
    marker = agent.files.runtime / "crashed"
    marker_text = str(marker)
    session_id = agent.state["session_id"]
    return [sys.executable, script, session_id, "--crash-once", marker_text]


def test_a_crashed_session_restarts_and_answers_the_message_again(team_dir, runtime_dir, broker, fake_cli, monkeypatch):
    """When the CLI exits during a turn, the agent puts the message back, starts the CLI again, and answers it."""
    monkeypatch.setattr(run_agents.Agent, "command", crash_once_command)
    agent = make_agent(team_dir, runtime_dir, broker)
    agent.send("human", "Please answer", "1-0")
    scenario = run_until_turns(agent, 1)
    asyncio.run(scenario)
    assert agent.state["turns"] == 1
    assert broker.fake_async.acked == ["1-0"]
    marker = agent.files.runtime / "crashed"
    assert marker.exists()
