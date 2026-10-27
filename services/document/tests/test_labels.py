import io

import pytest
from pypdf import PdfReader

from .conftest import CASHIER, OWNER, PHARMACIST, PREFIX, needs_pdf, pack_id, seed


def body(items: list[tuple[str, int]], layout: str = "shelf_50x30") -> dict:
    return {"type": "label", "layout": layout, "items": [{"pack_unit_id": i, "copies": c} for i, c in items]}


def fonts(reader: PdfReader) -> set[str]:
    names = set()
    for page in reader.pages:
        for font in (page.get("/Resources") or {}).get("/Font", {}).values():
            names.add(str(font.get_object().get("/BaseFont")))
    return names


@needs_pdf
@pytest.mark.parametrize(("layout", "copies", "pages"), [
    ("shelf_50x30", 3, 3), ("barcode_40x25", 2, 2), ("a4_sheet", 30, 2),
])  # fmt: skip
async def test_labels_are_a_pdf_with_the_product_name(client, layout, copies, pages) -> None:
    product = await seed()
    r = await client.post(
        f"{PREFIX}/render", json=body([(pack_id(product), copies)], layout), headers=PHARMACIST
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(r.content))
    assert len(reader.pages) == pages
    page_text = reader.pages[0].extract_text()
    assert "Panadol (Paracetamol)" in page_text
    assert "$5.00" in page_text and "8841000100031" in page_text
    assert "box · 120 tablet" in page_text
    # Khmer is drawn with a Khmer font (shaped by HarfBuzz), not missing-glyph boxes.
    assert any("Khmer" in name for name in fonts(reader)), fonts(reader)
    # Text extraction of shaped Khmer varies by font and extractor (spaces appear
    # between clusters), so only the first word is compared, ignoring spaces.
    assert "ប៉ាណាដុល" in "".join(page_text.split())


@needs_pdf
async def test_rx_products_are_marked_and_labels_without_barcode_still_print(client) -> None:
    product = await seed(is_rx_only=True)
    product["pack_units"][1]["barcode"] = None
    product = await seed(medicine_id=product["medicine_id"], version=2, is_rx_only=True,
                         pack_units=product["pack_units"])  # fmt: skip
    r = await client.post(f"{PREFIX}/render", json=body([(pack_id(product), 1)]), headers=OWNER)
    assert r.status_code == 200
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    assert "Rx" in text and "8841000100031" not in text


@needs_pdf
async def test_product_text_is_escaped_not_run_as_html(client) -> None:
    product = await seed(brand_name="<b>Bold</b><img src='http://evil/x.png'>", generic_name="x")
    r = await client.post(f"{PREFIX}/render", json=body([(pack_id(product), 1)]), headers=OWNER)
    assert r.status_code == 200
    assert "<b>Bold</b>" in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()


async def test_cashier_cannot_print_labels(client) -> None:
    product = await seed()
    r = await client.post(f"{PREFIX}/render", json=body([(pack_id(product), 1)]), headers=CASHIER)
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"


async def test_unknown_and_inactive_pack_units_are_refused(client) -> None:
    product = await seed()
    product["pack_units"][1]["is_active"] = False
    product = await seed(medicine_id=product["medicine_id"], version=2, pack_units=product["pack_units"])
    unknown = "00000000-0000-0000-0000-000000000001"
    r = await client.post(f"{PREFIX}/render", json=body([(pack_id(product), 1), (unknown, 1)]), headers=OWNER)
    assert r.status_code == 422
    assert r.json()["details"] == {"unknown": [unknown], "inactive": [pack_id(product)]}


async def test_deactivated_product_cannot_be_printed(client) -> None:
    product = await seed(is_active=False)
    r = await client.post(f"{PREFIX}/render", json=body([(pack_id(product, "tablet"), 1)]), headers=OWNER)
    assert r.status_code == 422


async def test_too_many_labels_are_refused(client) -> None:
    product = await seed()
    r = await client.post(
        f"{PREFIX}/render",
        json=body([(pack_id(product), 500), (pack_id(product, "tablet"), 500), (pack_id(product), 1)]),
        headers=OWNER,
    )
    assert r.status_code == 422 and r.json()["details"] == {"labels": 1001}


@pytest.mark.parametrize("change", [
    {"type": "receipt"}, {"layout": "huge"}, {"items": []}, {"extra": 1},
])  # fmt: skip
async def test_bad_requests_are_refused(client, change) -> None:
    product = await seed()
    r = await client.post(f"{PREFIX}/render", json={**body([(pack_id(product), 1)]), **change}, headers=OWNER)
    assert r.status_code == 422
