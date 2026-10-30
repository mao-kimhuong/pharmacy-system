"""Command line tools for the auth service.

    python -m auth_service.cli create-owner            (asks for name, phone, password)
    make owner                                         (same, inside the running container)

The password can also come from the OWNER_PASSWORD environment variable.
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from pharmacy_shared.outbox import add_event

from .db import db
from .models import OutboxEvent, Role, User
from .services.passwords import MIN_PASSWORD_LENGTH, hash_password
from .services.phone import normalize_phone
from .services.users import user_event_payload


class CliError(Exception):
    pass


async def create_owner(name: str, phone: str, password: str, is_pharmacist: bool = False) -> User:
    name = name.strip()
    if not name:
        raise CliError("Name is required")
    try:
        phone = normalize_phone(phone)
    except ValueError as exc:
        raise CliError("Invalid phone number") from exc
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    async with db.sessionmaker() as session, session.begin():
        if (await session.execute(select(User.id).where(User.role == Role.OWNER).limit(1))).first():
            raise CliError("An owner already exists. Add more staff from the Settings → User screen.")
        if (await session.execute(select(User.id).where(User.phone == phone))).first():
            raise CliError("This phone number is already used")
        user = User(
            name=name,
            phone=phone,
            password_hash=hash_password(password),
            role=Role.OWNER,
            is_pharmacist=is_pharmacist,
        )
        session.add(user)
        await session.flush()
        add_event(session, OutboxEvent, "user.created", user_event_payload(user))
    return user


async def republish() -> int:
    """Write a user.updated event for every user (name, role, pharmacist, active,
    branches; no secrets): for services that start listening after users exist."""
    async with db.sessionmaker() as session:
        users = list((await session.execute(select(User).order_by(User.name))).scalars())
        for user in users:
            add_event(session, OutboxEvent, "user.updated", user_event_payload(user))
        await session.commit()
    return len(users)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auth_service.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("create-owner", help="create the first owner account")
    owner.add_argument("--name")
    owner.add_argument("--phone")
    owner.add_argument("--pharmacist", action="store_true", help="the owner is also a licensed pharmacist")
    sub.add_parser("republish", help="re-send every user as a user.updated event")
    args = parser.parse_args(argv)

    if args.command == "republish":
        print(f"Queued {asyncio.run(_run(republish()))} user events")

    if args.command == "create-owner":
        name = args.name or input("Owner name: ")
        phone = args.phone or input("Phone: ")
        password = os.environ.get("OWNER_PASSWORD") or getpass.getpass("Password: ")
        if not os.environ.get("OWNER_PASSWORD") and getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match", file=sys.stderr)
            return 1
        try:
            user = asyncio.run(_run(create_owner(name, phone, password, args.pharmacist)))
        except CliError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Owner created: {user.name} ({user.phone})")
    return 0


async def _run(coro):  # type: ignore[no-untyped-def]
    try:
        return await coro
    finally:
        await db.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
