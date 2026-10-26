"""What a user may do: permissions of their role, and whether 2FA is still to be set up."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import ALL_PERMISSIONS

from ..config import Settings
from ..models import RolePermission, RoleRecord, User
from ..permissions import OWNER


async def load_permissions(session: AsyncSession, role_key: str) -> list[str]:
    if role_key == OWNER:
        return [ALL_PERMISSIONS]
    rows = await session.execute(
        select(RolePermission.permission_key)
        .join(RoleRecord, RoleRecord.key == RolePermission.role_key)
        .where(RolePermission.role_key == role_key, RoleRecord.is_active.is_(True))
        .order_by(RolePermission.permission_key)
    )
    return list(rows.scalars())


def needs_2fa(user: User, settings: Settings) -> bool:
    """The role must use 2FA, or the user turned it on themselves."""
    return user.role in settings.roles_requiring_2fa or user.totp_enabled


def mfa_setup_required(user: User, settings: Settings) -> bool:
    return user.role in settings.roles_requiring_2fa and not user.totp_enabled
