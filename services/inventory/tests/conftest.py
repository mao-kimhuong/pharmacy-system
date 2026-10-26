import os

from pharmacy_shared.testing import TEST_REDIS_URL

os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402

from inventory_service.main import app  # noqa: E402


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await app.state.redis.close()
