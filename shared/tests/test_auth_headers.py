from uuid import UUID

import pytest

from pharmacy_shared.auth import current_user
from pharmacy_shared.errors import AppError

UID = "11111111-1111-1111-1111-111111111111"
B1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_reads_user_from_headers() -> None:
    user = current_user(UID, "cashier", f"{B1},{B2}", "false", None)
    assert user.id == UUID(UID)
    assert user.branch_ids == {UUID(B1), UUID(B2)}
    assert not user.is_pharmacist
    assert user.can_access_branch(UUID(B1))
    assert not user.can_access_branch(UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"))


def test_owner_can_access_every_branch() -> None:
    owner = current_user(UID, "owner", "", "true", None)
    assert owner.can_access_branch(UUID(B1))


@pytest.mark.parametrize(
    "user_id,role,branches",
    [(None, "cashier", ""), (UID, None, ""), ("not-a-uuid", "cashier", ""), (UID, "cashier", "x,y")],
)
def test_missing_or_bad_headers_are_401(user_id, role, branches) -> None:
    with pytest.raises(AppError) as err:
        current_user(user_id, role, branches, None, None)
    assert err.value.status_code == 401


def test_require_branch_raises_403() -> None:
    user = current_user(UID, "cashier", B1, "false", None)
    with pytest.raises(AppError) as err:
        user.require_branch(UUID(B2))
    assert err.value.status_code == 403
    assert err.value.code == "BRANCH_FORBIDDEN"


def test_permissions_from_header() -> None:
    user = current_user(UID, "cashier", B1, "false", "pos.sell,sales.view")
    assert user.has("pos.sell")
    assert not user.has("settings.users")
    with pytest.raises(AppError) as err:
        user.require("settings.users")
    assert err.value.status_code == 403
    assert err.value.code == "FORBIDDEN"


def test_star_means_every_permission() -> None:
    owner = current_user(UID, "owner", "", "false", "*")
    assert owner.has("settings.roles")
    owner.require("anything.at.all")


def test_no_permissions_header_means_none() -> None:
    user = current_user(UID, "cashier", B1, "false", None)
    assert user.permissions == frozenset()
    assert not user.has("pos.sell")
