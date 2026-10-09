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

sys.path.insert(0, str(AGENTS_DIR))
import run_agents  # noqa: E402

RUNNER_LOG = run_agents.RUNTIME_DIR / "run_agents.log"

app = FastAPI(title="Agentic SDLC")
start_lock = threading.Lock()
runner: subprocess.Popen | None = None


class NewMessage(BaseModel):
    to: str
    text: str


@app.get("/")
def index():
    return FileResponse(SERVER_DIR / "static" / "index.html")


@app.get("/api/agents")
def agents():
    reap_runner()
    return run_agents.read_status()


@app.get("/api/messages")
def messages(after: str = "0"):
    """Messages in the broker's stream after the given id, oldest first."""
    return run_agents.read_messages(after)


@app.post("/api/messages")
def send_message(message: NewMessage):
    """Send a message from the human to one agent, or to all of them."""
    recipients = [folder.name for folder in run_agents.agent_folders()] + ["all"]
    if message.to not in recipients:
        raise HTTPException(400, f"Unknown recipient {message.to!r}.")
    if not message.text.strip():
        raise HTTPException(400, "The message is empty.")
    try:
        message_id = run_agents.publish("human", message.to, message.text.strip())
    except run_agents.redis.RedisError:
        raise HTTPException(503, "The broker is not running. Press Start first.")
    return {"id": message_id}


@app.post("/api/start")
def start():
    """Start the runner, which starts the broker and one Claude CLI session per agent."""
    global runner
    with start_lock:
        reap_runner()
        if run_agents.runner_pid() is None:
            RUNNER_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(RUNNER_LOG, "w") as log:
                # A session of its own, so the agents keep running while the
                # server reloads.
                runner = subprocess.Popen(
                    [sys.executable, str(AGENTS_DIR / "run_agents.py")],
                    cwd=REPO_ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            wait_for_runner(runner)
    return run_agents.read_status()


@app.post("/api/reset")
def reset():
    """Turn off every agent process and clear their sessions and messages."""
    if not run_agents.stop_runner():
        raise HTTPException(500, "The runner did not stop in time and was killed. Press Reset again.")
    run_agents.clear_sessions()
    run_agents.clear_messages()
    reap_runner()
    return run_agents.read_status()


def wait_for_runner(process: subprocess.Popen, timeout: float = 30) -> None:
    """Wait until the new runner holds its lock, or report why it exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run_agents.runner_pid() is not None:
            return
        if process.poll() is not None:
            raise HTTPException(500, f"The runner exited: {log_tail()}")
        time.sleep(0.1)


def reap_runner() -> None:
    """Collect the exit status of a runner this server started, if it has ended."""
    global runner
    if runner is not None and runner.poll() is not None:
        runner = None


def log_tail(lines: int = 5) -> str:
    try:
        return " ".join(RUNNER_LOG.read_text().strip().splitlines()[-lines:]) or "no output"
    except FileNotFoundError:
        return "no output"
