# How to run

The server in `server/` is a FastAPI app with one page. The page starts and stops the six agents (Alice, Bob, Charlie, David, Erin, and Frank) and shows the messages they send each other. Each agent is a long-running Claude CLI session, and the agents talk through a Redis broker.

## Requirements

- Linux, macOS, or Windows. These steps were tested with Python 3.14.8 on Linux and Python 3.12 on Windows 11, with FastAPI 0.143.0 and the Redis client 8.1.0.
- Python 3.10 or newer.
- The Claude Code CLI on your `PATH`, logged in to your Claude account. Check it with `claude --version`. The agents use that login, so no API key is needed. On Windows, Claude Code also needs Git for Windows, because its Bash tool runs Git Bash.
- Docker with Docker Compose, which runs the broker (`redis:7-alpine`) the same way on every system. On Windows, that is Docker Desktop, and it must be running before you press Start.

## First-time setup

The server and the agent runner share a local virtual environment at `server/.venv`, which git ignores. Create it and install the dependencies once. On Linux and macOS:

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, in PowerShell:

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `server/.venv` already exists, run only the last two lines, so that new dependencies get installed.

## Start the server

On Linux and macOS:

```bash
cd server
source .venv/bin/activate
fastapi dev main.py
```

On Windows, in PowerShell:

```powershell
cd server
.venv\Scripts\Activate.ps1
fastapi dev main.py
```

`fastapi dev` restarts the app whenever you save a change to the server code. A restart leaves running agents alone. To use another port, add `--port 8080`.

## Use the page

Open http://127.0.0.1:8000. The left panel shows the agents and the right panel shows the messages between them.

- Start starts the broker container if it is not running, then one process for every agent. Each card goes from offline to starting to idle once its Claude session is up. An agent that is handling a message shows working, and the card's middle line shows what it did last.
- Reset turns off every agent process and clears their sessions and all messages, so the next Start begins from scratch. The broker container keeps running.
- The box under the messages sends a message from you (the human) to one agent, or to all of them. Enter sends it, and Shift+Enter adds a line. A message sent while the agents are off waits in the broker until you press Start.

To begin the real work, send Alice a message such as "The user story in agents/shared_context/user-story-login.md is ready. Please write the requirements specification." The agents then hand the work to each other as described in `agents/shared_context/team.md`.

The page refreshes every second. Idle agents use nothing. Only the messages they handle count against your Claude plan.

The page calls these endpoints, which FastAPI lists at http://127.0.0.1:8000/docs: `GET /api/agents`, `POST /api/start`, `POST /api/reset`, `GET /api/messages`, and `POST /api/messages`.

## Run the agents from a terminal

You can also run the agents without the page. From the repository root, with the virtual environment active (`server\.venv\Scripts\Activate.ps1` on Windows):

```bash
source server/.venv/bin/activate
python agents/run_agents.py
```

In that terminal, type `@alice <message>` to message one agent, `@all <message>` to message all of them, `status` to list them, or `quit` to stop them (Ctrl+C works too). Each agent's replies and tool calls are printed with its name in front. Messages typed here also go through the broker, so the page shows them.

From any other terminal:

```bash
python agents/run_agents.py --status   # show what each agent is doing
python agents/run_agents.py --stop     # stop the agents and keep their sessions and messages
python agents/run_agents.py --reset    # stop the agents and clear sessions and messages, like the Reset button
```

Only one runner can work at a time, so the page and a terminal never start the same agent twice. The page also shows agents that were started from a terminal.

## How the agents run

`agents/shared_context/scenario.drawio` shows the whole setup in two pages, the scenario and the architecture. Open it with draw.io.

Every folder in `agents/` that has an `agent.json` file is one agent.

| Path | Purpose |
|---|---|
| `agents/<name>/CLAUDE.md` | The agent's role and instructions |
| `agents/<name>/agent.json` | How its session starts: label, role, tools, the folders it may use, permissions |
| `agents/shared_context/team.md` | Team context that every agent gets in addition to its own `CLAUDE.md`, including the rules for messages |
| `agents/shared_context/` | Files the agents share, starting with the user story |
| `agents/run_agents.py` | The runner that keeps the sessions alive and delivers messages |
| `agents/os_support.py` | What the runner does differently on Linux and macOS and on Windows: file locks, stopping the runner, reading the terminal, and the paths in a virtual environment |
| `agents/team_mcp.py` | The `send_message` tool the agents use to talk |
| `broker/compose.yaml` | The Redis broker |
| `target_app/` | The app the agents build. It starts empty, and git ignores it |
| `tests/` | The tests of the runner, the `send_message` tool, and the web server |

