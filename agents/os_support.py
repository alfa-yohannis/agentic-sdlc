"""What the agent runner does differently on each operating system.

The runner (run_agents.py) needs a few things that Linux and macOS do one way
and Windows another way: locking a file, asking a running process to stop,
reading commands from the terminal, starting child processes in a group of
their own, and the paths inside a Python virtual environment.

The Platform class lists these things. PosixPlatform does them for Linux and
macOS, and WindowsPlatform does them for Windows. current_platform() returns
the one for the computer the code runs on. Importing this module only loads
the system libraries that the current operating system needs.
"""

from __future__ import annotations

import abc
import asyncio
import os
import signal
import subprocess
import threading
from pathlib import Path

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        """The Windows OVERLAPPED structure, which says where in a file a lock starts."""

        _fields_ = [
            ("internal", ctypes.c_size_t),
            ("internal_high", ctypes.c_size_t),
            ("offset", wintypes.DWORD),
            ("offset_high", wintypes.DWORD),
            ("event", wintypes.HANDLE),
        ]
else:
    import fcntl


def current_platform(runtime_dir: Path) -> Platform:
    """Return the Platform for the operating system this code runs on.

    On Windows, requests to stop the runner go through a file in runtime_dir.
    """
    if os.name == "nt":
        stop_file = runtime_dir / "run_agents.stop"
        return WindowsPlatform(stop_file)
    return PosixPlatform()


class Platform(abc.ABC):
    """Everything the runner does differently on each operating system.

    Each subclass does these things for one family of operating systems. The
    attributes say how to start a child process in a group of its own, so
    that Ctrl+C in the terminal reaches only the process that started it:

        new_session     the start_new_session argument of subprocess.Popen
        creation_flags  the creationflags argument of subprocess.Popen
        prompt_note     text added to every agent's system prompt
    """

    def __init__(self) -> None:
        """Set the attributes to values that change nothing. Subclasses change them."""
        self.new_session = False
        self.creation_flags = 0
        self.prompt_note = ""

    def adapt_rule(self, rule: str) -> str:
        """Return the permission rule from agent.json, changed to the commands this system uses."""
        return rule

    @abc.abstractmethod
    def try_lock(self, file, shared: bool = False) -> bool:
        """Try to lock the open file, without waiting.

        Many processes can hold a shared lock at the same time, but only one
        process can hold an exclusive lock. Return True if this process now
        holds the lock, or False if another process holds a lock in the way.
        """

    @abc.abstractmethod
    def unlock(self, file) -> None:
        """Release the lock that try_lock() took on the open file."""

    @abc.abstractmethod
    def in_terminal(self, stream) -> bool:
        """Return whether the stream reads from a terminal in which this process runs in the foreground."""

    @abc.abstractmethod
    def watch_terminal(self, loop: asyncio.AbstractEventLoop, stream, on_line) -> None:
        """Make the event loop call on_line(line) for every line typed into the terminal."""

    @abc.abstractmethod
    async def handle_stop_requests(self, stopping: asyncio.Event) -> None:
        """Set the stopping event when Ctrl+C or request_stop() asks this runner to stop.

        Return once the event is set, by this method or by anything else.
        """

    @abc.abstractmethod
    def request_stop(self, pid: int) -> None:
        """Ask the runner with this pid to close its agents and exit. Do not wait for it."""

    @abc.abstractmethod
    def kill(self, pid: int) -> None:
        """End the process with this pid at once, without letting it clean up."""

    def forget_stop_request(self) -> None:
        """Remove a stop request that a killed runner left behind. Do nothing by default."""


