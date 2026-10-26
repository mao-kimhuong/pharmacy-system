import pytest

from auth_service.cli import CliError, create_owner

from .conftest import login, outbox_types


async def test_create_owner_then_log_in(client) -> None:
    user = await create_owner("Mao Kim Huong", "+855 12 000 111", "a-strong-password")
    assert user.role == "owner"
    assert user.phone == "012000111"
    assert (await login(client, phone="012000111", password="a-strong-password")).status_code == 200
    assert "user.created" in await outbox_types()


async def test_only_one_first_owner() -> None:
    await create_owner("Owner", "012000111", "a-strong-password")
    with pytest.raises(CliError, match="already exists"):
        await create_owner("Owner 2", "012000222", "a-strong-password")


async def test_short_password_is_refused() -> None:
    with pytest.raises(CliError, match="at least 8"):
        await create_owner("Owner", "012000111", "short")


async def test_bad_phone_is_refused() -> None:
    with pytest.raises(CliError, match="phone"):
        await create_owner("Owner", "abc", "a-strong-password")
