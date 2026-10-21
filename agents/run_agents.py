#!/usr/bin/env python3
"""Start the agent sessions, keep them alive, and pass messages to them.

Every folder in agents/ that has an agent.json is one agent. For each agent,
this script starts one Claude CLI process in stream-json mode with the agent's
folder as its working directory, so the session loads that folder's CLAUDE.md
as its context. The process stays open between messages and keeps its
conversation. If it exits, the script starts it again on the same session.

Agents talk through a Redis broker (see broker/compose.yaml). Every message
goes into one Redis stream. Each agent has its own consumer group on that
stream, which works as its inbox: this script delivers each message addressed
to the agent as a new turn, and acknowledges it once the turn is over.
Agents send messages with the send_message tool from agents/team_mcp.py.

Run it with the server's virtual environment, which has the Redis client:

    python agents/run_agents.py           start the broker and the agents (Ctrl+C stops the agents)
    python agents/run_agents.py --status  show what each agent is doing
    python agents/run_agents.py --stop    stop the agents and keep their sessions and messages
    python agents/run_agents.py --reset   stop the agents and clear their sessions and messages

When it runs in a terminal, type `@alice <message>` to message one agent,
`@all <message>` to message all of them, `status`, or `quit`.

Session ids, event logs, and the lock file live in agents/.runtime/.

The code is organized in these classes:

    Runner      the whole team: starts the agents, stops them, and reports on them
    Agent       one agent's Claude CLI session while the runner runs
    AgentFiles  one agent's folder, its settings, and the files the runner keeps for it
    Broker      the Redis stream that carries the messages
    RunnerLock  the lock file that lets only one runner work at a time
    Console     the commands typed into the runner's terminal

What differs between Linux, macOS, and Windows is in os_support.py. Running
this file as a script does what the command line asks. Importing it, as the
web server does, only defines the classes.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from os_support import Platform, current_platform

try:
    import redis
    import redis.asyncio as aioredis
except ImportError:  # --status works without the Redis client
    redis = aioredis = None

AGENTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_DIR.parent
RUNTIME_DIR = AGENTS_DIR / ".runtime"
TEAM_MCP = AGENTS_DIR / "team_mcp.py"
BROKER_COMPOSE = REPO_ROOT / "broker" / "compose.yaml"
BROKER_URL = os.environ.get("SDLC_BROKER_URL", "redis://127.0.0.1:6380/0")
STREAM = "sdlc:messages"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
# Context every agent gets on top of its own CLAUDE.md. A CLAUDE.md import
# cannot pull it in, because the CLI skips imports from outside the session's
# folder when it runs without a terminal.
TEAM_CONTEXT = AGENTS_DIR / "shared_context" / "team.md"

# One stream-json line can hold a whole file that the agent read or wrote.
LINE_LIMIT = 64 * 1024 * 1024

# Variables that tie a process to the Claude Code session that started it.
# They are dropped so that each agent is a session of its own, even when this
# script is started from a terminal that Claude Code opened.
PARENT_SESSION_VARS = {
    "AI_AGENT",
    "CLAUDECODE",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_EFFORT",
    "CLAUDE_PID",
}

PALETTE = (35, 34, 33, 36, 32, 31)
USE_COLOR = sys.stdout.isatty()


class RunnerError(Exception):
    """A problem that keeps the runner from doing what it was asked.

    The message says what went wrong, in words meant for the user.
    """


class RunnerLock:
    """The lock file that only one runner at a time can hold.

    The runner that holds the lock writes its pid into the file. Any other
    process can read that pid, and can find out whether the lock is held.
    """

    def __init__(self, path: Path, platform: Platform) -> None:
        """Remember where the lock file is. Do not touch the file yet."""
        self.path = path
        self.platform = platform
        self.file = None

    def holder(self) -> int | None:
        """Return the pid of the runner that holds the lock.

        Return 0 if that runner has not written its pid yet, or None if no
        runner holds the lock. To find out, briefly take a shared lock.
        """
        try:
            file = open(self.path)
        except FileNotFoundError:
            return None
        with file:
            if self.platform.try_lock(file, shared=True):
                self.platform.unlock(file)
                return None
            text = file.read()
        text = text.strip()
        if text.isdigit():
            return int(text)
        return 0

    def acquire(self) -> bool:
        """Lock the lock file for this process and write this process's pid into it.

        Create the file and its folder if needed. Return False, and change
        nothing, if another runner holds the lock.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = open(self.path, "a+")
        if not self.platform.try_lock(file):
            file.close()
            return False
        pid = os.getpid()
        pid_text = str(pid)
        file.seek(0)
        file.truncate()
        file.write(pid_text)
        file.flush()
        self.file = file
        return True

    def release(self) -> None:
        """Empty the lock file, unlock it, and close it, so that another runner can start."""
        self.file.truncate(0)
        self.platform.unlock(self.file)
        self.file.close()
        self.file = None


