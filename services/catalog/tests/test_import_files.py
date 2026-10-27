"""File safety for Import Product and the exports (docs/spec.md → Injection and
input attacks: formula injection, macro files, file type from content, 10 MB)."""

import io
import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from .conftest import OWNER, PREFIX, commit, count, create_medicine, product_rows, upload, xlsx


def with_macros(content: bytes) -> bytes:
    """Turn an .xlsx into what Excel writes for an .xlsm."""
    src = zipfile.ZipFile(io.BytesIO(content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"sheet.main+xml", b"sheet.macroEnabled.main+xml")
            dst.writestr(item, data)
        dst.writestr("xl/vbaProject.bin", b"\x00" * 64)
    return out.getvalue()


async def rejected(client, content: bytes, name: str = "products.xlsx") -> dict:
    r = await upload(client, content, name=name)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "FILE_REJECTED"
    return r.json()


async def test_macro_workbook_is_refused_even_when_named_xlsx(client) -> None:
    body = await rejected(client, with_macros(xlsx(product_rows())))
    assert "macros" in body["message"]
    await rejected(client, with_macros(xlsx(product_rows())), name="products.xlsm")


@pytest.mark.parametrize(
    "content",
    [
        b"sku,brand_name\nPARA500,Panadol\n",  # CSV renamed to .xlsx
        b"%PDF-1.7 fake",
        b"PK\x03\x04 not really a zip",
        b"",
    ],
)
async def test_files_that_are_not_xlsx_by_content_are_refused(client, content) -> None:
    await rejected(client, content)


async def test_a_zip_that_is_not_a_workbook_is_refused(client) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("hello.txt", "hi")
    await rejected(client, out.getvalue())


async def test_zip_bomb_is_refused(client) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "x")
        zf.writestr("xl/worksheets/sheet1.xml", b"0" * 50_000_000)
    body = await rejected(client, out.getvalue())
    assert "large" in body["message"]


async def test_files_over_10_mb_are_refused(client) -> None:
    await rejected(client, b"PK\x03\x04" + b"0" * (10 * 1024 * 1024))


async def test_missing_columns_are_named(client) -> None:
    body = await rejected(client, xlsx([{"sku": "A"}], header=["sku", "brand_name"]))
    assert "generic_name" in body["details"]["missing"]


async def test_headers_are_matched_loosely_and_the_first_sheet_is_used(client) -> None:
    header = ["SKU", "Brand Name", "generic name", "Base Unit", "Pack Unit", "Qty In Base", "Sell Price"]
    rows = [{"SKU": "ORS", "Brand Name": "ORS", "generic name": "Oral rehydration salts",
             "Base Unit": "sachet", "Pack Unit": "sachet", "Qty In Base": 1, "Sell Price": 0.15}]  # fmt: skip
    r = await upload(client, xlsx(rows, header=header, sheet="Sheet1"))
    assert r.status_code == 201 and r.json()["status"] == "validated", r.text


async def test_formulas_are_never_read_as_text_or_run(client) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(
        ["sku", "brand_name", "generic_name", "base_unit", "pack_unit", "qty_in_base", "sell_price_usd"]
    )
    ws.append(["F1", '=HYPERLINK("http://evil","x")', "Paracetamol", "tablet", "tablet", "=0+1", "0.10"])
    out = io.BytesIO()
    wb.save(out)
    imp = (await upload(client, out.getvalue())).json()
    d = (await client.get(f"{PREFIX}/imports/{imp['id']}", headers=OWNER)).json()
    row = d["rows"][0]
    # No cached value saved → empty cells, never the formula text.
    assert row["data"]["brand_name"] == "" and row["data"]["qty_in_base"] == ""
    assert {e["field"] for e in row["errors"]} >= {"brand_name", "qty_in_base"}


async def test_khmer_text_survives_the_excel_file(client) -> None:
    rows = product_rows(name_km="អាម៉ុកស៊ីស៊ីលីន ៥០០ មីលីក្រាម")
    imp = (await upload(client, xlsx(rows))).json()
    await commit(client, imp["id"])
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    assert m["name_km"] == "អាម៉ុកស៊ីស៊ីលីន ៥០០ មីលីក្រាម"


async def test_template_has_every_column_and_an_instructions_sheet(client) -> None:
    r = await client.get(f"{PREFIX}/imports/template.xlsx", headers=OWNER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Products", "Instructions"]
    header = [c.value for c in wb["Products"][1]]
    assert header[0] == "sku" and "sell_price_usd" in header
    assert await count("imports") == 0


async def test_export_escapes_formula_cells_and_imports_back_unchanged(client) -> None:
    await create_medicine(client, sku="EVIL1", brand_name="=cmd|' /C calc'!A0", generic_name="+SUM(1)",
                          manufacturer="@evil", strength="-5mg", pack_units=[])  # fmt: skip
    r = await client.get(f"{PREFIX}/medicines/export.xlsx", headers=OWNER)
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content))["Products"]
    header = [c.value for c in ws[1]]
    row = dict(zip(header, [c.value for c in ws[2]], strict=True))
    assert row["brand_name"] == "'=cmd|' /C calc'!A0"
    assert (
        row["generic_name"] == "'+SUM(1)" and row["manufacturer"] == "'@evil" and row["strength"] == "'-5mg"
    )
    assert all(c.data_type != "f" for c in ws[2])  # nothing is a formula

    imp = (await upload(client, r.content)).json()
    assert imp["status"] == "validated"
    done = (await commit(client, imp["id"])).json()
    assert done["updated_count"] == 0  # the escaping is undone on import
