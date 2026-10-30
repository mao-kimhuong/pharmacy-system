"""Rx photos and scans. Rules:

- Upload (prescriptions.manage): JPEG, PNG or PDF by content,
  at most 10 MB, EXIF removed, PDFs with active content refused
  (pharmacy_shared.uploads). Stored under a random key in the private file store;
  the original name only in the database. Not on cancelled prescriptions.
- Download only through this service: GET /prescriptions/{id}/attachments/{att}
  checks the user, the branch and prescriptions.view on every request and
  writes a User Log entry each time. Never a public or presigned link.
"""

import re
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.storage import Storage
from pharmacy_shared.uploads import check_upload

from ..models import RxAttachment
from .common import audit, not_found
from .prescriptions import get_rx, state_error

_UNSAFE = re.compile(r"[^\w.\- ()ក-៿]")


def safe_filename(name: str, extension: str) -> str:
    """For Content-Disposition: letters, digits, Khmer, . - _ ( ) and spaces only."""
    stem = _UNSAFE.sub("_", (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(" .") or "prescription"
    stem = stem[:100]
    return stem if stem.lower().endswith(f".{extension}") else f"{stem}.{extension}"


def content_disposition(name: str) -> str:
    """inline; an ASCII name for old clients plus the UTF-8 (Khmer) name (RFC 6266)."""
    ascii_name = name.encode("ascii", "ignore").decode() or "prescription"
    ascii_name = (
        ascii_name.replace('"', "") if not ascii_name.startswith(".") else "prescription" + ascii_name
    )
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


async def upload(
    session: AsyncSession, actor: CurrentUser, storage: Storage, rx_id: UUID, filename: str, data: bytes
) -> RxAttachment:
    rx = await get_rx(session, actor, rx_id, lock=True)
    if rx.status == "cancelled":
        raise state_error("A cancelled prescription takes no attachments", rx.status)
    clean = check_upload(data)
    key = f"rx/{uuid4()}"
    await storage.put(key, clean.data, clean.content_type)
    att = RxAttachment(prescription_id=rx.id, storage_key=key, original_filename=(filename or "")[:255],
                       content_type=clean.content_type, size_bytes=len(clean.data), uploaded_by=actor.id)  # fmt: skip
    session.add(att)
    await session.flush()
    audit(session, actor, "rx_attachment.uploaded", "prescription", rx.id, branch_id=rx.branch_id,
          after={"attachment_id": str(att.id), "type": att.content_type, "bytes": att.size_bytes})  # fmt: skip
    await session.commit()
    return att


async def download(
    session: AsyncSession, actor: CurrentUser, storage: Storage, rx_id: UUID, attachment_id: UUID
) -> tuple[RxAttachment, bytes]:
    rx = await get_rx(session, actor, rx_id)
    att = next((a for a in rx.attachments if a.id == attachment_id), None)
    if att is None:
        raise not_found("Attachment")
    data = await storage.get(att.storage_key)
    audit(session, actor, "rx_attachment.viewed", "prescription", rx.id, branch_id=rx.branch_id,
          after={"attachment_id": str(att.id)})  # fmt: skip
    await session.commit()
    return att, data