class Broker:
    """The Redis stream that carries every message between the human and the agents.

    Redis runs in a Docker container (broker/compose.yaml). ensure_running()
    starts the container when the broker does not answer.
    """

    def __init__(self, url: str = BROKER_URL, stream: str = STREAM) -> None:
        """Remember the broker's address and the stream's name, and create a client. Do not connect yet."""
        self.url = url
        self.stream = stream
        self.client = None
        if redis is not None:
            self.client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)

    def async_client(self):
        """Return a new asyncio Redis client for the runner's event loop. Do not connect yet."""
        self.require_client()
        return aioredis.Redis.from_url(self.url, decode_responses=True)

    def require_client(self) -> None:
        """Raise RunnerError if the Redis client package is not installed."""
        if self.client is None:
            raise RunnerError("The Redis client is missing. Run this with the server's virtual environment.")

    def answers(self) -> bool:
        """Send a PING to the broker. Return whether it answered."""
        try:
            self.client.ping()
        except redis.RedisError:
            return False
        return True

    def ensure_running(self) -> None:
        """Start the broker container with Docker Compose unless the broker answers already.

        Wait up to 30 seconds for the broker to answer. Raise RunnerError if
        it cannot be started.
        """
        self.require_client()
        if self.answers():
            return
        if shutil.which("docker") is None:
            raise RunnerError(f"The broker at {self.url} is not running and Docker is not available to start it.")
        print("Starting the broker...", flush=True)
        compose_file = str(BROKER_COMPOSE)
        result = subprocess.run(["docker", "compose", "-f", compose_file, "up", "-d"])
        if result.returncode != 0:
            raise RunnerError("Docker could not start the broker. Make sure Docker is running.")
        for attempt in range(60):
            if self.answers():
                return
            time.sleep(0.5)
        raise RunnerError(f"The broker did not answer at {self.url}.")

    def publish(self, sender: str, to: str, text: str) -> str:
        """Append a message to the stream, where its recipient's inbox finds it. Return the message's id.

        Raise redis.RedisError if the broker is down.
        """
        self.require_client()
        timestamp = now()
        fields = {"from": sender, "to": to, "text": text, "ts": timestamp}
        return self.client.xadd(self.stream, fields)

    def read(self, after: str = "0", limit: int = 500) -> dict:
        """Return up to `limit` messages after the message with the id `after`, oldest first.

        After "0", return the newest `limit` messages. The result also says
        whether the broker answered and how many messages the stream holds.
        """
        self.require_client()
        try:
            if after == "" or after == "0":
                entries = self.client.xrevrange(self.stream, count=limit)
                entries.reverse()
            else:
                entries = self.client.xrange(self.stream, min=f"({after}", count=limit)
            total = self.client.xlen(self.stream)
        except redis.RedisError:
            return {"broker": False, "total": 0, "messages": []}
        messages = []
        for message_id, fields in entries:
            message = {"id": message_id}
            message.update(fields)
            messages.append(message)
        return {"broker": True, "total": total, "messages": messages}

    def clear(self) -> None:
        """Delete the stream, with every message and every inbox position. Do nothing if the broker is down."""
        self.require_client()
        try:
            self.client.delete(self.stream)
        except redis.RedisError:
            pass


