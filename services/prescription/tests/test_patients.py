"""Patients, allergies, doctors: permissions, branch visibility, privacy log."""

from sqlalchemy import select

from prescription_service.db import db
from prescription_service.models import OutboxEvent

from .conftest import CASHIER, OWNER, PHARMACIST, PHARMACIST_PP2, PP1, PP2, PREFIX, add_doctor, add_patient


async def audits(action: str) -> list[dict]:
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == "audit.recorded"))).scalars()
        return [r.payload for r in rows if r.payload["action"] == action]


async def test_create_patient_with_allergies_and_view_is_logged(client) -> None:
    p = await add_patient(client, allergies=[{"kind": "class", "value": "penicillins", "note": "rash"}])
    assert p["phone"] == "012345678" and p["home_branch_id"] == str(PP1)
    assert [a["value"] for a in p["allergies"]] == ["penicillins"]
    r = await client.get(f"{PREFIX}/patients/{p['id']}", headers=PHARMACIST)
    assert r.status_code == 200
    r = await client.get(f"{PREFIX}/patients/{p['id']}", headers=PHARMACIST)
    assert len(await audits("patient.viewed")) == 2


async def test_name_in_one_language_is_needed(client) -> None:
    r = await client.post(f"{PREFIX}/patients", json={"branch_id": str(PP1), "sex": "male"}, headers=PHARMACIST)
    assert r.status_code == 422


async def test_cashier_cannot_see_patients(client) -> None:
    p = await add_patient(client)
    assert (await client.get(f"{PREFIX}/patients", headers=CASHIER)).status_code == 403
    assert (await client.get(f"{PREFIX}/patients/{p['id']}", headers=CASHIER)).status_code == 403
    body = {"branch_id": str(PP1), "name_en": "X", "sex": "male"}
    assert (await client.post(f"{PREFIX}/patients", json=body, headers=CASHIER)).status_code == 403


async def test_other_branch_sees_patient_only_after_exact_phone_lookup(client) -> None:
    p = await add_patient(client)
    assert (await client.get(f"{PREFIX}/patients/{p['id']}", headers=PHARMACIST_PP2)).status_code == 404
    r = await client.get(f"{PREFIX}/patients", params={"q": "Sok"}, headers=PHARMACIST_PP2)
    assert r.json()["total"] == 0
    # a wrong number finds nothing
    r = await client.post(f"{PREFIX}/patients/link", json={"branch_id": str(PP2), "phone": "012 345 679"},
                          headers=PHARMACIST_PP2)  # fmt: skip
    assert r.status_code == 200 and r.json() == []
    r = await client.post(f"{PREFIX}/patients/link", json={"branch_id": str(PP2), "phone": "+855 12 345 678"},
                          headers=PHARMACIST_PP2)  # fmt: skip
    assert [x["id"] for x in r.json()] == [p["id"]]
    assert len(await audits("patient.linked")) == 1
    r = await client.get(f"{PREFIX}/patients/{p['id']}", headers=PHARMACIST_PP2)
    assert r.status_code == 200 and set(r.json()["branch_ids"]) == {str(PP1), str(PP2)}
    # only for your own branch
    r = await client.post(f"{PREFIX}/patients/link", json={"branch_id": str(PP1), "phone": "012345678"},
                          headers=PHARMACIST_PP2)  # fmt: skip
    assert r.status_code == 403


async def test_search_by_name_or_phone_and_owner_sees_all(client) -> None:
    await add_patient(client)
    await add_patient(client, PHARMACIST_PP2, PP2, name_en="Chan Vanna", name_km="ចាន់ វណ្ណា", phone="097 111 222")
    r = await client.get(f"{PREFIX}/patients", params={"q": "097111222"}, headers=PHARMACIST_PP2)
    assert [x["name_en"] for x in r.json()["items"]] == ["Chan Vanna"]
    assert "allergies" not in r.json()["items"][0]  # lists carry no medical details
    r = await client.get(f"{PREFIX}/patients", params={"q": "ដារា"}, headers=PHARMACIST)
    assert r.json()["total"] == 1
    assert (await client.get(f"{PREFIX}/patients", headers=OWNER)).json()["total"] == 2


async def test_allergy_removed_with_reason_never_deleted(client) -> None:
    p = await add_patient(client)
    r = await client.post(f"{PREFIX}/patients/{p['id']}/allergies", json={"kind": "ingredient", "value": "Ibuprofen"},
                          headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 201
    again = await client.post(f"{PREFIX}/patients/{p['id']}/allergies", json={"kind": "ingredient", "value": "ibuprofen"},
                              headers=PHARMACIST)  # fmt: skip
    assert again.status_code == 409
    allergy = r.json()["allergies"][0]
    r = await client.post(f"{PREFIX}/patients/{p['id']}/allergies/{allergy['id']}/remove", json={"reason": "tested"},
                          headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 200
    assert [a["is_active"] for a in r.json()["allergies"]] == [False]


async def test_deactivate_patient_and_doctor(client) -> None:
    p = await add_patient(client)
    r = await client.post(f"{PREFIX}/patients/{p['id']}/deactivate", json={"reason": "moved away"}, headers=PHARMACIST)
    assert r.json()["is_active"] is False
    d = await add_doctor(client)
    r = await client.post(f"{PREFIX}/doctors/{d['id']}/deactivate", json={"reason": "retired"}, headers=PHARMACIST)
    assert r.json()["is_active"] is False


async def test_doctor_licence_is_unique(client) -> None:
    await add_doctor(client, "MD-7")
    r = await client.post(f"{PREFIX}/doctors", json={"name": "Dr B", "licence_no": "md-7"}, headers=PHARMACIST)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_CODE"
