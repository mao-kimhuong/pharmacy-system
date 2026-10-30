"""Against a real SeaweedFS (docker-compose.test.yml, pinned 4.51)."""

import os
from uuid import uuid4

import httpx
import pytest

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.storage import Storage

ENDPOINT = os.environ.get("TEST_S3_ENDPOINT", "")
STORE = Storage(endpoint=ENDPOINT, bucket="test-files",
                access_key="testkey123", secret_key="test-secret-0123456789abcdef")  # fmt: skip


# make test / make test-docker set TEST_S3_ENDPOINT (and start the store): then it must work.
pytestmark = pytest.mark.skipif(
    not ENDPOINT, reason="TEST_S3_ENDPOINT not set (make test-db starts the store)"
)


async def test_files_are_private_and_only_read_with_the_keys() -> None:
    await STORE.ensure_bucket()
    key = f"rx/{uuid4()}"
    await STORE.put(key, b"%PDF-1.7 test", "application/pdf")
    assert await STORE.get(key) == b"%PDF-1.7 test"
    # without the keys: nothing, not the file, not the list
    assert httpx.get(f"{ENDPOINT}/test-files/{key}").status_code == 403
    assert httpx.get(f"{ENDPOINT}/test-files").status_code == 403
    wrong = Storage(
        endpoint=ENDPOINT, bucket="test-files", access_key="testkey123", secret_key="wrong-secret-000000000"
    )
    with pytest.raises(AppError):
        await wrong.get(key)


async def test_a_missing_file_is_not_found() -> None:
    await STORE.ensure_bucket()
    with pytest.raises(AppError) as err:
        await STORE.get(f"rx/{uuid4()}")
    assert err.value.code == ErrorCode.NOT_FOUND


async def test_store_down_is_temporarily_unavailable() -> None:
    down = Storage(endpoint="http://127.0.0.1:9", bucket="x", access_key="a", secret_key="b" * 20)
    with pytest.raises(AppError) as err:
        await down.put("rx/x", b"x", "image/png")
    assert err.value.code == ErrorCode.TEMPORARILY_UNAVAILABLE