The runner starts one `claude -p` process per agent in stream-json mode, with the agent's folder as the working directory. The process stays open between messages, so the agent remembers the conversation. If a process exits, the runner starts it again on the same session.

The sessions load only the agent's own `CLAUDE.md`, the team context, the `team` MCP server, and the settings in `agent.json`. Your global `~/.claude` instructions, hooks, and other MCP servers stay out of them. Each agent can edit files in its own folder and in the folders listed under `add_dirs`. Nobody is there to answer permission prompts, so anything that would prompt is refused instead of leaving the session waiting. The `allow` list in `agent.json` names the commands an agent may run anyway. Bob, Charlie, David, Erin, and Frank may run Python through the app's virtual environment:

```json
"allow": [
  "Bash(cd *)",
  "Bash(python3 -m venv *)",
  "Bash(.venv/bin/pip *)",
  "Bash(.venv/bin/python *)",
  "Bash(.venv/bin/pytest *)"
]
```

So they can create `target_app/.venv`, install packages into it, and run `pytest` and Playwright from `target_app/`. On Windows, the runner changes these rules to `python -m venv *` and `.venv/Scripts/...`, where a Windows virtual environment keeps its programs, and tells the agents to use those forms. Other commands that need approval, such as `python3 -c ...` with the system Python, are still refused. Alice's list is empty, because she only writes the specification. Keep in mind that these rules let the agents run any Python code in that environment, because tests are code. Run them on a machine you trust.

After you change a `CLAUDE.md` or `team.md`, press Reset and then Start, so the agents begin new sessions with the change. To apply a change to `agent.json` and keep the agents' memory, run `python agents/run_agents.py --stop` and then press Start: each agent resumes its session with the new settings.

## How the agents talk

Every message goes into one Redis stream, `sdlc:messages`, as an entry with the fields `from`, `to`, `text`, and `ts`.

- An agent sends a message with the `send_message` tool. The tool comes from `agents/team_mcp.py`, a small MCP server that the runner gives every session, and it appends the message to the stream. The box on the page and `@name` in the terminal append messages the same way, from `human`.
- Each agent has its own consumer group on the stream (`agent:alice`, `agent:bob`, and so on), which works as its inbox. The runner reads each group, passes the messages addressed to that agent (or to `all`) to its session as a new turn starting with `From: <sender>`, and acknowledges each message once the turn is over. A message that was not finished, for example because the runner stopped, is delivered again on the next start.
- The page reads the same stream, so it shows every message, including the ones addressed to you.

To look at the stream directly:

```bash
docker exec agentic-sdlc-broker redis-cli XRANGE sdlc:messages - +
```

The broker listens on `127.0.0.1:6380`. Set `SDLC_BROKER_URL` to use another Redis. Messages live only in the broker's memory, so they disappear when the container stops. To remove the container:

```bash
docker compose -f broker/compose.yaml down
```

## Runtime files

The runtime files live in `agents/.runtime/`, which git ignores:

- `agents/.runtime/<name>/session.json`: session id, status, process id, number of turns, and the last activity
- `agents/.runtime/<name>/events.jsonl`: everything the session printed, one JSON event per line
- `agents/.runtime/<name>/stderr.log`: error output from the Claude CLI
- `agents/.runtime/run_agents.log`: the runner's output when the page started it
- `agents/.runtime/run_agents.pid`: the lock that lets only one runner work at a time, with the runner's process id
- `agents/.runtime/run_agents.stop`: on Windows only, the request to stop that Reset and `--stop` leave for the runner, which deletes it

## Run the tests

The tests in `tests/` cover the runner, the `send_message` tool, and the web server, on Linux, macOS, and Windows. A few of them run only on Windows, and pytest reports those as skipped elsewhere. They need no broker, Docker, or Claude CLI: in-memory fakes stand in for Redis, and `tests/fake_claude.py` stands in for the CLI. Install pytest into the virtual environment once, then run the tests from the repository root:

```bash
pip install -r server/requirements-dev.txt
python -m pytest
```

They take about ten seconds.

## Build the slides

The slides are in `slides/agentic-sdlc/agentic-sdlc.tex`. They use the Pradita Beamer theme in `slides/theme/`, copied from the advanced-web-engineering course, and need XeLaTeX. Git ignores the PDF, so build it from the deck's folder:

```bash
cd slides/agentic-sdlc
latexmk -xelatex agentic-sdlc.tex
```

The figures come from `figures/`. `scenario.png` is page 1 of `agents/shared_context/scenario.drawio` exported with draw.io, and `monitor.png` is a screenshot of the monitor page.

## Stop the server

Press `Ctrl+C` in the terminal where the server runs, and type `deactivate` to leave the virtual environment. Stopping the server does not stop the agents. Press Reset first, or run `python agents/run_agents.py --stop` afterwards.
