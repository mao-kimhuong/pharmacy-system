"""A report as a PDF (internal /render/table, for the reports service)."""

import base64
import io

import pytest
from pypdf import PdfReader

from document_service.main import app

from .conftest import needs_pdf

TOKEN = "test-service-token-0123456789abcdef"
BODY = {"title": "Sale Detail", "filters": {"date_from": "2026-10-01", "branch_id": "PP1"},
        "columns": [{"label": "SKU"}, {"label": "Medicine"}, {"label": "Net", "kind": "money"}],
        "rows": [["PARA500", "ប៉ាណាដុល Panadol", "8.00"], ["ORS", "ORS", "0.30"]], "summary": {"net": "8.30"}}  # fmt: skip


@pytest.fixture(autouse=True)
def token():
    old = app.state.settings.service_token
    app.state.settings.service_token = TOKEN
    yield
    app.state.settings.service_token = old


async def test_needs_the_service_token(client) -> None:
    assert (await client.post("/internal/v1/render/table", json=BODY)).status_code == 401


@needs_pdf
async def test_table_pdf(client) -> None:
    r = await client.post("/internal/v1/render/table", json=BODY, headers={"X-Service-Token": TOKEN})
    assert r.status_code == 200, r.text
    pdf = base64.b64decode(r.json()["pdf_base64"])
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    for expected in ("Sale Detail", "PARA500", "Panadol", "8.30", "date_from"):
        assert expected in text, expected
