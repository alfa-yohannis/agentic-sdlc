"""Tests for Console, the commands typed into the runner's terminal."""

import asyncio
import io
import sys

import run_agents


def make_console(runner: run_agents.Runner) -> run_agents.Console:
    """Return a Console for the runner, with a stopping event of its own."""
    stopping = asyncio.Event()
    return run_agents.Console(runner, stopping)


def test_quit_and_exit_set_the_stopping_event(runner):
    """Both quit and exit set the stopping event."""
    for command in ("quit\n", "exit\n"):
        console = make_console(runner)
        console.handle(command)
        assert console.stopping.is_set()


def test_a_message_to_an_agent_goes_through_the_broker(runner, broker):
    """`@amy <text>` publishes the text, stripped, from the human to amy."""
    console = make_console(runner)
    console.handle("@amy   Please start  \n")
    message = broker.read()["messages"][0]
    assert message["from"] == "human"
    assert message["to"] == "amy"
    assert message["text"] == "Please start"


def test_a_message_to_all_goes_through_the_broker(runner, broker):
    """`@all <text>` publishes the text from the human to all."""
    console = make_console(runner)
    console.handle("@all Stand-up in five minutes")
    message = broker.read()["messages"][0]
    assert message["to"] == "all"


def test_an_unknown_agent_an_empty_message_or_an_unknown_command_prints_the_help(runner, broker, capsys):
    """An unknown recipient, an empty message, or an unknown command prints the help line and sends nothing."""
    console = make_console(runner)
    console.handle("@zed hello")
    console.handle("@amy    ")
    console.handle("dance")
    output = capsys.readouterr().out
    assert output.count(run_agents.Console.HELP) == 3
    assert broker.read()["total"] == 0


def test_status_prints_every_agent(runner, capsys):
    """status prints whether the agents run and a line for each agent."""
    console = make_console(runner)
    console.handle("status")
    output = capsys.readouterr().out
    assert "Agents are not running." in output
    assert "amy" in output
    assert "ben" in output


def test_a_blank_line_does_nothing(runner, capsys):
    """A blank line prints nothing and stops nothing."""
    console = make_console(runner)
    console.handle("   \n")
    output = capsys.readouterr().out
    assert output == ""
    assert not console.stopping.is_set()


def test_open_does_nothing_without_a_terminal(runner, capsys, monkeypatch):
    """open() neither reads nor prints anything when the input is no terminal, as when the web server starts the runner."""
    no_terminal = io.StringIO("")
    monkeypatch.setattr(sys, "stdin", no_terminal)
    console = make_console(runner)
    loop = asyncio.new_event_loop()
    try:
        console.open(loop)
    finally:
        loop.close()
    output = capsys.readouterr().out
    assert output == ""
