"""Prescriptions: draft → active, validity, cancel, branch scope, expiry job."""

from datetime import date

from prescription_service.db import db
from prescription_service.services.expiry import expire_prescriptions

from .conftest import (
    CASHIER,
    PHARMACIST,
    PHARMACIST_PP2,
    PP1,
    PREFIX,
    add_doctor,
    add_patient,
    add_product,
    add_rx,
    event,
    hold,
)  # fmt: skip


async def setup(client) -> tuple[dict, dict, str]:  # noqa: ANN001
    return await add_patient(client), await add_doctor(client), await add_product()


async def test_numbered_valid_30_days_by_default_and_branch_setting(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 21, "dosage": "1 capsule",
                                      "frequency": "3 times a day", "duration_days": 7}], rx_no="A-778")  # fmt: skip
    assert rx["number"] == "PP1-RX-2026-000001" and rx["rx_no"] == "A-778"
    assert rx["valid_until"] == "2026-11-24" and rx["status"] == "active"
    await event("branch.settings_updated", {"branch_id": str(PP1), "rx_valid_days": 10})
    rx2 = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 1}], activate=False)
    assert rx2["valid_until"] == "2026-11-04" and rx2["status"] == "draft"


async def test_only_drafts_change_and_unknown_medicine_refused(client) -> None:
    p, d, m = await setup(client)
    r = await client.post(f"{PREFIX}/prescriptions", headers=PHARMACIST, json={
        "branch_id": str(PP1), "patient_id": p["id"], "doctor_id": d["id"], "issued_on": "2026-10-25",
        "items": [{"medicine_id": d["id"], "qty_base": 1}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_MEDICINE"
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}], activate=False)
    r = await client.patch(f"{PREFIX}/prescriptions/{rx['id']}", json={"items": [{"medicine_id": m, "qty_base": 20}]},
                           headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 200 and r.json()["items"][0]["qty_base"] == 20
    await client.post(f"{PREFIX}/prescriptions/{rx['id']}/activate", headers=PHARMACIST)
    r = await client.patch(f"{PREFIX}/prescriptions/{rx['id']}", json={"notes": "x"}, headers=PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "PRESCRIPTION_STATE"


async def test_activating_an_old_rx_is_refused(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 1}], activate=False,
                      issued_on="2026-08-01", valid_until="2026-09-01")  # fmt: skip
    r = await client.post(f"{PREFIX}/prescriptions/{rx['id']}/activate", headers=PHARMACIST)
    assert r.status_code == 422 and r.json()["code"] == "RX_EXPIRED"


async def test_cancel_needs_reason_and_not_while_held(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])
    assert (await client.post(f"{PREFIX}/prescriptions/{rx['id']}/cancel", json={}, headers=PHARMACIST)).status_code == 422
    assert (await hold(client, rx["items"][0]["id"], m, 5)).status_code == 200
    r = await client.post(f"{PREFIX}/prescriptions/{rx['id']}/cancel", json={"reason": "wrong"}, headers=PHARMACIST)
    assert r.status_code == 409
    rx2 = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])
    r = await client.post(f"{PREFIX}/prescriptions/{rx2['id']}/cancel", json={"reason": "doctor changed it"},
                          headers=PHARMACIST)  # fmt: skip
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "doctor changed it"


async def test_branch_scope_and_cashier_blocked(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])
    assert (await client.get(f"{PREFIX}/prescriptions/{rx['id']}", headers=PHARMACIST_PP2)).status_code == 404
    assert (await client.get(f"{PREFIX}/prescriptions", headers=PHARMACIST_PP2)).json()["total"] == 0
    assert (await client.get(f"{PREFIX}/prescriptions/{rx['id']}", headers=CASHIER)).status_code == 403
    assert (await client.get(f"{PREFIX}/prescriptions/{rx['id']}/remaining", headers=CASHIER)).status_code == 403


async def test_remaining_shows_fill_and_repeats(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10, "repeats_allowed": 2}])
    r = (await client.get(f"{PREFIX}/prescriptions/{rx['id']}/remaining", headers=PHARMACIST)).json()
    item = r["items"][0]
    assert r["dispensable"] is True
    assert (item["remaining_base"], item["fill_base"], item["can_dispense_now"]) == (30, 10, 10)


async def test_daily_job_expires_open_prescriptions(client) -> None:
    p, d, m = await setup(client)
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}], valid_until="2026-10-30")
    draft = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}], activate=False, valid_until="2026-10-30")
    async with db.sessionmaker() as s:
        assert await expire_prescriptions(s, date(2026, 10, 30)) == []
    async with db.sessionmaker() as s:
        assert await expire_prescriptions(s, date(2026, 10, 31)) == [rx["number"]]
    r = (await client.get(f"{PREFIX}/prescriptions/{rx['id']}", headers=PHARMACIST)).json()
    assert r["status"] == "expired"
    assert (await client.get(f"{PREFIX}/prescriptions/{draft['id']}", headers=PHARMACIST)).json()["status"] == "draft"
