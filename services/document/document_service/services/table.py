"""A report as a PDF (A4 landscape, Khmer/English): title, filters, columns, rows
and totals. Called by the reports service only (/internal/v1/render/table); the
rows are already the ones the user may see (no hidden cost columns)."""

from typing import Any

from pharmacy_shared import clock

from .pdf import FONTS, e, html_to_pdf

RIGHT = {"money", "qty", "pct", "khr"}


def table_html(data: dict[str, Any]) -> str:
    cols = data["columns"]
    head = "".join(f"<th class='{'r' if c.get('kind') in RIGHT else ''}'>{e(c['label'])}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td class='{'r' if c.get('kind') in RIGHT else ''}'>{e(v)}</td>" for c, v in zip(cols, row, strict=False))
        + "</tr>" for row in data["rows"]
    )  # fmt: skip
    filters = " · ".join(f"{e(k)}: {e(v)}" for k, v in (data.get("filters") or {}).items())
    summary = " · ".join(f"<b>{e(k)}</b> {e(v)}" for k, v in (data.get("summary") or {}).items())
    css = f"""
      @page {{ size: A4 landscape; margin: 10mm 8mm 12mm;
              @bottom-right {{ content: "Page " counter(page) " / " counter(pages); font-size: 7pt }} }}
      body {{ font-family: {FONTS}; font-size: 7.5pt; color: #111 }} h1 {{ font-size: 13pt; margin: 0 0 1mm }}
      .sub {{ color: #555; margin-bottom: 2mm }} table {{ width: 100%; border-collapse: collapse }}
      th {{ text-align: left; border-bottom: 0.3mm solid #000; padding: 1mm; font-size: 7pt }}
      td {{ border-bottom: 0.15mm solid #ddd; padding: 0.8mm 1mm; vertical-align: top }} .r {{ text-align: right }}
      thead {{ display: table-header-group }} tr {{ page-break-inside: avoid }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <h1>{e(data["title"])}</h1>
      <div class="sub">{filters} · printed {e(clock.now().astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M"))}</div>
      {f'<div class="sub">{summary}</div>' if summary else ""}
      <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
    </body></html>"""


async def render(data: dict[str, Any]) -> bytes:
    return await html_to_pdf(table_html(data))
