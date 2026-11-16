from uuid import uuid4

from sqlalchemy import select

from auth_service.db import db
from auth_service.models import KnownBranch, ProcessedMessage
from auth_service.services.events import handle_event
from pharmacy_shared.audit import AUDIT_EVENT, audit_payload
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.consumer import process_message

from .conftest import PREFIX, add_branch, as_user, login, make_user


async def deliver(event_type: str, payload: dict, message_id=None) -> bool:
    return await process_message(
        db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload
    )


async def test_user_log_records_logins(client) -> None:
    owner = await make_user(phone="010000000", role="owner")
    b1 = await add_branch()
    await make_user(phone="011111111", branches=(b1,))
    await login(client, phone="011111111")
    await login(client, phone="011111111", password="wrong-pass", ip="10.0.0.9")
    r = await client.get(f"{PREFIX}/audit-logs", headers=await as_user(owner))
    actions = [e["action"] for e in r.json()["items"]]
    assert actions[:2] == ["user.login_failed", "user.logged_in"]  # newest first


async def test_events_from_other_services_land_in_the_user_log(client) -> None:
    owner = await make_user(phone="010000000", role="owner")
    actor = CurrentUser(id=uuid4(), role="pharmacist", branch_ids=frozenset(), is_pharmacist=True)
    payload = audit_payload(
        service="sales",
        action="invoice.cancelled",
        entity_type="invoice",
        entity_id="INV-1",
        actor=actor,
        before={"status": "paid"},
        after={"status": "cancelled", "reason": "wrong item"},
    )
    assert await deliver(AUDIT_EVENT, payload)
    r = await client.get(
        f"{PREFIX}/audit-logs", params={"action": "invoice.cancelled"}, headers=await as_user(owner)
    )
    entry = r.json()["items"][0]
    assert entry["service"] == "sales"
    assert entry["after"]["reason"] == "wrong item"
    assert entry["actor_role"] == "pharmacist"


async def test_the_same_event_is_stored_once(client) -> None:
    owner = await make_user(phone="010000000", role="owner")
    mid = uuid4()
    payload = audit_payload(service="sales", action="x.y", entity_type="t", entity_id="1", actor=None)
    assert await deliver(AUDIT_EVENT, payload, mid)
    assert not await deliver(AUDIT_EVENT, payload, mid)
    r = await client.get(f"{PREFIX}/audit-logs", params={"action": "x.y"}, headers=await as_user(owner))
    assert r.json()["total"] == 1


async def test_manager_sees_only_own_branch_entries(client) -> None:
    b1 = await add_branch(code="PP1")
    b2 = await add_branch(code="PP2")
    manager = await make_user(phone="012222222", role="branch_manager", branches=(b1,))
    for branch in (b1, b2):
        await deliver(
            AUDIT_EVENT,
            audit_payload(
                service="sales", action="sale.x", entity_type="t", entity_id="1", actor=None, branch_id=branch
            ),
        )
    r = await client.get(f"{PREFIX}/audit-logs", params={"action": "sale.x"}, headers=await as_user(manager))
    assert [e["branch_id"] for e in r.json()["items"]] == [str(b1)]


async def test_cashier_cannot_read_the_user_log(client) -> None:
    b1 = await add_branch()
    cashier = await make_user(phone="011111111", branches=(b1,))
    assert (await client.get(f"{PREFIX}/audit-logs", headers=await as_user(cashier))).status_code == 403


async def test_branch_events_keep_the_branch_list_up_to_date() -> None:
    bid = uuid4()
    base = {"branch_id": str(bid), "code": "PP9", "name_en": "Riverside"}
    await deliver("branch.created", {**base, "is_active": True})
    await deliver("branch.updated", {**base, "name_en": "Riverside 2", "is_active": True})
    await deliver("branch.deactivated", {**base, "name_en": "Riverside 2", "is_active": False})
    async with db.sessionmaker() as session:
        branch = (await session.execute(select(KnownBranch).where(KnownBranch.id == bid))).scalar_one()
    assert branch.name_en == "Riverside 2"
    assert branch.is_active is False


async def test_an_event_from_the_seed_dev_clock_keeps_its_time(client) -> None:
    # make seed-realistic (development only) back-dates calls; the User Log keeps when it "happened"
    from datetime import datetime

    from pharmacy_shared import clock

    owner = await make_user(phone="010000000", role="owner")
    token = clock.set_override(datetime.fromisoformat("2026-08-15T10:30:00+07:00"))
    try:
        payload = audit_payload(service="sales", action="invoice.created", entity_type="invoice", entity_id="INV-9",
                                actor=None)  # fmt: skip
    finally:
        clock.reset_override(token)
    assert payload["occurred_at"].startswith("2026-08-15T03:30")
    assert "occurred_at" not in audit_payload(service="sales", action="x.y", entity_type="x", entity_id="1", actor=None)
    assert await deliver(AUDIT_EVENT, payload)
    r = await client.get(f"{PREFIX}/audit-logs", params={"action": "invoice.created"}, headers=await as_user(owner))
    [entry] = r.json()["items"]
    assert entry["occurred_at"].startswith("2026-08-15")
