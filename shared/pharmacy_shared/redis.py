import asyncio

from redis.asyncio import Redis


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
            self._client = Redis.from_url(self.url, decode_responses=True)
            self._loop = loop
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._loop = None
