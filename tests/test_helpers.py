"""Tests for the small helper functions in run_agents.py."""

import asyncio
import os
import re
import sys
import threading

import run_agents


def test_first_line_returns_the_first_line_of_the_stripped_text():
    """first_line() strips the text, then keeps its first line."""
    line = run_agents.first_line("\n  hello\nworld\n")
    assert line == "hello"


def test_first_line_cuts_a_long_line_to_the_width():
    """first_line() cuts a line that is too long, and ends it with "..."."""
    line = run_agents.first_line("x" * 150, width=20)
    assert line == "x" * 17 + "..."
    assert len(line) == 20


def test_first_line_of_blank_text_is_empty():
    """first_line() returns "" for text without any line."""
    line = run_agents.first_line("   \n ")
    assert line == ""


def test_describe_picks_the_first_main_input_without_the_repository_path():
    """describe() prefers file_path to command, and drops the repository's folder from the path."""
    path = run_agents.REPO_ROOT / "agents" / "notes.md"
    path_text = str(path)
    description = run_agents.describe({"command": "ls", "file_path": path_text})
    assert description == f"agents{os.sep}notes.md"


def test_describe_without_a_main_input_is_empty():
    """describe() returns "" when the tool call has none of the inputs it looks for."""
    description = run_agents.describe({"other": "value"})
    assert description == ""


def test_read_json_returns_an_empty_dict_for_a_missing_or_broken_file(tmp_path):
    """read_json() returns {} instead of failing when the file is missing or is not JSON."""
    missing = tmp_path / "missing.json"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert run_agents.read_json(missing) == {}
    assert run_agents.read_json(broken) == {}


def test_write_json_and_read_json_keep_non_ascii_text(tmp_path):
    """write_json() and read_json() keep any character, and leave no temporary file behind."""
    path = tmp_path / "state.json"
    data = {"activity": "café \u2192 \u2713"}
    run_agents.write_json(path, data)
    assert run_agents.read_json(path) == data
    temporary = path.with_suffix(".tmp")
    assert not temporary.exists()


def test_write_json_waits_for_a_reader_to_close_the_file(tmp_path):
    """write_json() replaces a file that another reader has open, retrying until the reader closes it.

    On Windows the first tries fail. On Linux and macOS the first one works.
    """
    path = tmp_path / "state.json"
    run_agents.write_json(path, {"version": 1})
    reader = open(path, encoding="utf-8")
    closer = threading.Timer(0.2, reader.close)
    closer.start()
    run_agents.write_json(path, {"version": 2})
    closer.join()
    reader.close()
    assert run_agents.read_json(path) == {"version": 2}


def test_now_is_an_iso_timestamp_in_utc():
    """now() returns the time in ISO 8601 format, to the second, in UTC."""
    stamp = run_agents.now()
    pattern = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00"
    assert re.fullmatch(pattern, stamp)


def test_new_session_state_has_a_new_id_and_no_turns():
    """new_session_state() starts every session with a different id and no turns."""
    first = run_agents.new_session_state()
    second = run_agents.new_session_state()
    assert first["turns"] == 0
    assert first["session_id"] != second["session_id"]


async def check_wait_for_event() -> None:
    """Wait for an event that is not set, which times out, and for a set one, which returns at once."""
    event = asyncio.Event()
    assert await run_agents.wait_for_event(event, 0.05) is False
    event.set()
    assert await run_agents.wait_for_event(event, 5) is True


def test_wait_for_event_says_whether_the_event_was_set():
    """wait_for_event() returns False after a timeout and True once the event is set."""
    scenario = check_wait_for_event()
    asyncio.run(scenario)


async def check_wait_for_exit() -> None:
    """Start a process that sleeps, see the wait time out, then kill it and see the wait succeed."""
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
    assert await run_agents.wait_for_exit(process, 0.1) is False
    process.kill()
    assert await run_agents.wait_for_exit(process, 10) is True


def test_wait_for_exit_says_whether_the_process_exited():
    """wait_for_exit() returns False while the process runs, and True once it has exited."""
    scenario = check_wait_for_exit()
    asyncio.run(scenario)


def test_print_status_prints_the_runner_and_one_line_per_agent(capsys):
    """print_status() names the runner's pid and prints each agent's status, pid, session, and turns."""
    agent = {"name": "amy", "label": "Agent A", "role": "Tester", "status": "idle",
             "pid": 42, "session_id": "0123456789abcdef", "turns": 3}
    run_agents.print_status({"running": True, "pid": 7, "agents": [agent]})
    output = capsys.readouterr().out
    assert "Agents are running (runner pid 7)." in output
    assert "amy" in output
    assert "idle" in output
    assert "session 01234567" in output
    assert "turns 3" in output
