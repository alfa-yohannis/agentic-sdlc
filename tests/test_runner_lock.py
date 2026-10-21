"""Tests for RunnerLock, the lock file that lets only one runner work at a time."""

import os
from pathlib import Path

import os_support
import run_agents


def make_lock(tmp_path: Path) -> run_agents.RunnerLock:
    """Return a RunnerLock on run_agents.pid in a runtime folder under tmp_path."""
    platform = os_support.current_platform(tmp_path)
    path = tmp_path / "runtime" / "run_agents.pid"
    return run_agents.RunnerLock(path, platform)


def test_nobody_holds_a_lock_whose_file_does_not_exist(tmp_path):
    """holder() is None before any runner has created the lock file."""
    lock = make_lock(tmp_path)
    assert lock.holder() is None


def test_acquire_writes_this_process_pid_for_others_to_read(tmp_path):
    """acquire() creates the folder and the file, writes this process's pid, and others read it with holder()."""
    lock = make_lock(tmp_path)
    other = make_lock(tmp_path)
    pid = os.getpid()
    assert lock.acquire() is True
    try:
        assert other.holder() == pid
        text = lock.path.read_text()
        assert text == str(pid)
    finally:
        lock.release()


def test_only_one_runner_can_acquire_the_lock(tmp_path):
    """While one RunnerLock holds the lock, acquire() on another one returns False."""
    lock = make_lock(tmp_path)
    other = make_lock(tmp_path)
    assert lock.acquire() is True
    try:
        assert other.acquire() is False
    finally:
        lock.release()


def test_release_empties_the_file_and_frees_the_lock(tmp_path):
    """release() empties the lock file, after which nobody holds the lock and another runner can take it."""
    lock = make_lock(tmp_path)
    other = make_lock(tmp_path)
    lock.acquire()
    lock.release()
    assert other.holder() is None
    assert lock.path.read_text() == ""
    assert other.acquire() is True
    other.release()


def test_holder_is_zero_while_the_runner_has_not_written_its_pid(tmp_path):
    """holder() returns 0 when the lock is held but the file has no pid in it yet."""
    lock = make_lock(tmp_path)
    other = make_lock(tmp_path)
    lock.acquire()
    try:
        lock.file.truncate(0)
        lock.file.flush()
        assert other.holder() == 0
    finally:
        lock.release()