class AgentFiles:
    """One agent's folder, its settings in agent.json, and the files the runner keeps for it.

    The runner keeps three files in agents/.runtime/<name>/: session.json
    (the session id, status, and last activity), events.jsonl (everything
    the session printed), and stderr.log (the CLI's error output).
    """

    def __init__(self, folder: Path, runtime_dir: Path) -> None:
        """Remember the agent's folder and where its runtime files go. Read nothing yet."""
        self.folder = folder
        self.name = folder.name
        self.runtime = runtime_dir / self.name
        self.stderr_log = self.runtime / "stderr.log"

    def read_config(self) -> dict:
        """Return the settings in the agent's agent.json, or {} if the file is missing or broken."""
        path = self.folder / "agent.json"
        return read_json(path)

    def read_state(self) -> dict:
        """Return the saved state in session.json, or {} if there is none."""
        path = self.runtime / "session.json"
        return read_json(path)

    def write_state(self, state: dict) -> None:
        """Replace session.json with the given state."""
        path = self.runtime / "session.json"
        write_json(path, state)

    def log(self, event: dict) -> None:
        """Append the event to events.jsonl, with the current time."""
        timestamp = now()
        record = {"ts": timestamp}
        record.update(event)
        line = json.dumps(record)
        path = self.runtime / "events.jsonl"
        with open(path, "a", encoding="utf-8") as log:
            log.write(line + "\n")

    def status(self, running: bool) -> dict:
        """Return the agent's name, label, role, status, and session, for the terminal and the web page.

        When the runner is not running, the agent is offline, whatever
        session.json says.
        """
        config = self.read_config()
        state = self.read_state()
        status = "offline"
        pid = None
        if running:
            status = state.get("status", "offline")
            pid = state.get("pid")
        return {
            "name": self.name,
            "label": config.get("label", ""),
            "role": config.get("role", ""),
            "status": status,
            "pid": pid,
            "session_id": state.get("session_id"),
            "turns": state.get("turns", 0),
            "activity": state.get("activity"),
            "updated": state.get("updated"),
        }

    def clear(self) -> None:
        """Delete the agent's runtime files, so the next start begins a new conversation."""
        for name in ("session.json", "events.jsonl", "stderr.log"):
            path = self.runtime / name
            path.unlink(missing_ok=True)


