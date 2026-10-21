"""Tests for os_support.py: what the runner does differently on Linux and macOS and on Windows.

Tests marked windows_only or posix_only run only on that kind of system. The
others run everywhere, against the platform of the computer they run on.
"""

import asyncio
import os
import signal
import subprocess

import pytest

import os_support

WINDOWS = os.name == "nt"
windows_only = pytest.mark.skipif(not WINDOWS, reason="Windows only")
posix_only = pytest.mark.skipif(WINDOWS, reason="Linux and macOS only")


def test_current_platform_matches_the_operating_system(tmp_path):
    """current_platform() returns WindowsPlatform on Windows and PosixPlatform elsewhere."""
    platform = os_support.current_platform(tmp_path)
    if WINDOWS:
        assert isinstance(platform, os_support.WindowsPlatform)
    else:
        assert isinstance(platform, os_support.PosixPlatform)


def test_posix_platform_keeps_rules_and_starts_children_in_a_new_session():
    """PosixPlatform keeps permission rules as they are, adds no prompt note, and starts children in a new session."""
    platform = os_support.PosixPlatform()
    rule = platform.adapt_rule("Bash(.venv/bin/python *)")
    assert rule == "Bash(.venv/bin/python *)"
    assert platform.new_session is True
    assert platform.creation_flags == 0
    assert platform.prompt_note == ""


@windows_only
def test_windows_platform_rewrites_virtual_environment_rules(tmp_path):
    """WindowsPlatform changes .venv/bin/ to .venv/Scripts/ and python3 to python, and leaves other rules alone."""
    platform = os_support.WindowsPlatform(tmp_path / "run_agents.stop")
    assert platform.adapt_rule("Bash(.venv/bin/pytest *)") == "Bash(.venv/Scripts/pytest *)"
    assert platform.adapt_rule("Bash(python3 -m venv *)") == "Bash(python -m venv *)"
    assert platform.adapt_rule("Bash(cd *)") == "Bash(cd *)"


@windows_only
def test_windows_platform_uses_a_new_process_group_and_explains_the_paths(tmp_path):
    """WindowsPlatform starts children in a new process group, and its prompt note explains .venv/Scripts/."""
    platform = os_support.WindowsPlatform(tmp_path / "run_agents.stop")
    assert platform.creation_flags == subprocess.CREATE_NEW_PROCESS_GROUP
    assert platform.new_session is False
    assert ".venv/Scripts/" in platform.prompt_note


def test_an_exclusive_lock_keeps_out_every_other_lock(tmp_path):
    """While one handle holds the exclusive lock, another handle gets neither a shared nor an exclusive lock."""
    platform = os_support.current_platform(tmp_path)
    path = tmp_path / "lock"
    path.write_text("")
    holder = open(path, "a+")
    other = open(path)
    try:
        assert platform.try_lock(holder) is True
        assert platform.try_lock(other, shared=True) is False
        assert platform.try_lock(other) is False
        platform.unlock(holder)
        assert platform.try_lock(other, shared=True) is True
    finally:
        holder.close()
        other.close()


def test_shared_locks_can_be_held_together_but_keep_out_an_exclusive_lock(tmp_path):
    """Two handles can hold shared locks at the same time, and a third then gets no exclusive lock."""
    platform = os_support.current_platform(tmp_path)
    path = tmp_path / "lock"
    path.write_text("")
    first = open(path)
    second = open(path)
    third = open(path, "a+")
    try:
        assert platform.try_lock(first, shared=True) is True
        assert platform.try_lock(second, shared=True) is True
        assert platform.try_lock(third) is False
    finally:
        first.close()
        second.close()
        third.close()


def test_a_pipe_is_not_a_terminal(tmp_path):
    """in_terminal() is False for a pipe and for no stream at all."""
    platform = os_support.current_platform(tmp_path)
    read_end, write_end = os.pipe()
    stream = os.fdopen(read_end)
    try:
        assert platform.in_terminal(stream) is False
        assert platform.in_terminal(None) is False
    finally:
        stream.close()
        os.close(write_end)


@windows_only
def test_nul_is_not_a_console(tmp_path):
    """On Windows, isatty() is true for NUL, which the web server gives the runner as input, but in_terminal() is not."""
    platform = os_support.current_platform(tmp_path)
    with open("NUL") as nul:
        assert nul.isatty() is True
        assert platform.in_terminal(nul) is False


async def collect_terminal_lines(platform: os_support.Platform) -> list[str]:
    """Write two lines into a pipe, let the platform watch the pipe as the terminal, and return the lines it passed on."""
    read_end, write_end = os.pipe()
    os.write(write_end, b"@amy hi\nstatus\n")
    os.close(write_end)
    stream = os.fdopen(read_end)
    lines = []
    loop = asyncio.get_running_loop()
    platform.watch_terminal(loop, stream, lines.append)
    for attempt in range(100):
        if len(lines) == 2:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)
    stream.close()
    return lines


def test_watch_terminal_passes_every_line_on(tmp_path):
    """watch_terminal() passes each line to on_line in the event loop, and stops at the end of input."""
    platform = os_support.current_platform(tmp_path)
    scenario = collect_terminal_lines(platform)
    lines = asyncio.run(scenario)
    assert lines == ["@amy hi\n", "status\n"]


async def stop_through(platform: os_support.Platform, how: str) -> bool:
    """Run handle_stop_requests(), then ask this process to stop, and return whether the stopping event got set.

    With how="ctrl_c", raise SIGINT, which is what Ctrl+C does. With
    how="request", call request_stop() on this process, which is what
    `run_agents.py --stop` does.
    """
    stopping = asyncio.Event()
    handling = platform.handle_stop_requests(stopping)
    task = asyncio.create_task(handling)
    await asyncio.sleep(0.2)
    if how == "ctrl_c":
        signal.raise_signal(signal.SIGINT)
    else:
        pid = os.getpid()
        platform.request_stop(pid)
    await asyncio.wait_for(task, timeout=5)
    return stopping.is_set()


def test_a_stop_request_sets_the_stopping_event(tmp_path, restore_signals):
    """request_stop() makes handle_stop_requests() set the stopping event. On Windows, the stop file is gone afterwards."""
    platform = os_support.current_platform(tmp_path)
    scenario = stop_through(platform, "request")
    stopped = asyncio.run(scenario)
    assert stopped is True
    if WINDOWS:
        assert not platform.stop_file.exists()


def test_ctrl_c_sets_the_stopping_event(tmp_path, restore_signals):
    """Ctrl+C (SIGINT) makes handle_stop_requests() set the stopping event."""
    platform = os_support.current_platform(tmp_path)
    scenario = stop_through(platform, "ctrl_c")
    stopped = asyncio.run(scenario)
    assert stopped is True


@windows_only
def test_forget_stop_request_deletes_a_stop_file_left_behind(tmp_path):
    """forget_stop_request() deletes a stop file that a killed runner never acted on."""
    platform = os_support.WindowsPlatform(tmp_path / "run_agents.stop")
    platform.stop_file.touch()
    platform.forget_stop_request()
    assert not platform.stop_file.exists()
