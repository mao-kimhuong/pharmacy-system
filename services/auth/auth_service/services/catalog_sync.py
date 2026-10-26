"""Start-up: copy the permission catalog into the database and make sure the
built-in roles exist. Safe to run on every start and from several replicas."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import db
from ..models import Permission, RolePermission, RoleRecord
from ..permissions import CATALOG, DEFAULT_ROLE_PERMISSIONS, SYSTEM_ROLES


async def sync_catalog() -> None:
    async with db.sessionmaker() as session, session.begin():
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
        # Defaults only for built-in roles that have never had permissions,
        # so the owner's later edits are kept.
        for role_key, perms in DEFAULT_ROLE_PERMISSIONS.items():
            has_any = await session.execute(
                select(RolePermission.role_key).where(RolePermission.role_key == role_key).limit(1)
            )
            if has_any.first() is None:
                for perm in sorted(perms):
                    session.add(RolePermission(role_key=role_key, permission_key=perm))
