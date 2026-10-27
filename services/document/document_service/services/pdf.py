"""HTML → PDF for every document (labels, purchase orders; receipts and
invoices later).

WeasyPrint shapes text with Pango and HarfBuzz, so Khmer (stacked consonants,
vowels written before the consonant) comes out right; fonts are Noto Sans +
Noto Sans Khmer from fonts-noto-core in the image. Never ReportLab for Khmer.

All data put into HTML goes through `e()` (HTML-escaped). WeasyPrint may fetch
nothing but our own inline data: images (no SSRF).
"""

import html

from starlette.concurrency import run_in_threadpool

# Latin first, then Khmer: each character takes the first font that has it.
FONTS = '"Noto Sans", "DejaVu Sans", Helvetica, Arial, "Noto Sans Khmer", "Khmer OS", sans-serif'


def e(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _render(page_html: str) -> bytes:
    # Imported here: needs Pango (in the Docker image; `brew install pango` on a Mac).
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    fetcher = URLFetcher(allowed_protocols={"data"})
    return HTML(string=page_html, url_fetcher=fetcher).write_pdf()


async def html_to_pdf(page_html: str) -> bytes:
    # CPU-bound: keep it off the event loop.
    return await run_in_threadpool(_render, page_html)
