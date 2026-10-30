"""Start-up: copy the permission catalog into the database and make sure the
built-in roles exist. Safe to run on every start and from several replicas.

- A built-in role that has never had permissions gets its defaults.
- A key that is new to the database (added in a later sprint) is given to the
  built-in roles whose defaults include it, so existing stacks get it too; the
  owner's later edits to other keys are kept.
- A renamed key (RENAMED) keeps its grants under the new name.
- DEFAULT_ADDITIONS (an existing key newly in a role's defaults) are given once.
"""

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from ..db import db
from ..models import AppliedGrant, Permission, RolePermission, RoleRecord
from ..permissions import CATALOG, DEFAULT_ADDITIONS, DEFAULT_ROLE_PERMISSIONS, RENAMED, SYSTEM_ROLES

LOCK_KEY = 7_202_651


async def sync_catalog() -> None:
    async with db.sessionmaker() as session, session.begin():
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        known = set((await session.execute(select(Permission.key))).scalars())
        first_time = not known
        for sort, p in enumerate(CATALOG):
            stmt = insert(Permission).values(key=p.key, group=p.group, label=p.label, sort=sort)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Permission.key],
                    set_={"group": p.group, "label": p.label, "sort": sort},
                )
            )
        for key, name in SYSTEM_ROLES.items():
            await session.execute(
                insert(RoleRecord)
                .values(key=key, name=name, is_system=True)
                .on_conflict_do_nothing(index_elements=[RoleRecord.key])
            )
        # Renamed keys: every role that had the old key gets the new one.
        for old, new in RENAMED.items():
            if old not in known:
                continue
            roles = (
                await session.execute(select(RolePermission.role_key).where(RolePermission.permission_key == old))
            ).scalars()
            for role_key in list(roles):
                await session.execute(
                    insert(RolePermission)
                    .values(role_key=role_key, permission_key=new)
                    .on_conflict_do_nothing()
                )
            await session.execute(delete(Permission).where(Permission.key == old))
            known.add(new)
        # Defaults only for built-in roles that have never had permissions,
        # so the owner's later edits are kept.
        for role_key, perms in DEFAULT_ROLE_PERMISSIONS.items():
            has_any = await session.execute(
                select(RolePermission.role_key).where(RolePermission.role_key == role_key).limit(1)
            )
            if has_any.first() is None:
                for perm in sorted(perms):
                    session.add(RolePermission(role_key=role_key, permission_key=perm))
            elif not first_time:
                for perm in sorted(perms - known):  # keys added since the last start
                    await session.execute(
                        insert(RolePermission)
                        .values(role_key=role_key, permission_key=perm)
                        .on_conflict_do_nothing()
                    )
        applied = set((await session.execute(select(AppliedGrant.tag))).scalars())
        for tag, role_key, perm in DEFAULT_ADDITIONS:
            if tag in applied:
                continue
            if not first_time:  # a new stack already got it with the defaults
                await session.execute(
                    insert(RolePermission).values(role_key=role_key, permission_key=perm).on_conflict_do_nothing()
                )
            session.add(AppliedGrant(tag=tag))
