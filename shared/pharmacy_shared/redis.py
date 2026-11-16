import asyncio
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialWithJitterBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

# redis-py 8: a client made by Redis.from_url() gets Retry(NoBackoff(), 0) – a connection or handshake that fails
# once (a reset socket, a reply cut short through Docker's port forwarding, a Redis restart) fails the call at once,
# seen as "Invalid Database" / "Error setting client name" during test set-up. Every client here is made by connect():
# the connect + handshake and the command are retried with backoff (≈ 2 s in all), and nothing waits forever.
RETRIES = 6


def connect(url: str, **kwargs: Any) -> Redis:  # noqa: ANN401
    return Redis.from_url(
        url,
        retry=Retry(ExponentialWithJitterBackoff(base=0.05, cap=0.5), retries=RETRIES),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
        socket_connect_timeout=5,
        socket_timeout=10,
        health_check_interval=30,
        **kwargs,
    )


class RedisProvider:
    """One Redis client per event loop (one in production; one per test loop in tests).

    Creating the client does not connect; the first command does.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: Redis | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def client(self) -> Redis:
        loop = asyncio.get_running_loop()
        if self._client is None or loop is not self._loop:
            self._client = connect(self.url, decode_responses=True)
            self._loop = loop
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._loop = None
