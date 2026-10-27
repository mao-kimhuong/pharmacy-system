"""Excel files for Import Product and the product export.

Layout (sheet "Products", one row per pack unit, grouped by SKU):

    sku | brand_name | ... | reorder_level | pack_unit | qty_in_base | barcode | sell_price_usd

Product columns may be repeated on every row of a SKU or left blank after the
first one. The row whose pack_unit equals base_unit (qty_in_base 1) is the base unit.

Safety (docs/spec.md → Injection and input attacks):
- Only real .xlsx files are read: checked from the content, not the name.
  Macro workbooks (.xlsm, vbaProject.bin) and anything else are refused.
- Zip bombs: limits on member count, total unpacked size and compression ratio.
- Values only: openpyxl with read_only=True, data_only=True (a formula gives
  its last saved value, never runs). XML is parsed with defusedxml.
- Exported text goes through pharmacy_shared.spreadsheet.safe_cell.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.spreadsheet import FORMULA_PREFIXES, safe_cell

from .common import clean

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 500
MAX_RATIO = 200
MAX_CELL_CHARS = 500

XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


@dataclass(frozen=True)
class Column:
    key: str
    product: bool  # product column (same on every row of a SKU) or pack unit column
    required: bool  # header must be present
    help: str


COLUMNS: tuple[Column, ...] = (
    Column("sku", True, True, "Your product code, e.g. PARA500. Capital letters, digits, . _ - /"),
    Column("brand_name", True, True, "Name on the pack, e.g. Panadol"),
    Column("generic_name", True, True, "Active ingredient, e.g. Paracetamol"),
    Column("strength", True, False, "e.g. 500mg, 250mg/5ml"),
    Column("dosage_form", True, False, "e.g. tablet, capsule, syrup, sachet"),
    Column("name_km", True, False, "Name in Khmer"),
    Column("category", True, False, "Category English name; must exist unless you allow new ones on commit"),
    Column("brand", True, False, "Brand English name; must exist unless you allow new ones on commit"),
    Column("manufacturer", True, False, "Maker, e.g. GSK"),
    Column("base_unit", True, True, "Smallest unit sold, e.g. tablet. Stock is counted in it"),
    Column("rx_only", True, False, "yes / no. Blank = no (yes for controlled medicines)"),
    Column("controlled_schedule", True, False, "Blank, I, II, III or IV. Controlled = always Rx-only"),
    Column("storage", True, False, "room or cold. Blank = room"),
    Column("reorder_level", True, False, "Re-order when stock (in base units) falls to this. Blank = 0"),
    Column("pack_unit", False, True, "tablet / strip / box ... One row per pack unit"),
    Column("qty_in_base", False, True, "How many base units it holds. 1 only on the base_unit row"),
    Column("barcode", False, False, "Unique across all products; blank = none"),
    Column("sell_price_usd", False, True, "Selling price in USD, e.g. 2.50"),
)
KEYS = tuple(c.key for c in COLUMNS)
PRODUCT_KEYS = tuple(c.key for c in COLUMNS if c.product)
REQUIRED_HEADERS = tuple(c.key for c in COLUMNS if c.required)


def _reject(message: str, **details: Any) -> AppError:
    return AppError(ErrorCode.FILE_REJECTED, message, status_code=422, details=details)


def check_xlsx(data: bytes) -> None:
    """Refuse anything that is not a plain .xlsx workbook, judged by content."""
    if len(data) > MAX_FILE_BYTES:
        raise _reject("The file is larger than 10 MB")
    if not data.startswith(b"PK\x03\x04"):
        raise _reject("This is not an Excel .xlsx file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise _reject("The workbook has too many parts")
            unpacked = sum(i.file_size for i in infos)
            if unpacked > MAX_UNPACKED_BYTES or any(
                i.compress_size and i.file_size / i.compress_size > MAX_RATIO for i in infos
            ):
                raise _reject("The workbook unpacks to an unusually large size")
            names = {i.filename for i in infos}
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise _reject("Workbooks with macros (.xlsm) are not accepted; save as .xlsx")
            if "[Content_Types].xml" not in names:
                raise _reject("This is not an Excel .xlsx file")
            content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise _reject("This is not an Excel .xlsx file") from exc
    if "macroEnabled" in content_types:
        raise _reject("Workbooks with macros (.xlsm) are not accepted; save as .xlsx")
    if XLSX_MAIN not in content_types:
        raise _reject(
            "This is not an Excel .xlsx workbook (.xltx templates and other files are not accepted)"
        )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else format(Decimal(repr(value)), "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = clean(value)[:MAX_CELL_CHARS]
    # Undo our own export escaping ('=...), so an exported file imports unchanged.
    if text.startswith("'") and text[1:2] and text[1:2] in FORMULA_PREFIXES:
        text = text[1:]
    return text


def _header_key(value: Any) -> str:
    key = clean(value).lower().replace(" ", "_").replace("-", "_")
    return {"sell_price": "sell_price_usd", "price": "sell_price_usd", "rx": "rx_only"}.get(key, key)


def read_rows(data: bytes) -> list[tuple[int, dict[str, str]]]:
    """(Excel row number, {column: text}) for every non-empty row."""
    check_xlsx(data)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001  any parse failure is the file's fault
        raise _reject("The workbook could not be read") from exc
    try:
        ws = wb["Products"] if "Products" in wb.sheetnames else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None) or ()
        positions: dict[str, int] = {}
        for i, cell in enumerate(header):
            key = _header_key(cell)
            if key in KEYS and key not in positions:
                positions[key] = i
        missing = [k for k in REQUIRED_HEADERS if k not in positions]
        if missing:
            raise _reject(f"Missing columns: {', '.join(missing)}. Use the template.", missing=missing)

        result: list[tuple[int, dict[str, str]]] = []
        for row_no, values in enumerate(rows, start=2):
            cells = {k: _text(values[i]) if i < len(values) else "" for k, i in positions.items()}
            if not any(cells.values()):
                continue
            if len(result) >= MAX_ROWS:
                raise _reject(f"Too many rows: at most {MAX_ROWS} per file")
            result.append((row_no, {k: cells.get(k, "") for k in KEYS}))
    finally:
        wb.close()
    if not result:
        raise _reject("The sheet has no product rows")
    return result


def write_workbook(sheets: list[tuple[str, list[str], list[list[Any]]]]) -> bytes:
    """Sheets of (title, header, rows). Every text cell is formula-escaped."""
    wb = Workbook()
    wb.remove(wb.active)
    for title, header, rows in sheets:
        ws = wb.create_sheet(title)
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([safe_cell(v) for v in row])
        for i, name in enumerate(header):
            width = max([len(str(name))] + [len(str(r[i])) for r in rows if i < len(r) and r[i] is not None])
            ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = min(
                max(width + 2, 10), 60
            )
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


TEMPLATE_EXAMPLE = [
    ["PARA500", "Panadol", "Paracetamol", "500mg", "tablet", "ប៉ារ៉ាសេតាម៉ុល", "Pain & fever", "Panadol",
     "GSK", "tablet", "no", "", "room", 200, "tablet", 1, "", "0.10"],
    ["PARA500", "", "", "", "", "", "", "", "", "", "", "", "", "", "strip", 10, "", "0.90"],
    ["PARA500", "", "", "", "", "", "", "", "", "", "", "", "", "", "box", 120, "", "10.00"],
]  # fmt: skip


def template() -> bytes:
    help_rows = [[c.key, "yes" if c.required else "", c.help] for c in COLUMNS]
    help_rows += [
        ["", "", ""],
        ["Rows", "", "One row per pack unit. Repeat the SKU on each row of the same product."],
        [
            "",
            "",
            "Product columns may be left blank after the SKU's first row; a different value is an error.",
        ],
        ["Updates", "", "A SKU that already exists is updated; blank cells keep the saved value."],
        ["", "", "Pack units are matched by name. Pack units not in the file are left as they are."],
        ["Values", "", "Only values are read. Formulas give their last saved value; macros are refused."],
    ]
    return write_workbook([
        ("Products", list(KEYS), TEMPLATE_EXAMPLE),
        ("Instructions", ["column", "required", "what to enter"], help_rows),
    ])  # fmt: skip
