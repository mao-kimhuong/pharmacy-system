from uuid import uuid4

from branch_service.db import db
from branch_service.services.branches import sync_features

from .conftest import CASHIER_PERMS, OWNER, PREFIX, outbox, user


async def test_everyone_logged_in_can_read_features(client) -> None:
    cashier = user("cashier", (uuid4(),), CASHIER_PERMS)
    features = {f["key"]: f for f in (await client.get(f"{PREFIX}/features", headers=cashier)).json()}
    assert features["commission"]["enabled"] is False
    assert "commission_rules" in features["commission"]["hides"]
    assert set(features) >= {"hampers", "sale_orders", "multi_branch", "ai"}


async def test_owner_turns_a_feature_on(client) -> None:
    r = await client.put(f"{PREFIX}/features/commission", json={"enabled": True}, headers=OWNER)
    assert r.status_code == 200
    assert {f["key"]: f["enabled"] for f in r.json()}["commission"] is True
    events = await outbox()
    assert ("feature.changed", {"key": "commission", "enabled": True}) in events
    assert any(t == "audit.recorded" and p["action"] == "feature.changed" for t, p in events)


async def test_setting_the_same_value_records_nothing(client) -> None:
    await client.put(f"{PREFIX}/features/commission", json={"enabled": False}, headers=OWNER)
    assert await outbox() == []


async def test_cashier_cannot_change_features(client) -> None:
    cashier = user("cashier", (uuid4(),), CASHIER_PERMS)
    r = await client.put(f"{PREFIX}/features/commission", json={"enabled": True}, headers=cashier)
    assert r.status_code == 403


async def test_unknown_feature(client) -> None:
    r = await client.put(f"{PREFIX}/features/time_travel", json={"enabled": True}, headers=OWNER)
    assert r.status_code == 404
    assert r.json()["code"] == "UNKNOWN_FEATURE"


async def test_restart_keeps_the_owners_choice(client) -> None:
    await client.put(f"{PREFIX}/features/ai", json={"enabled": True}, headers=OWNER)
    async with db.sessionmaker() as session:
        await sync_features(session)
    features = {
        f["key"]: f["enabled"] for f in (await client.get(f"{PREFIX}/features", headers=OWNER)).json()
    }
    assert features["ai"] is True
