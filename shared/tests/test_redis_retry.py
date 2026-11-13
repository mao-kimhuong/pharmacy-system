"""Regression: the intermittent "Invalid Database" / "Error setting client name" at test set-up. redis-py 8 gives a
client from Redis.from_url() no retry at all, so one connection cut during the handshake failed the call.
pharmacy_shared.redis.connect() retries it. A fake Redis drops the first two connections mid-handshake."""

import asyncio

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from pharmacy_shared.redis import RETRIES, RedisProvider, connect


class FlakyRedis:
    """Speaks just enough RESP2: the first `drop` connections are closed after the handshake was sent."""

    def __init__(self, drop: int) -> None:
        self.drop, self.connections = drop, 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        dropped = self.connections <= self.drop
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if not line.startswith(b"*"):
                    continue
                args = []
                for _ in range(int(line[1:])):
                    await reader.readline()  # $len
                    args.append((await reader.readline()).strip())
                if dropped and args[0].upper() == b"SELECT":  # what a cut connection looks like to the client
                    break
                writer.write(b"+OK\r\n" if args[0].upper() != b"PING" else b"+PONG\r\n")
                await writer.drain()
        finally:
            writer.close()

    async def __aenter__(self) -> str:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return f"redis://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/15"

    async def __aexit__(self, *exc: object) -> None:
        self.server.close()
        await self.server.wait_closed()


async def test_a_dropped_handshake_is_retried() -> None:
    flaky = FlakyRedis(drop=2)
    async with flaky as url:
        client = connect(url)
        try:
            assert await client.flushdb() is True
        finally:
            await client.aclose()
    assert flaky.connections == 3  # two cut, the third worked


async def test_without_the_retry_it_fails_at_once_which_was_the_bug() -> None:
    flaky = FlakyRedis(drop=1)
    async with flaky as url:
        plain = Redis.from_url(url)
        try:
            with pytest.raises(RedisConnectionError):
                await plain.flushdb()
        finally:
            await plain.aclose()
    assert flaky.connections == 1


async def test_a_redis_that_stays_down_still_fails_quickly() -> None:
    flaky = FlakyRedis(drop=100)
    async with flaky as url:
        client = connect(url)
        try:
            with pytest.raises(RedisConnectionError):
                await asyncio.wait_for(client.flushdb(), timeout=15)
        finally:
            await client.aclose()
    assert flaky.connections >= RETRIES  # tried again, then gave up (no endless wait)


async def test_the_services_clients_have_the_retry() -> None:
    provider = RedisProvider("redis://127.0.0.1:1/15")
    client = provider.client()
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["retry"]._retries == RETRIES and kwargs["socket_connect_timeout"] == 5  # noqa: SLF001
    await provider.close()
