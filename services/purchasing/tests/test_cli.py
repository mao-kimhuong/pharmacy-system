from purchasing_service.cli import republish

from .conftest import add_product, create_po, create_supplier, outbox


async def test_republish_resends_open_purchase_orders(client) -> None:
    supplier = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, supplier, [(para, "box", 2, "4.00")], send=True)
    before = len(await outbox())
    assert await republish() == 1
    new = (await outbox())[before:]
    assert [t for t, _ in new] == ["purchase_order.updated"] and new[0][1]["number"] == po["number"]
