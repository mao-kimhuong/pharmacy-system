import io

import pytest
from PIL import Image

from pharmacy_shared.errors import AppError
from pharmacy_shared.uploads import MAX_BYTES, check_upload


def jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x0112] = 6  # orientation: rotate 90
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_jpeg_exif_is_removed_and_orientation_applied() -> None:
    raw = jpeg_with_exif()
    assert b"SecretCam" in raw
    clean = check_upload(raw)
    assert clean.content_type == "image/jpeg" and clean.extension == "jpg"
    assert b"SecretCam" not in clean.data and b"Exif" not in clean.data
    with Image.open(io.BytesIO(clean.data)) as img:
        assert img.size == (20, 40)  # turned the right way up
        assert not img.getexif()


def test_png_text_chunks_are_removed() -> None:
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Comment", "patient Sok Dara 012345678")
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(out, format="PNG", pnginfo=info)
    clean = check_upload(out.getvalue())
    assert clean.content_type == "image/png" and b"Sok Dara" not in clean.data


def test_pdf_is_kept_but_active_content_refused() -> None:
    pdf = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF"
    assert check_upload(pdf).data == pdf
    with pytest.raises(AppError) as exc:
        check_upload(
            pdf.replace(
                b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>"
            )
        )
    assert exc.value.code == "FILE_REJECTED"


@pytest.mark.parametrize("data", [
    b"GIF89a....", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"MZ\x90\x00 an exe", b"",
    b"\xff\xd8\xff but not really a jpeg", b"\x89PNG\r\n\x1a\n broken",
])  # fmt: skip
def test_type_is_judged_by_content(data) -> None:
    with pytest.raises(AppError):
        check_upload(data)


def test_a_png_named_jpeg_is_still_checked_by_content() -> None:
    out = io.BytesIO()
    Image.new("RGB", (5, 5)).save(out, format="PNG")
    assert check_upload(out.getvalue()).content_type == "image/png"


def test_files_over_10_mb_are_refused() -> None:
    with pytest.raises(AppError, match="10 MB"):
        check_upload(b"%PDF-" + b"0" * MAX_BYTES)
