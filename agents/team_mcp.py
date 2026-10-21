#!/usr/bin/env python3
"""MCP server that gives an agent session one tool: send_message.

The runner starts every Claude CLI session with this server. A call to
send_message appends the message to the broker's stream. The runner then
delivers it to the recipient, and the web page shows it.

It speaks MCP over stdin and stdout: one JSON-RPC message per line. Running
this file serves the agent named by the SDLC_AGENT environment variable until
the CLI closes the input. Importing it only defines the class.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis

AGENTS_DIR = Path(__file__).resolve().parent

TOOL_DESCRIPTION = (
    "Send a message to a teammate or to the human through the team's message broker. "
    "Use it for handoffs, questions, answers, and reports that you are done or blocked. "
    "The recipient reads it as a new message after your current turn, so do not wait for a reply. "
    "Do not send acknowledgements or thanks."
)


class TeamServer:
    """The MCP server of one agent.

    It answers the MCP requests that the Claude CLI sends, and offers one
    tool, send_message, which appends a message to the broker's stream.
    """

    def __init__(self, agent: str, broker_url: str, stream: str) -> None:
        """Remember the agent this server serves, find its possible recipients, and create a broker client.

        Do not connect to the broker yet.
        """
        self.agent = agent
        self.stream = stream
        self.recipients = self.find_teammates()
        self.recipients.append("all")
        self.recipients.append("human")
        self.broker = redis.Redis.from_url(broker_url, socket_connect_timeout=3)

    def find_teammates(self) -> list[str]:
        """Return the names of the other agents, the other folders in agents/ with an agent.json, sorted."""
        teammates = []
        for path in AGENTS_DIR.glob("*/agent.json"):
            name = path.parent.name
            if name != self.agent:
                teammates.append(name)
        teammates.sort()
        return teammates

    def tool(self) -> dict:
        """Return the MCP definition of the send_message tool, which lists this agent's possible recipients."""
        return {
            "name": "send_message",
            "description": TOOL_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "enum": self.recipients,
                        "description": "A teammate's name, 'all' for every teammate, or 'human' for the product owner.",
                    },
                    "text": {"type": "string", "description": "The message. Name the files it is about by their paths."},
                },
                "required": ["to", "text"],
                "additionalProperties": False,
            },
        }

    def send_message(self, arguments: dict) -> tuple[str, bool]:
        """Append the message to the broker's stream, if its recipient is known and its text is not empty.

        Return the text for the tool result and whether it is an error.
        """
        to = arguments.get("to")
        text = arguments.get("text") or ""
        text = str(text)
        text = text.strip()
        if to not in self.recipients:
            choices = ", ".join(self.recipients)
            return f"Unknown recipient {to!r}. Choose one of: {choices}.", True
        if not text:
            return "The message is empty.", True
        timestamp = now()
        fields = {"from": self.agent, "to": to, "text": text, "ts": timestamp}
        try:
            self.broker.xadd(self.stream, fields)
        except redis.RedisError as error:
            return f"The broker is not reachable, so the message was not sent: {error}", True
        return f"Sent to {to}.", False

    def handle(self, method: str, params: dict) -> dict:
        """Answer one MCP request: initialize, tools/list, tools/call, or ping.

        Raise LookupError for any other method.
        """
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "team", "version": "1.0.0"},
            }
        if method == "tools/list":
            tool = self.tool()
            return {"tools": [tool]}
        if method == "tools/call":
            return self.call_tool(params)
        if method == "ping":
            return {}
        raise LookupError(method)

    def call_tool(self, params: dict) -> dict:
        """Run the tool that a tools/call request names, and return the MCP tool result."""
        name = params.get("name")
        if name != "send_message":
            return {"content": [{"type": "text", "text": f"Unknown tool {name!r}."}], "isError": True}
        arguments = params.get("arguments") or {}
        text, failed = self.send_message(arguments)
        return {"content": [{"type": "text", "text": text}], "isError": failed}

    def serve(self, requests, replies) -> None:
        """Read JSON-RPC messages, one per line, until the input ends, and write a reply line for each request.

        Notifications, the messages without an id, get no reply.
        """
        for line in requests:
            if not line.strip():
                continue
            request = json.loads(line)
            if "id" not in request:  # a notification, which gets no answer
                continue
            method = request.get("method", "")
            params = request.get("params") or {}
            try:
                result = self.handle(method, params)
                reply = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            except LookupError:
                error = {"code": -32601, "message": f"Method not found: {method}"}
                reply = {"jsonrpc": "2.0", "id": request["id"], "error": error}
            text = json.dumps(reply)
            print(text, file=replies, flush=True)


def now() -> str:
    """Return the current UTC time in ISO 8601 format, to the second."""
    moment = datetime.now(timezone.utc)
    return moment.isoformat(timespec="seconds")


def main() -> None:
    """Serve the agent named by SDLC_AGENT on stdin and stdout until the CLI closes the input."""
    agent = os.environ["SDLC_AGENT"]
    broker_url = os.environ.get("SDLC_BROKER_URL", "redis://127.0.0.1:6380/0")
    stream = os.environ.get("SDLC_STREAM", "sdlc:messages")
    server = TeamServer(agent, broker_url, stream)
    # The CLI writes UTF-8. On Windows, Python would read a pipe in the ANSI code page.
    sys.stdin.reconfigure(encoding="utf-8")
    server.serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
