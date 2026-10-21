"""Fakes that stand in for Redis and the broker in the tests.

They keep everything in memory, so the tests need no Redis server. They have
only the commands that the code under test uses.
"""

import asyncio

import redis

import run_agents


def id_number(message_id: str) -> int:
    """Return the number before the dash in a fake message id such as "3-0"."""
    number, _, _ = message_id.partition("-")
    return int(number)


class FakeRedis:
    """A stand-in for the blocking Redis client, with the stream commands the code uses.

    Set `up` to False to make every command fail as if the broker were down.
    """

    def __init__(self) -> None:
        """Start with no streams, and with the broker up."""
        self.up = True
        self.streams = {}
        self.last_id = 0

    def check_up(self) -> None:
        """Raise redis.ConnectionError if the broker is down."""
        if not self.up:
            raise redis.ConnectionError("The fake broker is down.")

    def ping(self) -> bool:
        """Answer a PING."""
        self.check_up()
        return True

    def xadd(self, stream: str, fields: dict) -> str:
        """Append an entry to the stream. Return its id: 1-0, then 2-0, and so on."""
        self.check_up()
        self.last_id = self.last_id + 1
        message_id = f"{self.last_id}-0"
        copied = dict(fields)
        entries = self.streams.setdefault(stream, [])
        entries.append((message_id, copied))
        return message_id

    def xrange(self, stream: str, min: str = "-", count: int | None = None) -> list:
        """Return up to `count` entries after the id in `min`, which looks like "(3-0", oldest first."""
        self.check_up()
        after = id_number(min[1:])
        found = []
        for message_id, fields in self.streams.get(stream, []):
            if id_number(message_id) > after:
                found.append((message_id, fields))
        return found[:count]

    def xrevrange(self, stream: str, count: int | None = None) -> list:
        """Return up to `count` entries, newest first."""
        self.check_up()
        entries = self.streams.get(stream, [])
        newest_first = list(entries)
        newest_first.reverse()
        return newest_first[:count]

    def xlen(self, stream: str) -> int:
        """Return how many entries the stream holds."""
        self.check_up()
        entries = self.streams.get(stream, [])
        return len(entries)

    def delete(self, stream: str) -> None:
        """Delete the stream."""
        self.check_up()
        self.streams.pop(stream, None)


class FakeAsyncRedis:
    """A stand-in for the asyncio Redis client that the agents use for their inboxes.

    The test queues batches of messages, which xreadgroup() returns one per
    call. The fake records every cursor it was asked for and every
    acknowledgement, and calls on_ack(message_id) after each acknowledgement
    if the test set it. When a group's batches run out, it sets
    `stop_when_empty`, if the test set that event.
    """

    def __init__(self) -> None:
        """Start with no groups, no batches, and nothing recorded."""
        self.groups = set()
        self.batches = {}
        self.cursors = []
        self.acked = []
        self.on_ack = None
        self.stop_when_empty = None
        self.closed = False

    def add_batch(self, group: str, entries: list) -> None:
        """Queue entries, as (message id, fields) pairs, for the group's next xreadgroup() call."""
        response = [["test:messages", entries]]
        queue = self.batches.setdefault(group, [])
        queue.append(response)

    async def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:
        """Create the group, or raise BUSYGROUP as Redis does if it exists already."""
        if group in self.groups:
            raise redis.ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups.add(group)

    async def xreadgroup(self, group: str, consumer: str, streams: dict, count: int, block: int) -> list:
        """Record the cursor, and return the group's next batch. Without one, wait a moment and return nothing."""
        for cursor in streams.values():
            self.cursors.append(cursor)
        queue = self.batches.get(group, [])
        if queue:
            return queue.pop(0)
        if self.stop_when_empty is not None:
            self.stop_when_empty.set()
        await asyncio.sleep(0.05)
        return []

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        """Record the acknowledgement, then call on_ack(message_id) if the test set it."""
        self.acked.append(message_id)
        if self.on_ack is not None:
            self.on_ack(message_id)

    async def aclose(self) -> None:
        """Remember that the runner closed the client."""
        self.closed = True


class FakeBroker(run_agents.Broker):
    """A Broker whose blocking and asyncio clients are the fakes above."""

    def __init__(self) -> None:
        """Set up a broker on a made-up address, with fake clients."""
        super().__init__("redis://fake-broker:6379/0", "test:messages")
        self.client = FakeRedis()
        self.fake_async = FakeAsyncRedis()

    def async_client(self) -> FakeAsyncRedis:
        """Return the fake asyncio client in place of a real one."""
        return self.fake_async
