"""Tests for team_mcp.py, the MCP server that gives each agent the send_message tool."""

import io
import json

import pytest

import team_mcp
from fakes import FakeRedis


@pytest.fixture
def server(team_dir, monkeypatch) -> team_mcp.TeamServer:
    """Return the TeamServer of amy in the test team, with an in-memory broker."""
    monkeypatch.setattr(team_mcp, "AGENTS_DIR", team_dir)
    server = team_mcp.TeamServer("amy", "redis://fake-broker:6379/0", "test:messages")
    server.broker = FakeRedis()
    return server


def stored_messages(server: team_mcp.TeamServer) -> list[dict]:
    """Return the fields of every message that the server added to the stream."""
    entries = server.broker.streams.get("test:messages", [])
    messages = []
    for message_id, fields in entries:
        messages.append(fields)
    return messages


def as_lines(messages: list[dict]) -> str:
    """Return the messages as JSON-RPC input: one JSON object per line."""
    lines = []
    for message in messages:
        line = json.dumps(message)
        lines.append(line)
    return "\n".join(lines) + "\n"


def test_the_recipients_are_the_teammates_all_and_the_human(server):
    """The recipients are the other agents (not amy herself, not folders without agent.json), all, and human."""
    assert server.recipients == ["ben", "all", "human"]


def test_the_tool_offers_exactly_the_recipients(server):
    """The send_message tool lists the recipients and requires both to and text."""
    tool = server.tool()
    schema = tool["inputSchema"]
    assert tool["name"] == "send_message"
    assert schema["properties"]["to"]["enum"] == server.recipients
    assert schema["required"] == ["to", "text"]


def test_send_message_adds_the_message_to_the_stream(server):
    """send_message() adds the stripped text from amy to the stream, keeping any character, and reports success."""
    text, failed = server.send_message({"to": "ben", "text": "  Spec siap → lihat requirements.md ✓ "})
    assert failed is False
    assert text == "Sent to ben."
    fields = stored_messages(server)[0]
    assert fields["from"] == "amy"
    assert fields["to"] == "ben"
    assert fields["text"] == "Spec siap → lihat requirements.md ✓"
    assert "ts" in fields


def test_send_message_refuses_an_unknown_recipient(server):
    """send_message() reports an error that lists the recipients, and sends nothing, for an unknown recipient."""
    text, failed = server.send_message({"to": "zed", "text": "hi"})
    assert failed is True
    assert "Choose one of: ben, all, human." in text
    assert stored_messages(server) == []


def test_send_message_refuses_an_empty_message(server):
    """send_message() reports an error, and sends nothing, for a message without text."""
    text, failed = server.send_message({"to": "ben", "text": "   "})
    assert failed is True
    assert text == "The message is empty."
    assert stored_messages(server) == []


def test_send_message_reports_a_broker_that_is_down(server):
    """send_message() reports an error, instead of failing, when the broker is down."""
    server.broker.up = False
    text, failed = server.send_message({"to": "ben", "text": "hi"})
    assert failed is True
    assert "not reachable" in text


def test_initialize_answers_with_the_client_protocol_version(server):
    """initialize answers with the protocol version the client asked for, a tools capability, and the server's name."""
    result = server.handle("initialize", {"protocolVersion": "2024-11-05"})
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "team"


def test_tools_list_and_ping_are_answered(server):
    """tools/list returns the one tool, and ping returns an empty result."""
    listing = server.handle("tools/list", {})
    tools = listing["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "send_message"
    assert server.handle("ping", {}) == {}


def test_tools_call_runs_send_message(server):
    """tools/call with send_message sends the message and returns the tool's text."""
    params = {"name": "send_message", "arguments": {"to": "all", "text": "Stand-up"}}
    result = server.handle("tools/call", params)
    assert result["isError"] is False
    assert result["content"][0]["text"] == "Sent to all."


def test_tools_call_refuses_an_unknown_tool(server):
    """tools/call with another tool's name returns an error result."""
    result = server.handle("tools/call", {"name": "delete_everything"})
    assert result["isError"] is True


def test_an_unknown_method_raises_lookup_error(server):
    """handle() raises LookupError for a method the server does not have."""
    with pytest.raises(LookupError):
        server.handle("resources/list", {})


def test_serve_answers_every_request_and_skips_notifications(server):
    """serve() writes one reply line per request, none for notifications or blank lines, and an error for an unknown method."""
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "send_message", "arguments": {"to": "ben", "text": "Hello"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "nope"},
    ]
    text = as_lines(messages) + "\n"
    requests = io.StringIO(text)
    replies = io.StringIO()
    server.serve(requests, replies)
    output = replies.getvalue()
    answers = []
    for line in output.splitlines():
        answer = json.loads(line)
        answers.append(answer)
    ids = []
    for answer in answers:
        ids.append(answer["id"])
    assert ids == [1, 2, 3]
    assert answers[1]["result"]["isError"] is False
    assert answers[2]["error"]["code"] == -32601
    stored = stored_messages(server)
    assert len(stored) == 1
