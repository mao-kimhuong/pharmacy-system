"""2FA backup codes (S8b): for a lost phone. Rules:

- 10 codes of 10 characters from an alphabet without look-alikes (no 0/O, 1/I/L);
  only their argon2 hashes are stored; shown once (by /2fa/enable and by
  POST /2fa/backup-codes, which needs the password and retires the old set).
- POST /login/2fa accepts one instead of the 6-digit code; it is used up in the
  same transaction (the user row is locked); a wrong one counts as a failed
  attempt (same lockout as a wrong code).
- User Log: user.backup_codes_regenerated, user.backup_code_used.
"""

import secrets
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock

from ..models import MfaBackupCode, User
from .passwords import hash_password, verify_password

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
COUNT, LENGTH = 10, 10


def _normal(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


async def regenerate(session: AsyncSession, user: User) -> list[str]:
    """A new set (the old one is retired). The caller commits and shows the codes once."""


    await session.execute(update(MfaBackupCode).where(MfaBackupCode.user_id == user.id, MfaBackupCode.used_at.is_(None),
                                                      MfaBackupCode.retired_at.is_(None)).values(retired_at=clock.now()))  # fmt: skip
    codes = ["".join(secrets.choice(ALPHABET) for _ in range(LENGTH)) for _ in range(COUNT)]
    session.add_all(MfaBackupCode(user_id=user.id, hash=hash_password(c)) for c in codes)
    return [f"{c[:5]}-{c[5:]}" for c in codes]


async def consume(session: AsyncSession, user: User, code: str) -> bool:
    """True when the code is one of the user's unused codes (now used). The user row
    is locked by the caller, so two logins cannot use the same code."""


    given = _normal(code)
    rows = (await session.execute(select(MfaBackupCode).where(
        MfaBackupCode.user_id == user.id, MfaBackupCode.used_at.is_(None), MfaBackupCode.retired_at.is_(None))
        .with_for_update())).scalars().all()  # fmt: skip
    for row in rows:
        if verify_password(row.hash, given):
            row.used_at = clock.now()
            return True
    return False


async def left(session: AsyncSession, user_id: UUID) -> int:
    return int((await session.execute(select(func.count()).select_from(MfaBackupCode).where(
        MfaBackupCode.user_id == user_id, MfaBackupCode.used_at.is_(None),
        MfaBackupCode.retired_at.is_(None)))).scalar_one())  # fmt: skip
