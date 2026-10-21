"""The web server for the monitor page.

It serves the page in static/index.html and the API that the page calls to
show the agents and their messages, to start and reset the agents, and to send
a message from the human. The agents run in a separate process, the runner
(agents/run_agents.py), which this server starts on demand.

Importing this module creates the FastAPI app and the objects that talk to the
runner. It starts nothing. Run it with `fastapi dev main.py`.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parent
AGENTS_DIR = REPO_ROOT / "agents"

# run_agents.py is a script in agents/, not an installed package.
AGENTS_PATH = str(AGENTS_DIR)
sys.path.insert(0, AGENTS_PATH)
import run_agents  # noqa: E402


class RunnerProcess:
    """The runner process that this server starts in the background.

    The server keeps the process it started, so that it can tell when the
    runner exits right after starting, and can collect its exit status.
    """

    def __init__(self, runner: run_agents.Runner) -> None:
        """Remember the runner to start. Start nothing yet."""
        self.runner = runner
        self.process: subprocess.Popen | None = None
        self.starting = threading.Lock()

    def start(self) -> None:
        """Start the runner unless one runs already, and wait until it holds its lock.

        The runner's output goes to its log file. Two requests at the same
        time start only one runner. Raise RunnerError if the runner exits
        instead of taking its lock.
        """
        with self.starting:
            self.reap()
            if self.runner.lock.holder() is not None:
                return
            log_path = self.runner.log_file
            log_path.parent.mkdir(parents=True, exist_ok=True)
            script = str(AGENTS_DIR / "run_agents.py")
            platform = self.runner.platform
            with open(log_path, "w") as log:
                # A process group of its own, so the agents keep running
                # while the server reloads or stops on Ctrl+C.
                self.process = subprocess.Popen(
                    [sys.executable, script],
                    cwd=REPO_ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=platform.new_session,
                    creationflags=platform.creation_flags,
                )
            self.wait_until_running()

    def wait_until_running(self, timeout: float = 30) -> None:
        """Wait up to `timeout` seconds until the new runner holds its lock.

        Raise RunnerError, with the end of the runner's log, if it exits first.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.runner.lock.holder() is not None:
                return
            if self.process.poll() is not None:
                tail = self.log_tail()
                raise run_agents.RunnerError(f"The runner exited: {tail}")
            time.sleep(0.1)

    def reap(self) -> None:
        """Forget the runner process this server started, and collect its exit status, if it has ended."""
        if self.process is None:
            return
        if self.process.poll() is not None:
            self.process = None

    def log_tail(self, lines: int = 5) -> str:
        """Return the last lines of the runner's log, joined into one line, or "no output"."""
        try:
            text = self.runner.log_file.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return "no output"
        text = text.strip()
        all_lines = text.splitlines()
        last_lines = all_lines[-lines:]
        tail = " ".join(last_lines)
        if not tail:
            return "no output"
        return tail


class NewMessage(BaseModel):
    """The body of POST /api/messages: who gets the message, and its text."""

    to: str
    text: str


runner = run_agents.Runner()
runner_process = RunnerProcess(runner)
app = FastAPI(title="Agentic SDLC")


@app.get("/")
def index():
    """Return the monitor page."""
    page = SERVER_DIR / "static" / "index.html"
    return FileResponse(page)


@app.get("/api/agents")
def agents():
    """Return whether the agents run and what each agent is doing. Forget the runner process if it has ended."""
    runner_process.reap()
    return runner.status()


@app.get("/api/messages")
def messages(after: str = "0"):
    """Return the messages in the broker's stream after the given id, oldest first."""
    return runner.broker.read(after)


@app.post("/api/messages")
def send_message(message: NewMessage):
    """Send a message from the human to one agent, or to all of them, through the broker.

    Answer 400 for an unknown recipient or an empty message, and 503 if the
    broker is not running.
    """
    recipients = runner.agent_names()
    recipients.append("all")
    if message.to not in recipients:
        raise HTTPException(400, f"Unknown recipient {message.to!r}.")
    text = message.text.strip()
    if not text:
        raise HTTPException(400, "The message is empty.")
    try:
        message_id = runner.broker.publish("human", message.to, text)
    except run_agents.redis.RedisError:
        raise HTTPException(503, "The broker is not running. Press Start first.")
    return {"id": message_id}


@app.post("/api/start")
def start():
    """Start the runner, which starts the broker and one Claude CLI session per agent.

    Return the agents' status. Answer 500 if the runner exits instead of starting.
    """
    try:
        runner_process.start()
    except run_agents.RunnerError as error:
        reason = str(error)
        raise HTTPException(500, reason)
    return runner.status()


@app.post("/api/reset")
def reset():
    """Turn off every agent process, then clear their sessions and all messages.

    Return the agents' status. Answer 500 if the runner did not stop in time
    and had to be killed.
    """
    if not runner.stop():
        raise HTTPException(500, "The runner did not stop in time and was killed. Press Reset again.")
    runner.clear()
    runner_process.reap()
    return runner.status()
