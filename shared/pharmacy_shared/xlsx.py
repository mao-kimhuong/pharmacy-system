"""Reading and writing .xlsx files safely (imports and exports in any service).

Needs openpyxl + defusedxml (`pharmacy-shared[xlsx]`); only services that
import this module install them.

Safety (docs/spec.md → Injection and input attacks):
- Only real .xlsx files are read: checked from the content, not the name.
  Macro workbooks (.xlsm, vbaProject.bin) and anything else are refused.
- Zip bombs: limits on member count, total unpacked size and compression ratio.
- Values only: openpyxl with read_only=True, data_only=True (a formula gives
  its last saved value, never runs). XML is parsed with defusedxml.
- Exported text goes through pharmacy_shared.spreadsheet.safe_cell.
"""

import io
import unicodedata
import zipfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from .errors import AppError, ErrorCode
from .spreadsheet import FORMULA_PREFIXES, safe_cell

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 500
MAX_RATIO = 200
MAX_CELL_CHARS = 500

XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def reject(message: str, **details: Any) -> AppError:
    return AppError(ErrorCode.FILE_REJECTED, message, status_code=422, details=details)


def check_xlsx(data: bytes) -> None:
    """Refuse anything that is not a plain .xlsx workbook, judged by content."""
    if len(data) > MAX_FILE_BYTES:
        raise reject("The file is larger than 10 MB")
    if not data.startswith(b"PK\x03\x04"):
        raise reject("This is not an Excel .xlsx file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise reject("The workbook has too many parts")
            unpacked = sum(i.file_size for i in infos)
            if unpacked > MAX_UNPACKED_BYTES or any(
                i.compress_size and i.file_size / i.compress_size > MAX_RATIO for i in infos
            ):
                raise reject("The workbook unpacks to an unusually large size")
            names = {i.filename for i in infos}
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise reject("Workbooks with macros (.xlsm) are not accepted; save as .xlsx")
            if "[Content_Types].xml" not in names:
                raise reject("This is not an Excel .xlsx file")
            content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise reject("This is not an Excel .xlsx file") from exc
    if "macroEnabled" in content_types:
        raise reject("Workbooks with macros (.xlsm) are not accepted; save as .xlsx")
    if XLSX_MAIN not in content_types:
        raise reject("This is not an Excel .xlsx workbook (.xltx templates and other files are not accepted)")


def cell_text(value: Any) -> str:
    """A cell as trimmed NFC text (Khmer compares the same however it was typed)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else format(Decimal(repr(value)), "f")
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = unicodedata.normalize("NFC", str(value)).strip()[:MAX_CELL_CHARS]
    # Undo our own export escaping ('=...), so an exported file imports unchanged.
    if text.startswith("'") and text[1:2] and text[1:2] in FORMULA_PREFIXES:
        text = text[1:]
    return text


def _header_key(value: Any, aliases: Mapping[str, str]) -> str:
    key = cell_text(value).lower().replace(" ", "_").replace("-", "_")
    return aliases.get(key, key)


def read_sheet(
    data: bytes,
    *,
    keys: Sequence[str],
    required: Sequence[str],
    sheet: str,
    aliases: Mapping[str, str] | None = None,
    max_rows: int = MAX_ROWS,
) -> list[tuple[int, dict[str, str]]]:
    """(Excel row number, {column: text}) for every non-empty row of `sheet`
    (or the first sheet). Headers are matched loosely ("Sell Price" = sell_price)."""
    check_xlsx(data)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001  any parse failure is the file's fault
        raise reject("The workbook could not be read") from exc
    try:
        ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None) or ()
        positions: dict[str, int] = {}
        for i, cell in enumerate(header):
            key = _header_key(cell, aliases or {})
            if key in keys and key not in positions:
                positions[key] = i
        missing = [k for k in required if k not in positions]
        if missing:
            raise reject(f"Missing columns: {', '.join(missing)}. Use the template.", missing=missing)

        result: list[tuple[int, dict[str, str]]] = []
        for row_no, values in enumerate(rows, start=2):
            cells = {k: cell_text(values[i]) if i < len(values) else "" for k, i in positions.items()}
            if not any(cells.values()):
                continue
            if len(result) >= max_rows:
                raise reject(f"Too many rows: at most {max_rows} per file")
            result.append((row_no, {k: cells.get(k, "") for k in keys}))
    finally:
        wb.close()
    if not result:
        raise reject("The sheet has no rows")
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
