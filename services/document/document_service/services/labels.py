"""Shelf and barcode labels as PDF.

Rendering: HTML + CSS → PDF with WeasyPrint, which shapes text with Pango and
HarfBuzz, so Khmer (stacked consonants, vowels written before the consonant)
comes out right. The font is Noto Sans Khmer, installed in the Docker image
(fonts-noto-core). Barcodes: Code128, drawn as SVG by python-barcode.

Every text value is HTML-escaped; nothing from a product reaches a shell or a
URL fetch (WeasyPrint's url fetcher only allows our own inline data: images).

Rules:
- Only active pack units of active products can be printed.
- At most `max_labels` labels per PDF.
"""

import base64
import html
import io
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from pharmacy_shared.errors import AppError, ErrorCode

from ..models import ProductPackUnit

Layout = Literal["shelf_50x30", "barcode_40x25", "a4_sheet"]
# Latin first, then Khmer: each character takes the first font that has it.
FONTS = '"Noto Sans", "DejaVu Sans", Helvetica, Arial, "Noto Sans Khmer", "Khmer OS", sans-serif'


@dataclass(frozen=True)
class Label:
    name_en: str
    name_km: str
    strength: str
    pack: str
    price: Decimal
    barcode: str | None
    rx: bool


def _pack_text(pack: ProductPackUnit) -> str:
    base = pack.product.base_unit
    return pack.name if pack.is_base else f"{pack.name} · {pack.qty_in_base} {base}"


def to_label(pack: ProductPackUnit) -> Label:
    p = pack.product
    return Label(
        name_en=p.brand_name if p.brand_name.casefold() == p.generic_name.casefold()
        else f"{p.brand_name} ({p.generic_name})",
        name_km=p.name_km,
        strength=" ".join(x for x in (p.strength, p.dosage_form) if x),
        pack=_pack_text(pack),
        price=pack.sell_price,
        barcode=pack.barcode,
        rx=p.is_rx_only,
    )  # fmt: skip


async def load_labels(session: AsyncSession, items: list[tuple[UUID, int]], max_labels: int) -> list[Label]:
    total = sum(copies for _, copies in items)
    if total > max_labels:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, f"At most {max_labels} labels per print", status_code=422,
            details={"labels": total},
        )  # fmt: skip
    ids = {pack_id for pack_id, _ in items}
    packs = {
        p.id: p
        for p in (await session.execute(select(ProductPackUnit).where(ProductPackUnit.id.in_(ids)))).scalars()
    }
    unknown = sorted(str(i) for i in ids if i not in packs)
    inactive = sorted(str(i) for i, p in packs.items() if not (p.is_active and p.product.is_active))
    if unknown or inactive:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Some pack units are unknown or inactive",
            status_code=422,
            details={"unknown": unknown, "inactive": inactive},
        )
    return [to_label(packs[pack_id]) for pack_id, copies in items for _ in range(copies)]


def barcode_svg(code: str, module_height_mm: float) -> str:
    """Code128 as an SVG data URI (no text: the digits are printed under it)."""
    from barcode import Code128
    from barcode.writer import SVGWriter

    out = io.BytesIO()
    Code128(code, writer=SVGWriter()).write(
        out, options={"write_text": False, "module_width": 0.2, "module_height": module_height_mm,
                      "quiet_zone": 1.5, "background": "white", "foreground": "black"},
    )  # fmt: skip
    return "data:image/svg+xml;base64," + base64.b64encode(out.getvalue()).decode()


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _label_html(label: Label, layout: Layout) -> str:
    small = layout == "barcode_40x25"
    bar = ""
    if label.barcode:
        bar = (
            f'<img class="bar" src="{barcode_svg(label.barcode, 6 if small else 7)}" alt="">'
            f'<div class="code">{_e(label.barcode)}</div>'
        )
    rx = '<span class="rx">Rx</span>' if label.rx else ""
    km = f'<div class="km" lang="km">{_e(label.name_km)}</div>' if label.name_km else ""
    strength = f'<div class="strength">{_e(label.strength)}</div>' if label.strength and not small else ""
    return (
        '<div class="label">'
        f'<div class="en">{rx}{_e(label.name_en)}</div>{km}{strength}'
        f'<div class="row"><div class="pack">{_e(label.pack)}</div>'
        f'<div class="price">${label.price:,.2f}</div></div>'
        f"{bar}</div>"
    )


_CSS = {
    "shelf_50x30": "@page { size: 50mm 30mm; margin: 0 } .label { width: 50mm; height: 30mm; "
    "page-break-after: always; padding: 1.5mm 2mm; } .en { font-size: 7.5pt } .km { font-size: 7.5pt } "
    ".price { font-size: 11pt } .bar { height: 7mm }",
    "barcode_40x25": "@page { size: 40mm 25mm; margin: 0 } .label { width: 40mm; height: 25mm; "
    "page-break-after: always; padding: 1.2mm 1.5mm; } .en { font-size: 6.5pt; max-height: 1.2em } "
    ".km { font-size: 6.5pt } .price { font-size: 8.5pt } .bar { height: 6.5mm }",
    # 3 × 8 labels of 64 × 34 mm on A4, a common label sheet size.
    "a4_sheet": "@page { size: A4; margin: 12mm 9mm } body { display: flex; flex-wrap: wrap; "
    "align-content: flex-start } .label { width: 64mm; height: 34mm; padding: 2mm 2.5mm; "
    "border: 0.2mm dashed #bbb; break-inside: avoid } .en { font-size: 8.5pt } .km { font-size: 8.5pt } "
    ".price { font-size: 12pt } .bar { height: 8mm }",
}
_BASE_CSS = (
    f"* {{ box-sizing: border-box; margin: 0 }} body {{ font-family: {FONTS}; color: #000 }} "
    ".label { overflow: hidden; display: flex; flex-direction: column } "
    ".en { font-weight: 700; line-height: 1.15; max-height: 2.4em; overflow: hidden } "
    ".km { line-height: 1.5; max-height: 1.6em; overflow: hidden; white-space: nowrap } "
    ".row { display: flex; justify-content: space-between; align-items: baseline; gap: 1mm } "
    ".strength, .pack { font-size: 6.5pt; overflow: hidden; white-space: nowrap; text-overflow: ellipsis } "
    ".pack { flex: 1 1 auto; min-width: 0 } "
    ".price { flex: 0 0 auto; font-weight: 700; white-space: nowrap } "
    ".rx { border: 0.2mm solid #000; border-radius: 0.6mm; padding: 0 0.6mm; margin-right: 0.8mm; "
    "font-size: 85% } "
    ".bar { display: block; margin: 0.5mm auto 0; max-width: 100% } "
    ".code { font-size: 6pt; text-align: center; letter-spacing: 0.3pt } "
)


def build_html(labels: Iterable[Label], layout: Layout) -> str:
    body = "".join(_label_html(label, layout) for label in labels)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_BASE_CSS}{_CSS[layout]}</style></head><body>{body}</body></html>"
    )


def _render(page_html: str) -> bytes:
    # Imported here: needs Pango (in the Docker image; `brew install pango` on a Mac).
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    # Our barcodes are inline data: images; nothing else is ever fetched (no SSRF).
    fetcher = URLFetcher(allowed_protocols={"data"})
    return HTML(string=page_html, url_fetcher=fetcher).write_pdf()


async def render_pdf(labels: list[Label], layout: Layout) -> bytes:
    # CPU-bound: keep it off the event loop.
    return await run_in_threadpool(_render, build_html(labels, layout))
