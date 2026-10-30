"""Rx photos / scans: checked by content, stored privately in SeaweedFS, and
streamed only through the service (auth, branch, permission, audit each time)."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from prescription_service.api.storage import get_storage
from prescription_service.db import db
from prescription_service.models import OutboxEvent

from .conftest import (
    CASHIER,
    PHARMACIST,
    PHARMACIST_PP2,
    PREFIX,
    S3_ENDPOINT,
    add_doctor,
    add_patient,
    add_product,
    add_rx,
)  # fmt: skip

pytestmark = pytest.mark.skipif(not S3_ENDPOINT, reason="TEST_S3_ENDPOINT not set (make test-db starts the store)")


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
async def rx(client) -> dict:  # noqa: ANN001
    await get_storage().ensure_bucket()
    p, d, m = await add_patient(client), await add_doctor(client), await add_product()
    return await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10}])


async def upload(client, rx: dict, name: str, data: bytes, headers=PHARMACIST):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/prescriptions/{rx['id']}/attachments", files={"file": (name, data)},
                             headers=headers)  # fmt: skip


async def test_upload_and_download_with_safe_headers_and_audit(client, rx) -> None:
    r = await upload(client, rx, 'វេជ្ជបញ្ជា "x"/../a.png', png())
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["content_type"] == "image/png"
    url = f"{PREFIX}/prescriptions/{rx['id']}/attachments/{att['id']}"
    r = await client.get(url, headers=PHARMACIST)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    disposition = r.headers["content-disposition"]
    assert disposition.startswith('inline; filename="') and "/" not in disposition.split("filename*=")[0]
    assert ".." not in disposition and disposition.count('"') == 2
    await client.get(url, headers=PHARMACIST)
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == "audit.recorded"))).scalars()
        assert sum(1 for x in rows if x.payload["action"] == "rx_attachment.viewed") == 2


async def test_download_checks_permission_and_branch(client, rx) -> None:
    att = (await upload(client, rx, "a.png", png())).json()
    url = f"{PREFIX}/prescriptions/{rx['id']}/attachments/{att['id']}"
    assert (await client.get(url, headers=CASHIER)).status_code == 403
    assert (await client.get(url, headers=PHARMACIST_PP2)).status_code == 404
    assert (await client.get(url)).status_code == 401


async def test_wrong_type_and_too_big_are_refused(client, rx) -> None:
    r = await upload(client, rx, "rx.png", b"MZ\x90\x00 not an image")
    assert r.status_code == 422 and r.json()["code"] == "FILE_REJECTED"
    r = await upload(client, rx, "rx.html", b"<html><script>alert(1)</script>")
    assert r.status_code == 422
    r = await upload(client, rx, "rx.pdf", b"%PDF-1.7\n1 0 obj << /OpenAction << /JS (app.alert(1)) >> >>")
    assert r.status_code == 422
    r = await upload(client, rx, "big.png", b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024))
    assert r.status_code == 413 and r.json()["code"] == "FILE_REJECTED"
    r = await upload(client, rx, "a.png", png(), headers=CASHIER)
    assert r.status_code == 403


async def test_store_keeps_no_original_name_and_no_exif(client, rx) -> None:
    img = Image.new("RGB", (20, 20), "red")
    exif = Image.Exif()
    exif[0x8825] = {2: (11.0, 33.0, 0.0)}  # GPS
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    att = (await upload(client, rx, "patient-name.jpg", buf.getvalue())).json()
    r = await client.get(f"{PREFIX}/prescriptions/{rx['id']}/attachments/{att['id']}", headers=PHARMACIST)
    assert r.headers["content-type"] == "image/jpeg"
    assert not Image.open(io.BytesIO(r.content)).getexif()
