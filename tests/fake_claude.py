"""Stands in for the Claude CLI in stream-json mode, for the tests.

It answers every user message at once, with one text block, one tool call,
and a result event, and exits when its input ends. Run it as

    python fake_claude.py <session id> [--crash-once <marker file>]

With --crash-once, the first process that finds no marker file creates it,
reads one message, and exits with code 3 without answering, as a crashed CLI
would. Later processes answer normally.
"""

import json
import sys
from pathlib import Path


def emit(event: dict) -> None:
    """Print the event as one stream-json line."""
    line = json.dumps(event)
    print(line, flush=True)


def answer(session_id: str, line: str) -> None:
    """Answer one stream-json user message with a text block, a tool call, and a result event."""
    message = json.loads(line)
    content = message["message"]["content"]
    lines = content.splitlines()
    first = lines[0]
    text = f"Got it → {first} ✓"
    blocks = [
        {"type": "text", "text": text},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "notes.md"}},
    ]
    emit({"type": "assistant", "message": {"content": blocks}})
    emit({"type": "result", "subtype": "success", "session_id": session_id, "result": "ok"})


def main() -> None:
    """Announce the session, then answer messages until the input ends, or crash once if asked to."""
    session_id = sys.argv[1]
    crash_marker = None
    if "--crash-once" in sys.argv:
        position = sys.argv.index("--crash-once")
        crash_marker = Path(sys.argv[position + 1])
    sys.stdin.reconfigure(encoding="utf-8")
    emit({"type": "system", "subtype": "init", "session_id": session_id})
    for line in sys.stdin:
        if crash_marker is not None and not crash_marker.exists():
            crash_marker.touch()
            sys.exit(3)
        answer(session_id, line)


if __name__ == "__main__":
    main()
