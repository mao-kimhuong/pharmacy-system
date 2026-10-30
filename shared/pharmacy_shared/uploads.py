"""Checking uploaded files (Rx photos and scans). Rules:

- At most 10 MB.
- JPEG, PNG or PDF only, judged by the first bytes of the content (magic bytes),
  never by the file name or the browser's content type.
- Images are opened and saved again without metadata: EXIF (GPS position,
  camera, time) and PNG text chunks are gone; the EXIF orientation is applied
  first so the picture still shows the right way up. A file that cannot be
  decoded as the image it claims to be is refused.
- PDFs are kept as uploaded but refused when they carry active content
  (JavaScript, launch actions, embedded files).
- Anything else → FILE_REJECTED (422).
Needs Pillow (`pharmacy-shared[uploads]`).
"""

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import AppError, ErrorCode

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000  # decompression bombs
_PDF_ACTIVE = re.compile(
    rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|OpenAction\s*<<[^>]*?/S\s*/JavaScript)\b"
)


@dataclass(frozen=True)
class CleanFile:
    data: bytes
    content_type: str
    extension: str


def _reject(message: str) -> AppError:
    return AppError(ErrorCode.FILE_REJECTED, message, status_code=422)


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _clean_image(data: bytes, kind: str) -> bytes:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != kind.upper():
                raise _reject("The picture is not the type it claims to be")
            img.load()
            img = ImageOps.exif_transpose(img)
            out = io.BytesIO()
            if kind == "jpeg":
                img.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)  # no exif=…: none kept
            else:
                img.save(out, format="PNG", optimize=True)  # no pnginfo: text chunks dropped
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise _reject("The picture could not be read") from exc


def check_upload(data: bytes) -> CleanFile:
    if not data:
        raise _reject("The file is empty")
    if len(data) > MAX_BYTES:
        raise _reject("The file is larger than 10 MB")
    kind = sniff(data)
    if kind == "image/jpeg":
        return CleanFile(_clean_image(data, "jpeg"), kind, "jpg")
    if kind == "image/png":
        return CleanFile(_clean_image(data, "png"), kind, "png")
    if kind == "application/pdf":
        if _PDF_ACTIVE.search(data):
            raise _reject("PDFs with scripts, actions or embedded files are not accepted")
        return CleanFile(data, kind, "pdf")
    raise _reject("Only JPEG, PNG or PDF files are accepted")
