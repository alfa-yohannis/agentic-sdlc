#!/usr/bin/env python3
"""MCP server that gives an agent session one tool: send_message.

The runner starts every Claude CLI session with this server. A call to
send_message appends the message to the broker's stream. The runner then
delivers it to the recipient, and the web page shows it.

It speaks MCP over stdin and stdout: one JSON-RPC message per line.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis

AGENT = os.environ["SDLC_AGENT"]
BROKER_URL = os.environ.get("SDLC_BROKER_URL", "redis://127.0.0.1:6380/0")
STREAM = os.environ.get("SDLC_STREAM", "sdlc:messages")
AGENTS_DIR = Path(__file__).resolve().parent
TEAMMATES = sorted(p.parent.name for p in AGENTS_DIR.glob("*/agent.json") if p.parent.name != AGENT)
RECIPIENTS = TEAMMATES + ["all", "human"]

TOOL = {
    "name": "send_message",
    "description": (
        "Send a message to a teammate or to the human through the team's message broker. "
        "Use it for handoffs, questions, answers, and reports that you are done or blocked. "
        "The recipient reads it as a new message after your current turn, so do not wait for a reply. "
        "Do not send acknowledgements or thanks."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "enum": RECIPIENTS,
                "description": "A teammate's name, 'all' for every teammate, or 'human' for the product owner.",
            },
            "text": {"type": "string", "description": "The message. Name the files it is about by their paths."},
        },
        "required": ["to", "text"],
        "additionalProperties": False,
    },
}

broker = redis.Redis.from_url(BROKER_URL, socket_connect_timeout=3)


def send_message(arguments: dict) -> tuple[str, bool]:
    """Return the text for the tool result and whether it is an error."""
    to = arguments.get("to")
    text = str(arguments.get("text") or "").strip()
    if to not in RECIPIENTS:
        return f"Unknown recipient {to!r}. Choose one of: {', '.join(RECIPIENTS)}.", True
    if not text:
        return "The message is empty.", True
    try:
        broker.xadd(STREAM, {
            "from": AGENT,
            "to": to,
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except redis.RedisError as error:
        return f"The broker is not reachable, so the message was not sent: {error}", True
    return f"Sent to {to}.", False


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "team", "version": "1.0.0"},
        }
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return {"content": [{"type": "text", "text": f"Unknown tool {params.get('name')!r}."}], "isError": True}
        text, failed = send_message(params.get("arguments") or {})
        return {"content": [{"type": "text", "text": text}], "isError": failed}
    if method == "ping":
        return {}
    raise LookupError(method)


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        if "id" not in request:  # a notification, which gets no answer
            continue
        try:
            reply = {"result": handle(request.get("method", ""), request.get("params") or {})}
        except LookupError:
            reply = {"error": {"code": -32601, "message": f"Method not found: {request.get('method')}"}}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], **reply}), flush=True)


if __name__ == "__main__":
    main()