class PosixPlatform(Platform):
    """Linux and macOS: flock() file locks, signals, and an event loop that can watch the terminal."""

    def __init__(self) -> None:
        """Start child processes in a session of their own."""
        super().__init__()
        self.new_session = True
        self.loop = None
        self.terminal = None
        self.on_line = None

    def try_lock(self, file, shared: bool = False) -> bool:
        """Try to take a shared or exclusive flock() lock on the file. Return False if it is in use."""
        if shared:
            mode = fcntl.LOCK_SH | fcntl.LOCK_NB
        else:
            mode = fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(file, mode)
        except BlockingIOError:
            return False
        return True

    def unlock(self, file) -> None:
        """Release the flock() lock on the file."""
        fcntl.flock(file, fcntl.LOCK_UN)

    def in_terminal(self, stream) -> bool:
        """Return whether the stream is a terminal whose foreground process group is this process's group."""
        if not stream:
            return False
        try:
            if not stream.isatty():
                return False
            descriptor = stream.fileno()
            foreground_group = os.tcgetpgrp(descriptor)
        except OSError:
            return False
        return foreground_group == os.getpgrp()

    def watch_terminal(self, loop: asyncio.AbstractEventLoop, stream, on_line) -> None:
        """Make the event loop call read_terminal_line() whenever the terminal has input."""
        self.loop = loop
        self.terminal = stream
        self.on_line = on_line
        descriptor = stream.fileno()
        loop.add_reader(descriptor, self.read_terminal_line)

    def read_terminal_line(self) -> None:
        """Read one line from the terminal and pass it to on_line. At the end of input, stop watching the terminal."""
        line = self.terminal.readline()
        if line:
            self.on_line(line)
            return
        descriptor = self.terminal.fileno()
        self.loop.remove_reader(descriptor)

    async def handle_stop_requests(self, stopping: asyncio.Event) -> None:
        """Make SIGINT (Ctrl+C) and SIGTERM (from request_stop()) set the stopping event, then wait for it."""
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, stopping.set)
        loop.add_signal_handler(signal.SIGTERM, stopping.set)
        await stopping.wait()

    def request_stop(self, pid: int) -> None:
        """Send SIGTERM to the runner, which then closes its agents and exits."""
        os.kill(pid, signal.SIGTERM)

    def kill(self, pid: int) -> None:
        """Send SIGKILL to the process."""
        os.kill(pid, signal.SIGKILL)


