#!/usr/bin/env python3
"""Start the agent sessions and keep them alive.

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
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import redis
    import redis.asyncio as aioredis
except ImportError:  # --status works without the Redis client
    redis = aioredis = None

AGENTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENTS_DIR.parent
RUNTIME_DIR = AGENTS_DIR / ".runtime"
LOCK_FILE = RUNTIME_DIR / "run_agents.pid"
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
HELP = "Type @<agent> <message>, @all <message>, status, or quit."


class Agent:
    """One agent: a Claude CLI session that runs in the agent's folder."""

    def __init__(self, folder: Path, color: int = 0) -> None:
        self.name = folder.name
        self.folder = folder
        self.color = color
        self.config = read_json(folder / "agent.json")
        self.runtime = RUNTIME_DIR / self.name
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.state = read_json(self.runtime / "session.json")
        if not self.state.get("session_id"):
            self.state = {"session_id": str(uuid.uuid4()), "turns": 0}
        self.status = "offline"
        self.broker = None  # set by run() to an asyncio Redis client
        self.proc: asyncio.subprocess.Process | None = None
        self.inbox: collections.deque[tuple[str, str, str | None]] = collections.deque()
        self.mail = asyncio.Event()
        self.turn_over = asyncio.Event()
        self.in_flight: tuple[str, str, str | None] | None = None
        self.turn_started = 0.0

    @property
    def group(self) -> str:
        return f"agent:{self.name}"

    def send(self, sender: str, text: str, message_id: str | None = None) -> None:
        """Queue a message. The agent reads it as soon as its current turn ends."""
        self.inbox.append((sender, text, message_id))
        self.mail.set()

    def command(self) -> list[str]:
        config = self.config
        team_server = {
            "command": sys.executable,
            "args": [str(TEAM_MCP)],
            "env": {"SDLC_AGENT": self.name, "SDLC_BROKER_URL": BROKER_URL, "SDLC_STREAM": STREAM},
        }
        allow = ["mcp__team__send_message", *config.get("allow", [])]
        cmd = [
            CLAUDE_BIN, "-p", "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--name", self.name,
            # Load this folder's CLAUDE.md and settings but not the user's
            # global ones, and no MCP server except the team's.
            "--setting-sources", "project,local",
            "--mcp-config", json.dumps({"mcpServers": {"team": team_server}}),
            "--strict-mcp-config",
            "--settings", json.dumps({"permissions": {"allow": allow}}),
            "--permission-mode", config.get("permission_mode", "acceptEdits"),
            # Nobody is there to answer a permission prompt, so anything that
            # would ask is denied instead of leaving the session waiting.
            "--permission-prompts", "none",
        ]
        # The CLI can resume a session only once it has received a message.
        if self.state.get("turns") or self.state.get("started"):
            cmd += ["--resume", self.state["session_id"]]
        else:
            cmd += ["--session-id", self.state["session_id"]]
        if TEAM_CONTEXT.exists():
            cmd += ["--append-system-prompt", TEAM_CONTEXT.read_text()]
        if config.get("tools"):
            cmd += ["--tools", ",".join(config["tools"])]
        for directory in config.get("add_dirs", []):
            path = REPO_ROOT / directory
            path.mkdir(parents=True, exist_ok=True)
            cmd += ["--add-dir", str(path)]
        if config.get("model"):
            cmd += ["--model", config["model"]]
        if config.get("effort"):
            cmd += ["--effort", config["effort"]]
        return cmd

    async def keep_alive(self, stopping: asyncio.Event) -> None:
        """Run the session until `stopping` is set, restarting it when it exits."""
        quick_exits = 0
        while not stopping.is_set():
            started = time.monotonic()
            try:
                await self._spawn()
            except OSError as error:
                self._say(f"cannot start the Claude CLI: {error}")
                self._set_status("offline")
                code = None
            else:
                reader = asyncio.create_task(self._read_events())
                writer = asyncio.create_task(self._deliver())
                stop = asyncio.create_task(stopping.wait())
                await asyncio.wait({reader, stop}, return_when=asyncio.FIRST_COMPLETED)
                if stopping.is_set():
                    await self._shutdown()
                for task in (writer, stop):
                    task.cancel()
                await asyncio.gather(reader, writer, stop, return_exceptions=True)
                code = await self.proc.wait()
                self._set_status("offline")
            if stopping.is_set():
                break

            # The process ended on its own. Put the unanswered message back
            # in the queue and start the session again.
            if self.in_flight:
                self.inbox.appendleft(self.in_flight)
                self.in_flight = None
                self.mail.set()
            quick_exits = quick_exits + 1 if time.monotonic() - started < 10 else 0
            if quick_exits >= 3:
                self._say(f"session {self.state['session_id'][:8]} keeps failing, starting a new one")
                self.state = {"session_id": str(uuid.uuid4()), "turns": 0}
                quick_exits = 0
            delay = 2 ** quick_exits
            self._say(f"exited with code {code}, restarting in {delay}s")
            try:
                await asyncio.wait_for(stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def read_inbox(self, stopping: asyncio.Event) -> None:
        """Pass the agent every broker message addressed to it, through its consumer group."""
        # "0" first returns messages this agent received before but never
        # finished, for example when the runner stopped mid-turn. ">" then
        # waits for new ones.
        cursor = "0"
        while not stopping.is_set():
            try:
                response = await self.broker.xreadgroup(
                    self.group, "runner", {STREAM: cursor}, count=20, block=2000)
            except redis.ResponseError as error:
                if "NOGROUP" not in str(error):
                    raise
                await self._create_group()
                continue
            except redis.ConnectionError as error:
                self._say(f"broker unreachable ({error}), retrying")
                await asyncio.sleep(2)
                continue
            entries = response[0][1] if response else []
            if cursor != ">":
                cursor = entries[-1][0] if entries else ">"
            for message_id, fields in entries:
                sender = fields.get("from", "?")
                if fields.get("to") in (self.name, "all") and sender != self.name:
                    self.send(sender, fields.get("text", ""), message_id)
                else:
                    await self.broker.xack(STREAM, self.group, message_id)

    async def _create_group(self) -> None:
        try:
            await self.broker.xgroup_create(STREAM, self.group, id="0", mkstream=True)
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def _spawn(self) -> None:
        self._set_status("starting")
        with open(self.runtime / "stderr.log", "ab") as stderr:
            self.proc = await asyncio.create_subprocess_exec(
                *self.command(),
                cwd=self.folder,
                env={k: v for k, v in os.environ.items() if k not in PARENT_SESSION_VARS},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                limit=LINE_LIMIT,
                # A process group of its own, so Ctrl+C reaches only this
                # script, which then closes the sessions one by one.
                start_new_session=True,
            )
        kind = "resumed" if self.state.get("turns") or self.state.get("started") else "new"
        self._say(f"{kind} session {self.state['session_id'][:8]}, pid {self.proc.pid}")
        self._set_status("idle")

    async def _deliver(self) -> None:
        """Write queued messages to the session, one turn at a time."""
        while True:
            while not self.inbox:
                self.mail.clear()
                await self.mail.wait()
            sender, text, _ = self.in_flight = self.inbox.popleft()
            self.turn_over.clear()
            self.turn_started = time.monotonic()
            self.state["started"] = True
            self.state["activity"] = f"reading a message from {sender}"
            self._set_status("working")
            self._say(f"<- {sender}: {first_line(text)}")
            self._log({"type": "runtime", "subtype": "message", "from": sender, "text": text})
            message = {
                "type": "user",
                "session_id": self.state["session_id"],
                "parent_tool_use_id": None,
                "message": {"role": "user", "content": f"From: {sender}\n\n{text}"},
            }
            self.proc.stdin.write(json.dumps(message).encode() + b"\n")
            await self.proc.stdin.drain()
            await self.turn_over.wait()

    async def _read_events(self) -> None:
        """Read the session's output until the process closes it."""
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
            self._log(event)
            self._show(event)
            if event.get("type") == "result" and self.in_flight:
                message_id = self.in_flight[2]
                self.in_flight = None
                self.state["turns"] = self.state.get("turns", 0) + 1
                self.state["session_id"] = event.get("session_id") or self.state["session_id"]
                self._set_status("idle")
                if message_id and self.broker:
                    try:
                        await self.broker.xack(STREAM, self.group, message_id)
                    except redis.RedisError as error:
                        self._say(f"could not acknowledge message {message_id}: {error}")
                self.turn_over.set()

    async def _shutdown(self) -> None:
        """Close the session's input so the CLI exits, and make sure it does."""
        proc = self.proc
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
        for action, grace in ((None, 10), (proc.terminate, 5), (proc.kill, 5)):
            if action:
                try:
                    action()
                except ProcessLookupError:
                    return
            try:
                await asyncio.wait_for(proc.wait(), timeout=grace)
                return
            except asyncio.TimeoutError:
                continue

    def _set_status(self, status: str) -> None:
        self.status = status
        self._save_state()
        self._log({"type": "runtime", "subtype": "status", "status": status})

    def _save_state(self) -> None:
        alive = self.proc is not None and self.proc.returncode is None
        self.state.update(status=self.status, pid=self.proc.pid if alive else None, updated=now())
        write_json(self.runtime / "session.json", self.state)

    def _show(self, event: dict) -> None:
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    self._say(block["text"].strip())
                    self.state["activity"] = first_line(block["text"])
                    self._save_state()
                elif block.get("type") == "tool_use":
                    tool_input = block.get("input") or {}
                    if block.get("name") == "mcp__team__send_message":
                        activity = f"sent a message to {tool_input.get('to')}"
                    else:
                        activity = f"{block.get('name')} {describe(tool_input)}".strip()
                    self._say(f"-> {activity}")
                    self.state["activity"] = activity
                    self._save_state()
        elif event.get("type") == "result" and self.in_flight:
            seconds = time.monotonic() - self.turn_started
            if event.get("is_error"):
                self._say(f"turn failed after {seconds:.0f}s: {event.get('result') or event.get('subtype')}")
            else:
                self._say(f"done in {seconds:.0f}s")

    def _say(self, text: str) -> None:
        prefix = f"\033[{self.color}m[{self.name}]\033[0m" if USE_COLOR and self.color else f"[{self.name}]"
        for line in text.splitlines():
            print(prefix, line, flush=True)

    def _log(self, event: dict) -> None:
        with open(self.runtime / "events.jsonl", "a") as log:
            log.write(json.dumps({"ts": now(), **event}) + "\n")


def agent_folders() -> list[Path]:
    return sorted(path.parent for path in AGENTS_DIR.glob("*/agent.json"))


def runner_pid() -> int | None:
    """Return the pid of the running runner (0 if not yet written), or None."""
    try:
        with open(LOCK_FILE) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                text = lock.read().strip()
                return int(text) if text.isdigit() else 0
            return None
    except FileNotFoundError:
        return None


def read_status() -> dict:
    """Describe the runner and every agent, for the terminal and the web page."""
    pid = runner_pid()
    running = pid is not None
    agents = []
    for folder in agent_folders():
        config = read_json(folder / "agent.json")
        state = read_json(RUNTIME_DIR / folder.name / "session.json")
        agents.append({
            "name": folder.name,
            "label": config.get("label", ""),
            "role": config.get("role", ""),
            "status": state.get("status", "offline") if running else "offline",
            "pid": state.get("pid") if running else None,
            "session_id": state.get("session_id"),
            "turns": state.get("turns", 0),
            "activity": state.get("activity"),
            "updated": state.get("updated"),
        })
    return {"running": running, "pid": pid or None, "agents": agents}


def stop_runner(timeout: float = 25) -> bool:
    """Stop the running runner, if any. Return True once it is gone."""
    deadline = time.monotonic() + timeout
    signalled = False
    while (pid := runner_pid()) is not None:
        if time.monotonic() > deadline:
            if pid:
                os.kill(pid, signal.SIGKILL)
            return False
        if pid and not signalled:
            os.kill(pid, signal.SIGTERM)
            signalled = True
        time.sleep(0.2)
    return True


def clear_sessions() -> None:
    """Forget every agent's session, so the next start begins new conversations."""
    for folder in agent_folders():
        for name in ("session.json", "events.jsonl", "stderr.log"):
            (RUNTIME_DIR / folder.name / name).unlink(missing_ok=True)


def broker_client():
    if redis is None:
        sys.exit("The Redis client is missing. Run this script with the server's virtual environment.")
    return redis.Redis.from_url(BROKER_URL, decode_responses=True, socket_connect_timeout=2)


def ensure_broker() -> None:
    """Start the broker container unless the broker already answers."""
    client = broker_client()
    try:
        client.ping()
        return
    except redis.RedisError:
        pass
    if not shutil.which("docker"):
        sys.exit(f"The broker at {BROKER_URL} is not running and Docker is not available to start it.")
    print("Starting the broker...", flush=True)
    subprocess.run(["docker", "compose", "-f", str(BROKER_COMPOSE), "up", "-d"], check=True)
    for _ in range(60):
        try:
            client.ping()
            return
        except redis.RedisError:
            time.sleep(0.5)
    sys.exit(f"The broker did not answer at {BROKER_URL}.")


def publish(sender: str, to: str, text: str) -> str:
    """Add a message to the broker's stream and return its id."""
    return broker_client().xadd(STREAM, {"from": sender, "to": to, "text": text, "ts": now()})


def read_messages(after: str = "0", limit: int = 500) -> dict:
    """Return the messages after the given stream id, oldest first."""
    try:
        client = broker_client()
        if after in ("", "0"):
            entries = list(reversed(client.xrevrange(STREAM, count=limit)))
        else:
            entries = client.xrange(STREAM, min=f"({after}", count=limit)
        total = client.xlen(STREAM)
    except redis.RedisError:
        return {"broker": False, "total": 0, "messages": []}
    return {"broker": True, "total": total, "messages": [{"id": i, **fields} for i, fields in entries]}


def clear_messages() -> None:
    """Delete every message and inbox position. Nothing to do if the broker is down."""
    try:
        broker_client().delete(STREAM)
    except redis.RedisError:
        pass


def print_status(status: dict) -> None:
    if status["running"]:
        print(f"Agents are running (runner pid {status['pid']}).")
    else:
        print("Agents are not running.")
    for agent in status["agents"]:
        session = (agent["session_id"] or "-")[:8]
        print(f"  {agent['name']:<8} {agent['label']:<8} {agent['role']:<21} "
              f"{agent['status']:<9} pid {agent['pid'] or '-':<8} session {session}  turns {agent['turns']}")


def open_console(loop: asyncio.AbstractEventLoop, agents: list[Agent], stopping: asyncio.Event) -> None:
    """Read commands from the terminal, if this process runs in the foreground of one."""
    stdin = sys.stdin
    try:
        if not stdin or not stdin.isatty() or os.tcgetpgrp(stdin.fileno()) != os.getpgrp():
            return
    except OSError:
        return
    names = {agent.name for agent in agents}

    def on_line() -> None:
        line = stdin.readline()
        if not line:
            loop.remove_reader(stdin.fileno())
            return
        handle_command(line.strip(), names, stopping)

    loop.add_reader(stdin.fileno(), on_line)
    print(HELP, flush=True)


def handle_command(line: str, names: set[str], stopping: asyncio.Event) -> None:
    if not line:
        return
    if line in ("quit", "exit"):
        stopping.set()
        return
    if line == "status":
        print_status(read_status())
        return
    if line.startswith("@"):
        target, _, text = line[1:].partition(" ")
        if (target in names or target == "all") and text.strip():
            publish("human", target, text.strip())
            return
    print(HELP, flush=True)


async def run() -> None:
    agents = [Agent(folder, PALETTE[i % len(PALETTE)]) for i, folder in enumerate(agent_folders())]
    broker = aioredis.Redis.from_url(BROKER_URL, decode_responses=True)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    for agent in agents:
        agent.broker = broker
        await agent._create_group()
    print(f"Starting {len(agents)} agents: {', '.join(agent.name for agent in agents)}", flush=True)
    open_console(loop, agents, stopping)
    await asyncio.gather(
        *(agent.keep_alive(stopping) for agent in agents),
        *(agent.read_inbox(stopping) for agent in agents),
    )
    await broker.aclose()
    print("All agents stopped.", flush=True)


def take_lock():
    """Lock the pid file so only one runner can work at a time."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    # Write a temporary file first so a reader never sees half a file.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    os.replace(temporary, path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def first_line(text: str, width: int = 100) -> str:
    lines = text.strip().splitlines()
    line = lines[0] if lines else ""
    return line if len(line) <= width else line[: width - 3] + "..."


def describe(tool_input: dict) -> str:
    for key in ("file_path", "command", "pattern", "path", "url", "description"):
        if tool_input.get(key):
            return first_line(str(tool_input[key])).replace(f"{REPO_ROOT}/", "")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the agent sessions and keep them alive.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="show what each agent is doing")
    action.add_argument("--stop", action="store_true", help="stop the agents and keep their sessions and messages")
    action.add_argument("--reset", action="store_true", help="stop the agents and clear their sessions and messages")
    args = parser.parse_args()

    if args.status:
        print_status(read_status())
        return
    if args.stop or args.reset:
        if not stop_runner():
            sys.exit("The runner did not stop in time and was killed. Run the command again to clean up.")
        if args.reset:
            clear_sessions()
            clear_messages()
        print("Agents stopped, sessions and messages cleared." if args.reset else "Agents stopped.")
        return

    if not shutil.which(CLAUDE_BIN):
        sys.exit(f"Cannot find the Claude CLI ({CLAUDE_BIN}). Install it, or set CLAUDE_BIN to its path.")
    ensure_broker()
    lock = take_lock()
    if lock is None:
        sys.exit(f"The agents are already running (runner pid {runner_pid()}). Stop them with --stop.")
    try:
        asyncio.run(run())
    finally:
        lock.truncate(0)
        lock.close()


if __name__ == "__main__":
    main()
