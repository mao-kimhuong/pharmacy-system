from uuid import UUID, uuid4

from sqlalchemy import select

from document_service.db import db
from document_service.models import ProcessedMessage, Product, ProductPackUnit
from document_service.services.events import handle_event
from pharmacy_shared.consumer import process_message

from .conftest import medicine_event


async def apply(event_type: str, payload: dict, message_id: UUID | None = None) -> bool:
    return await process_message(
        db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload
    )


async def product(medicine_id: str) -> Product | None:
    async with db.sessionmaker() as session:
        return (
            await session.execute(select(Product).where(Product.id == UUID(medicine_id)))
        ).scalar_one_or_none()


async def test_medicine_events_keep_a_local_copy(client) -> None:
    created = medicine_event(version=1)
    await apply("medicine.created", created)
    p = await product(created["medicine_id"])
    assert p.brand_name == "Panadol" and p.name_km == "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល"
    assert {u.name: str(u.sell_price) for u in p.pack_units} == {"tablet": "0.05", "box": "5.00"}

    updated = {**created, "version": 2, "is_active": False}
    updated["pack_units"] = [dict(u) for u in created["pack_units"]]
    updated["pack_units"][1]["sell_price"] = "5.50"
    await apply("medicine.deactivated", updated)
    p = await product(created["medicine_id"])
    assert p.is_active is False and p.version == 2
    assert {u.name: str(u.sell_price) for u in p.pack_units}["box"] == "5.50"


async def test_an_older_event_does_not_overwrite_a_newer_copy(client) -> None:
    newer = medicine_event(version=3, brand_name="Panadol Extra")
    await apply("medicine.updated", newer)
    older = {**newer, "version": 2, "brand_name": "Panadol"}
    await apply("medicine.updated", older)
    assert (await product(newer["medicine_id"])).brand_name == "Panadol Extra"


async def test_a_repeated_message_is_processed_once(client) -> None:
    payload = medicine_event()
    message_id = uuid4()
    assert await apply("medicine.created", payload, message_id) is True
    assert await apply("medicine.created", payload, message_id) is False
    async with db.sessionmaker() as session:
        count = len((await session.execute(select(ProductPackUnit))).scalars().all())
    assert count == 2


async def test_other_events_are_ignored(client) -> None:
    await apply("category.created", {"id": str(uuid4()), "name_en": "x"})
    async with db.sessionmaker() as session:
        assert (await session.execute(select(Product))).first() is None