class Agent:
    """One agent while the runner runs: a Claude CLI session in the agent's folder.

    The session is a `claude -p` process in stream-json mode. The agent reads
    its inbox on the broker, writes each message to the process as a new
    turn, and reads the process's events to see when the turn is over.
    """

    def __init__(self, files: AgentFiles, platform: Platform, broker: Broker, client, color: int = 0) -> None:
        """Load the agent's settings and saved session, and create its runtime folder. Start nothing.

        `client` is the runner's asyncio Redis client. Without a saved session,
        the agent gets a new session id.
        """
        self.files = files
        self.name = files.name
        self.platform = platform
        self.broker = broker
        self.redis = client
        self.color = color
        self.config = files.read_config()
        files.runtime.mkdir(parents=True, exist_ok=True)
        self.state = files.read_state()
        if not self.state.get("session_id"):
            self.state = new_session_state()
        self.status = "offline"
        self.proc: asyncio.subprocess.Process | None = None
        # Messages waiting for a turn, as (sender, text, message id).
        self.inbox: collections.deque[tuple[str, str, str | None]] = collections.deque()
        self.mail = asyncio.Event()
        self.turn_over = asyncio.Event()
        self.in_flight: tuple[str, str, str | None] | None = None
        self.turn_started = 0.0

    @property
    def group(self) -> str:
        """The name of the agent's consumer group on the stream, which is its inbox."""
        return f"agent:{self.name}"

    def send(self, sender: str, text: str, message_id: str | None = None) -> None:
        """Queue a message and wake the delivery loop. The agent reads it as soon as its current turn ends."""
        message = (sender, text, message_id)
        self.inbox.append(message)
        self.mail.set()

    def session_started(self) -> bool:
        """Return whether the session has received a message before, so the CLI must resume it."""
        if self.state.get("turns"):
            return True
        started = self.state.get("started")
        return bool(started)

    def command(self) -> list[str]:
        """Return the command line that starts this agent's Claude CLI session.

        Read team.md, and create the folders listed under add_dirs in
        agent.json if they are missing.
        """
        config = self.config
        mcp_config = self.mcp_config()
        settings = self.settings()
        permission_mode = config.get("permission_mode", "acceptEdits")
        session_id = self.state["session_id"]
        cmd = [
            CLAUDE_BIN, "-p", "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--name", self.name,
            # Load this folder's CLAUDE.md and settings but not the user's
            # global ones, and no MCP server except the team's.
            "--setting-sources", "project,local",
            "--mcp-config", mcp_config,
            "--strict-mcp-config",
            "--settings", settings,
            "--permission-mode", permission_mode,
            # Nobody is there to answer a permission prompt, so anything that
            # would ask is denied instead of leaving the session waiting.
            "--permission-prompts", "none",
        ]
        # The CLI can resume a session only once it has received a message.
        if self.session_started():
            cmd += ["--resume", session_id]
        else:
            cmd += ["--session-id", session_id]
        if TEAM_CONTEXT.exists():
            team_context = TEAM_CONTEXT.read_text(encoding="utf-8")
            cmd += ["--append-system-prompt", team_context + self.platform.prompt_note]
        if config.get("tools"):
            tools = ",".join(config["tools"])
            cmd += ["--tools", tools]
        for directory in config.get("add_dirs", []):
            path = REPO_ROOT / directory
            path.mkdir(parents=True, exist_ok=True)
            path_text = str(path)
            cmd += ["--add-dir", path_text]
        if config.get("model"):
            cmd += ["--model", config["model"]]
        if config.get("effort"):
            cmd += ["--effort", config["effort"]]
        return cmd

    def mcp_config(self) -> str:
        """Return the --mcp-config JSON, which gives the session the team's MCP server, team_mcp.py.

        The server learns from its environment which agent it serves and where
        the broker is.
        """
        script = str(TEAM_MCP)
        environment = {"SDLC_AGENT": self.name, "SDLC_BROKER_URL": self.broker.url, "SDLC_STREAM": self.broker.stream}
        team_server = {"command": sys.executable, "args": [script], "env": environment}
        config = {"mcpServers": {"team": team_server}}
        return json.dumps(config)

    def settings(self) -> str:
        """Return the --settings JSON, which allows send_message and the rules under allow in agent.json.

        The rules are adapted to this operating system first.
        """
        allow = ["mcp__team__send_message"]
        for rule in self.config.get("allow", []):
            adapted = self.platform.adapt_rule(rule)
            allow.append(adapted)
        settings = {"permissions": {"allow": allow}}
        return json.dumps(settings)

    def environment(self) -> dict[str, str]:
        """Return this process's environment without the variables that tie a process to a parent Claude Code session."""
        environment = {}
        for name, value in os.environ.items():
            if name not in PARENT_SESSION_VARS:
                environment[name] = value
        return environment

    async def keep_alive(self, stopping: asyncio.Event) -> None:
        """Run the agent's session until the stopping event is set.

        When the session exits on its own, start it again after a pause that
        doubles with every quick exit in a row. After three quick exits in a
        row, start a new session instead of resuming the old one.
        """
        quick_exits = 0
        while not stopping.is_set():
            started = time.monotonic()
            code = await self.run_session(stopping)
            if stopping.is_set():
                break
            self.requeue_unanswered()
            elapsed = time.monotonic() - started
            if elapsed < 10:
                quick_exits = quick_exits + 1
            else:
                quick_exits = 0
            if quick_exits >= 3:
                short_id = self.state["session_id"][:8]
                self.say(f"session {short_id} keeps failing, starting a new one")
                self.state = new_session_state()
                quick_exits = 0
            delay = 2 ** quick_exits
            self.say(f"exited with code {code}, restarting in {delay}s")
            await wait_for_event(stopping, delay)

    async def run_session(self, stopping: asyncio.Event) -> int | None:
        """Start the CLI process and serve it until it exits, or until the stopping event is set.

        While it runs, deliver queued messages to it and read its events. When
        the stopping event is set, close it. Return the process's exit code,
        or None if it could not start.
        """
        try:
            await self.spawn()
        except OSError as error:
            self.say(f"cannot start the Claude CLI: {error}")
            self.set_status("offline")
            return None
        # Calling an async method only creates its coroutine. create_task()
        # runs the coroutine in the background.
        reading = self.read_events()
        reader = asyncio.create_task(reading)
        delivering = self.deliver()
        writer = asyncio.create_task(delivering)
        waiting = stopping.wait()
        stop = asyncio.create_task(waiting)
        await asyncio.wait({reader, stop}, return_when=asyncio.FIRST_COMPLETED)
        if stopping.is_set():
            await self.shutdown()
        writer.cancel()
        stop.cancel()
        await asyncio.gather(reader, writer, stop, return_exceptions=True)
        code = await self.proc.wait()
        self.set_status("offline")
        return code

    def requeue_unanswered(self) -> None:
        """Put the message that the ended session was handling back at the front of the queue."""
        if self.in_flight is None:
            return
        self.inbox.appendleft(self.in_flight)
        self.in_flight = None
        self.mail.set()

    async def read_inbox(self, stopping: asyncio.Event) -> None:
        """Read the agent's consumer group on the broker until the stopping event is set.

        Queue every message addressed to this agent or to all, and acknowledge
        the others at once. While the broker is unreachable, retry every 2
        seconds.
        """
        # "0" first returns messages this agent received before but never
        # finished, for example when the runner stopped mid-turn. ">" then
        # waits for new ones.
        cursor = "0"
        while not stopping.is_set():
            streams = {self.broker.stream: cursor}
            try:
                response = await self.redis.xreadgroup(self.group, "runner", streams, count=20, block=2000)
            except redis.ResponseError as error:
                reason = str(error)
                if "NOGROUP" not in reason:
                    raise
                await self.create_group()
                continue
            except redis.ConnectionError as error:
                self.say(f"broker unreachable ({error}), retrying")
                await asyncio.sleep(2)
                continue
            entries = []
            if response:
                entries = response[0][1]
            if cursor != ">":
                if entries:
                    cursor = entries[-1][0]
                else:
                    cursor = ">"
            for message_id, fields in entries:
                await self.take(message_id, fields)

    async def take(self, message_id: str, fields: dict) -> None:
        """Queue the message if it is addressed to this agent or to all, and comes from someone else.

        Otherwise acknowledge it at once, so the inbox moves past it.
        """
        sender = fields.get("from", "?")
        recipient = fields.get("to")
        addressed = recipient == self.name or recipient == "all"
        if addressed and sender != self.name:
            text = fields.get("text", "")
            self.send(sender, text, message_id)
        else:
            await self.redis.xack(self.broker.stream, self.group, message_id)

    async def create_group(self) -> None:
        """Create the agent's consumer group on the stream, and the stream if needed. Do nothing if the group exists."""
        try:
            await self.redis.xgroup_create(self.broker.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as error:
            reason = str(error)
            if "BUSYGROUP" not in reason:
                raise

    async def spawn(self) -> None:
        """Start the agent's Claude CLI process in the agent's folder, with its errors going to stderr.log.

        Set the status to starting, then to idle once the process runs.
        Raise OSError if the CLI cannot start.
        """
        self.set_status("starting")
        cmd = self.command()
        environment = self.environment()
        with open(self.files.stderr_log, "ab") as stderr:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.files.folder,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                limit=LINE_LIMIT,
                # A process group of its own, so Ctrl+C reaches only this
                # script, which then closes the sessions one by one.
                start_new_session=self.platform.new_session,
                creationflags=self.platform.creation_flags,
            )
        if self.session_started():
            kind = "resumed"
        else:
            kind = "new"
        short_id = self.state["session_id"][:8]
        self.say(f"{kind} session {short_id}, pid {self.proc.pid}")
        self.set_status("idle")

    async def deliver(self) -> None:
        """Write queued messages to the session one at a time, each as a new turn.

        Wait for each turn to end before writing the next message. Run until
        cancelled.
        """
        while True:
            while not self.inbox:
                self.mail.clear()
                await self.mail.wait()
            self.in_flight = self.inbox.popleft()
            sender, text, message_id = self.in_flight
            self.turn_over.clear()
            self.turn_started = time.monotonic()
            self.state["started"] = True
            self.state["activity"] = f"reading a message from {sender}"
            self.set_status("working")
            summary = first_line(text)
            self.say(f"<- {sender}: {summary}")
            self.files.log({"type": "runtime", "subtype": "message", "from": sender, "text": text})
            await self.write_turn(sender, text)
            await self.turn_over.wait()

    async def write_turn(self, sender: str, text: str) -> None:
        """Write one message to the session's input as a user turn that starts with the sender's name."""
        message = {
            "type": "user",
            "session_id": self.state["session_id"],
            "parent_tool_use_id": None,
            "message": {"role": "user", "content": f"From: {sender}\n\n{text}"},
        }
        line = json.dumps(message) + "\n"
        data = line.encode()
        self.proc.stdin.write(data)
        await self.proc.stdin.drain()

    async def read_events(self) -> None:
        """Read the session's output events until the process closes its output.

        Log and show every event, and finish the turn when a result event
        arrives. Skip lines that are not JSON or are longer than LINE_LIMIT.
        """
        while True:
            try:
                line = await self.proc.stdout.readline()
            except ValueError:  # a line longer than LINE_LIMIT
                continue
            if not line:
                return
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.files.log(event)
            self.show(event)
            if event.get("type") == "result" and self.in_flight:
                await self.finish_turn(event)

    async def finish_turn(self, event: dict) -> None:
        """End the current turn after its result event.

        Count the turn, keep the session id that the CLI reported, set the
        status to idle, acknowledge the message on the broker, and let the
        delivery loop write the next message.
        """
        message_id = self.in_flight[2]
        self.in_flight = None
        turns = self.state.get("turns", 0)
        self.state["turns"] = turns + 1
        reported_id = event.get("session_id")
        if reported_id:
            self.state["session_id"] = reported_id
        self.set_status("idle")
        if message_id and self.redis:
            try:
                await self.redis.xack(self.broker.stream, self.group, message_id)
            except redis.RedisError as error:
                self.say(f"could not acknowledge message {message_id}: {error}")
        self.turn_over.set()

    async def shutdown(self) -> None:
        """Close the session's input, so the CLI exits by itself.

        If the process still runs after 10 seconds, terminate it. If it still
        runs 5 seconds later, kill it.
        """
        proc = self.proc
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
        if await wait_for_exit(proc, 10):
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        if await wait_for_exit(proc, 5):
            return
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await wait_for_exit(proc, 5)

    def set_status(self, status: str) -> None:
        """Set the agent's status (offline, starting, idle, or working), save it, and log the change."""
        self.status = status
        self.save_state()
        self.files.log({"type": "runtime", "subtype": "status", "status": status})

    def save_state(self) -> None:
        """Write the session id, turns, status, the pid of a running process, the last activity, and the time to session.json."""
        pid = None
        if self.proc is not None and self.proc.returncode is None:
            pid = self.proc.pid
        self.state["status"] = self.status
        self.state["pid"] = pid
        self.state["updated"] = now()
        self.files.write_state(self.state)

    def show(self, event: dict) -> None:
        """Print what the agent says, which tools it calls, and how each turn ends."""
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message", {})
            blocks = message.get("content", [])
            for block in blocks:
                self.show_block(block)
        elif kind == "result" and self.in_flight:
            self.show_result(event)

    def show_block(self, block: dict) -> None:
        """Print one part of an assistant message, its text or the tool it calls, and save it as the last activity."""
        kind = block.get("type")
        if kind == "text":
            text = block.get("text", "")
            text = text.strip()
            if not text:
                return
            self.say(text)
            self.state["activity"] = first_line(text)
            self.save_state()
        elif kind == "tool_use":
            tool_input = block.get("input") or {}
            name = block.get("name")
            if name == "mcp__team__send_message":
                recipient = tool_input.get("to")
                activity = f"sent a message to {recipient}"
            else:
                details = describe(tool_input)
                activity = f"{name} {details}"
                activity = activity.strip()
            self.say(f"-> {activity}")
            self.state["activity"] = activity
            self.save_state()

    def show_result(self, event: dict) -> None:
        """Print whether the turn succeeded and how long it took."""
        seconds = time.monotonic() - self.turn_started
        if event.get("is_error"):
            reason = event.get("result") or event.get("subtype")
            self.say(f"turn failed after {seconds:.0f}s: {reason}")
        else:
            self.say(f"done in {seconds:.0f}s")

    def say(self, text: str) -> None:
        """Print every line of the text with the agent's name in front, in the agent's color in a terminal."""
        if USE_COLOR and self.color:
            prefix = f"\033[{self.color}m[{self.name}]\033[0m"
        else:
            prefix = f"[{self.name}]"
        for line in text.splitlines():
            print(prefix, line, flush=True)