class WindowsPlatform(Platform):
    """Windows: Win32 file locks, a stop file instead of SIGTERM, and a thread that reads the console."""

    # Windows file locks are mandatory: no other process can read the bytes
    # that a lock covers. The lock covers one byte far past the end of the
    # lock file, so the runner's pid in the file stays readable.
    LOCK_OFFSET = 1 << 20
    LOCKFILE_FAIL_IMMEDIATELY = 0x1
    LOCKFILE_EXCLUSIVE_LOCK = 0x2
    ERROR_LOCK_VIOLATION = 33

    # The permission rules in agent.json and the commands in team.md are
    # written for Linux and macOS. On Windows, a virtual environment keeps its
    # programs in Scripts/ instead of bin/, and python3 is often only a stub
    # that offers to install Python from the Microsoft Store.
    PROMPT_NOTE = """

## Windows

This computer runs Windows, and the Bash tool runs Git Bash. Wherever the
instructions say `.venv/bin/`, use `.venv/Scripts/` with forward slashes, for
example `.venv/Scripts/python -m pytest`, and use `python` instead of
`python3`, for example `python -m venv .venv`. Only these forms are allowed.
"""

    def __init__(self, stop_file: Path) -> None:
        """Remember where stop requests go, and load the Win32 functions for locks and the console."""
        super().__init__()
        self.creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.prompt_note = self.PROMPT_NOTE
        self.stop_file = stop_file
        self.loop = None
        self.stopping = None
        self.terminal = None
        self.on_line = None
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        overlapped_pointer = ctypes.POINTER(Overlapped)
        dword_pointer = ctypes.POINTER(wintypes.DWORD)
        self.kernel32.LockFileEx.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, overlapped_pointer)
        self.kernel32.UnlockFileEx.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, overlapped_pointer)
        self.kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, dword_pointer)

    def adapt_rule(self, rule: str) -> str:
        """Return the rule with .venv/bin/ changed to .venv/Scripts/ and python3 changed to python."""
        rule = rule.replace(".venv/bin/", ".venv/Scripts/")
        rule = rule.replace("python3 ", "python ")
        return rule

    def try_lock(self, file, shared: bool = False) -> bool:
        """Try to lock one byte at LOCK_OFFSET with LockFileEx. Return False if another process holds it."""
        flags = self.LOCKFILE_FAIL_IMMEDIATELY
        if not shared:
            flags = flags | self.LOCKFILE_EXCLUSIVE_LOCK
        handle = self.handle_of(file)
        where = Overlapped(offset=self.LOCK_OFFSET)
        # The arguments after the flags: a reserved 0, then the length of the
        # locked range, 1 byte, in its low and high parts.
        locked = self.kernel32.LockFileEx(handle, flags, 0, 1, 0, where)
        if locked:
            return True
        error = ctypes.get_last_error()
        if error != self.ERROR_LOCK_VIOLATION:
            raise ctypes.WinError(error)
        return False

    def unlock(self, file) -> None:
        """Release the byte that try_lock() locked."""
        handle = self.handle_of(file)
        where = Overlapped(offset=self.LOCK_OFFSET)
        self.kernel32.UnlockFileEx(handle, 0, 1, 0, where)

    def in_terminal(self, stream) -> bool:
        """Return whether the stream is a console. isatty() alone is not enough: it is also true for NUL."""
        if not stream:
            return False
        try:
            if not stream.isatty():
                return False
            handle = self.handle_of(stream)
        except OSError:
            return False
        mode = wintypes.DWORD()
        is_console = self.kernel32.GetConsoleMode(handle, mode)
        return bool(is_console)

    def watch_terminal(self, loop: asyncio.AbstractEventLoop, stream, on_line) -> None:
        """Start a thread that reads the console, because the Windows event loop cannot watch it."""
        self.loop = loop
        self.terminal = stream
        self.on_line = on_line
        reader = threading.Thread(target=self.read_terminal_lines, daemon=True)
        reader.start()

    def read_terminal_lines(self) -> None:
        """Read lines from the console until the end of input, and have the event loop pass each one to on_line.

        This runs in its own thread, which ends when the input ends or the process exits.
        """
        for line in self.terminal:
            self.loop.call_soon_threadsafe(self.on_line, line)

    async def handle_stop_requests(self, stopping: asyncio.Event) -> None:
        """Make Ctrl+C and Ctrl+Break set the stopping event, and set it when the stop file appears.

        The Windows event loop cannot take signal handlers, and Windows has no
        SIGTERM, so request_stop() creates the stop file instead. This checks
        for the file twice a second, deletes it when it appears, and returns
        once the event is set.
        """
        self.loop = asyncio.get_running_loop()
        self.stopping = stopping
        signal.signal(signal.SIGINT, self.on_signal)
        signal.signal(signal.SIGBREAK, self.on_signal)
        while not stopping.is_set():
            if self.stop_file.exists():
                self.stop_file.unlink(missing_ok=True)
                stopping.set()
            else:
                await asyncio.sleep(0.5)

    def on_signal(self, number, frame) -> None:
        """Have the event loop set the stopping event. Python calls this on Ctrl+C or Ctrl+Break."""
        self.loop.call_soon_threadsafe(self.stopping.set)

    def request_stop(self, pid: int) -> None:
        """Create the stop file, which the runner watches.

        os.kill() would end the runner at once and leave its agents running.
        """
        self.stop_file.touch()

    def kill(self, pid: int) -> None:
        """End the process at once. On Windows, os.kill() does that whatever the signal."""
        os.kill(pid, signal.SIGTERM)

    def forget_stop_request(self) -> None:
        """Delete the stop file, if a killed runner left one behind."""
        self.stop_file.unlink(missing_ok=True)

    @staticmethod
    def handle_of(file) -> int:
        """Return the Win32 handle of an open Python file."""
        descriptor = file.fileno()
        return msvcrt.get_osfhandle(descriptor)
