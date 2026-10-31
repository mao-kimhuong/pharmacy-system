"""Report exports: CSV and XLSX made here, PDF by the document service
(/internal/v1/render/table). The rows are the ones the user may see: hidden
(cost) columns were dropped before (common.drop_hidden). Every text cell goes
through safe_cell (no formula injection), also in CSV."""

import base64
import csv
import io
from typing import Any

from pharmacy_shared.internal import InternalClient
from pharmacy_shared.spreadsheet import safe_cell
from pharmacy_shared.xlsx import XLSX_MEDIA_TYPE, write_workbook

from .common import Filters, Result

MEDIA = {"csv": "text/csv; charset=utf-8", "xlsx": XLSX_MEDIA_TYPE, "pdf": "application/pdf"}


def _matrix(result: Result) -> tuple[list[str], list[list[Any]]]:
    keys = [c.key for c in result.columns]
    return [c.label for c in result.columns], [[r.get(k) for k in keys] for r in result.rows]


def to_csv(result: Result) -> bytes:
    header, rows = _matrix(result)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else safe_cell(v) for v in row])
    return ("﻿" + out.getvalue()).encode()  # BOM: Excel opens Khmer text as UTF-8


def to_xlsx(result: Result) -> bytes:
    header, rows = _matrix(result)
    return write_workbook([(result.title[:31], header, rows)])


async def to_pdf(document: InternalClient, result: Result, f: Filters, user_id: Any) -> bytes:
    header, rows = _matrix(result)
    out = await document.post("/render/table", {
        "title": result.title, "filters": f.as_dict(),
        "columns": [{"label": c.label, "kind": c.kind} for c in result.columns],
        "rows": [["" if v is None else str(v) for v in row] for row in rows],
        "summary": {k: str(v) for k, v in result.summary.items()},
    })  # fmt: skip
    return base64.b64decode(out["pdf_base64"])