class Console:
    """The commands typed into the terminal where the runner runs.

    `@<agent> <message>` and `@all <message>` send a message from the human,
    `status` prints what each agent is doing, and `quit` stops the agents.
    """

    HELP = "Type @<agent> <message>, @all <message>, status, or quit."

    def __init__(self, runner: Runner, stopping: asyncio.Event) -> None:
        """Remember the runner and the event that stops it, and look up the agents' names. Read nothing yet."""
        self.runner = runner
        self.stopping = stopping
        names = runner.agent_names()
        self.names = set(names)

    def open(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start reading commands and print the help line, if this process runs in the foreground of a terminal.

        Do nothing otherwise, for example when the web server started the runner.
        """
        platform = self.runner.platform
        if not platform.in_terminal(sys.stdin):
            return
        platform.watch_terminal(loop, sys.stdin, self.handle)
        print(self.HELP, flush=True)

    def handle(self, line: str) -> None:
        """Run one command: send a message, print the status, or set the stopping event.

        Print the help line for anything else.
        """
        line = line.strip()
        if not line:
            return
        if line == "quit" or line == "exit":
            self.stopping.set()
            return
        if line == "status":
            status = self.runner.status()
            print_status(status)
            return
        if line.startswith("@"):
            target, _, text = line[1:].partition(" ")
            text = text.strip()
            known = target in self.names or target == "all"
            if known and text:
                self.runner.broker.publish("human", target, text)
                return
        print(self.HELP, flush=True)


class Runner:
    """The runner: one process that keeps a Claude CLI session alive for every agent.

    The process that runs the agents calls start(). Other processes, such as
    the web server and `run_agents.py --status`, use the same class to ask
    about the runner (status()), stop it (stop()), and clear what it kept
    (clear()).
    """

    def __init__(self, agents_dir: Path = AGENTS_DIR, runtime_dir: Path = RUNTIME_DIR,
                 broker: Broker | None = None, platform: Platform | None = None) -> None:
        """Set up the runner's parts for the given folders. Start nothing and touch no file."""
        if platform is None:
            platform = current_platform(runtime_dir)
        if broker is None:
            broker = Broker()
        self.agents_dir = agents_dir
        self.runtime_dir = runtime_dir
        self.platform = platform
        self.broker = broker
        lock_path = runtime_dir / "run_agents.pid"
        self.lock = RunnerLock(lock_path, platform)
        # The runner's output when the web server started it.
        self.log_file = runtime_dir / "run_agents.log"

    def agent_files(self) -> list[AgentFiles]:
        """Return the files of every agent, one for each folder in agents_dir that has an agent.json, sorted by name."""
        paths = self.agents_dir.glob("*/agent.json")
        paths = sorted(paths)
        agents = []
        for path in paths:
            files = AgentFiles(path.parent, self.runtime_dir)
            agents.append(files)
        return agents

    def agent_names(self) -> list[str]:
        """Return the names of all agents, sorted."""
        names = []
        for files in self.agent_files():
            names.append(files.name)
        return names

    def status(self) -> dict:
        """Return whether the runner runs, its pid, and every agent's status, for the terminal and the web page."""
        pid = self.lock.holder()
        running = pid is not None
        agents = []
        for files in self.agent_files():
            agent_status = files.status(running)
            agents.append(agent_status)
        return {"running": running, "pid": pid or None, "agents": agents}

    def stop(self, timeout: float = 25) -> bool:
        """Ask the running runner, if any, to close its agents and exit, and wait until it has.

        Return True once no runner holds the lock. If the runner still runs
        after `timeout` seconds, kill it and return False.
        """
        deadline = time.monotonic() + timeout
        asked = False
        while True:
            pid = self.lock.holder()
            if pid is None:
                return True
            if time.monotonic() > deadline:
                if pid:
                    self.platform.kill(pid)
                return False
            if pid and not asked:
                self.platform.request_stop(pid)
                asked = True
            time.sleep(0.2)

    def clear(self) -> None:
        """Delete every agent's runtime files and every message, so the next start begins from scratch.

        Call it only while the runner is stopped.
        """
        for files in self.agent_files():
            files.clear()
        self.broker.clear()

    def start(self) -> None:
        """Run the agents in this process until Ctrl+C, quit, or stop() asks them to stop.

        Start the broker if needed, and hold the lock while the agents run.
        Raise RunnerError if the Claude CLI is missing, the broker cannot
        start, or another runner is running.
        """
        if shutil.which(CLAUDE_BIN) is None:
            raise RunnerError(f"Cannot find the Claude CLI ({CLAUDE_BIN}). Install it, or set CLAUDE_BIN to its path.")
        self.broker.ensure_running()
        if not self.lock.acquire():
            pid = self.lock.holder()
            raise RunnerError(f"The agents are already running (runner pid {pid}). Stop them with --stop.")
        self.platform.forget_stop_request()
        try:
            main_coroutine = self.run()
            asyncio.run(main_coroutine)
        finally:
            self.lock.release()

    async def run(self) -> None:
        """Start every agent's session and inbox, and wait until all of them have stopped.

        They stop after Ctrl+C, quit, or stop(). Print what happens.
        """
        stopping = asyncio.Event()
        stop_requests = self.platform.handle_stop_requests(stopping)
        stop_task = asyncio.create_task(stop_requests)
        client = self.broker.async_client()
        agents = []
        index = 0
        for files in self.agent_files():
            color = PALETTE[index % len(PALETTE)]
            agent = Agent(files, self.platform, self.broker, client, color)
            await agent.create_group()
            agents.append(agent)
            index = index + 1
        count = len(agents)
        names = self.agent_names()
        name_list = ", ".join(names)
        print(f"Starting {count} agents: {name_list}", flush=True)
        loop = asyncio.get_running_loop()
        console = Console(self, stopping)
        console.open(loop)
        jobs = [stop_task]
        for agent in agents:
            session_job = agent.keep_alive(stopping)
            inbox_job = agent.read_inbox(stopping)
            jobs.append(session_job)
            jobs.append(inbox_job)
        await asyncio.gather(*jobs)
        await client.aclose()
        print("All agents stopped.", flush=True)


def print_status(status: dict) -> None:
    """Print whether the agents run, and one line per agent, as `--status` and the console show it."""
    if status["running"]:
        runner_pid = status["pid"]
        print(f"Agents are running (runner pid {runner_pid}).")
    else:
        print("Agents are not running.")
    for agent in status["agents"]:
        session = agent["session_id"] or "-"
        session = session[:8]
        pid = agent["pid"] or "-"
        print(f"  {agent['name']:<8} {agent['label']:<8} {agent['role']:<21} "
              f"{agent['status']:<9} pid {pid:<8} session {session}  turns {agent['turns']}")


def new_session_state() -> dict:
    """Return the state of a session that has not started yet: a new random session id and no turns."""
    session_id = uuid.uuid4()
    session_text = str(session_id)
    return {"session_id": session_text, "turns": 0}


async def wait_for_event(event: asyncio.Event, seconds: float) -> bool:
    """Wait until the event is set, but at most the given number of seconds. Return whether it was set."""
    waiting = event.wait()
    try:
        await asyncio.wait_for(waiting, timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


async def wait_for_exit(process: asyncio.subprocess.Process, seconds: float) -> bool:
    """Wait until the process exits, but at most the given number of seconds. Return whether it exited."""
    waiting = process.wait()
    try:
        await asyncio.wait_for(waiting, timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


def read_json(path: Path) -> dict:
    """Return the JSON object in the file, or {} if the file is missing or is not valid JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict) -> None:
    """Replace the file with the data as JSON, in one step, so a reader never sees half a file.

    Write a temporary file first, then move it over the old one. Raise
    PermissionError if the move keeps failing for 2 seconds.
    """
    temporary = path.with_suffix(".tmp")
    text = json.dumps(data, indent=2)
    temporary.write_text(text, encoding="utf-8")
    deadline = time.monotonic() + 2
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            # Windows cannot replace a file while another process, such as
            # the web server, is reading it. That takes a moment at most.
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def now() -> str:
    """Return the current UTC time in ISO 8601 format, to the second."""
    moment = datetime.now(timezone.utc)
    return moment.isoformat(timespec="seconds")


def first_line(text: str, width: int = 100) -> str:
    """Return the first line of the text, cut to `width` characters with "..." at the end if it is longer."""
    text = text.strip()
    lines = text.splitlines()
    if not lines:
        return ""
    line = lines[0]
    if len(line) <= width:
        return line
    return line[: width - 3] + "..."


def describe(tool_input: dict) -> str:
    """Return a short description of a tool call: the first line of its main input, without the repository's path.

    The main input is the first of these that the call has: file_path,
    command, pattern, path, url, or description. Return "" if it has none.
    """
    repo_prefix = f"{REPO_ROOT}{os.sep}"
    for key in ("file_path", "command", "pattern", "path", "url", "description"):
        value = tool_input.get(key)
        if value:
            text = str(value)
            line = first_line(text)
            return line.replace(repo_prefix, "")
    return ""


def main() -> None:
    """Run the command line: show the status, stop the agents, reset them, or run them until they stop.

    Exit with a message if something goes wrong.
    """
    parser = argparse.ArgumentParser(description="Start the agent sessions and keep them alive.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="show what each agent is doing")
    action.add_argument("--stop", action="store_true", help="stop the agents and keep their sessions and messages")
    action.add_argument("--reset", action="store_true", help="stop the agents and clear their sessions and messages")
    args = parser.parse_args()
    # Agents print any character. On Windows, a log file or pipe would get the
    # ANSI code page, which has few of them, and a failed print stops an agent.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    runner = Runner()
    try:
        if args.status:
            status = runner.status()
            print_status(status)
        elif args.stop or args.reset:
            if not runner.stop():
                raise RunnerError("The runner did not stop in time and was killed. Run the command again to clean up.")
            if args.reset:
                runner.clear()
                print("Agents stopped, sessions and messages cleared.")
            else:
                print("Agents stopped.")
        else:
            runner.start()
    except RunnerError as error:
        message = str(error)
        sys.exit(message)


if __name__ == "__main__":
    main()
