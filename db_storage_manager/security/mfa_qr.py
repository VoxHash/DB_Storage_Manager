"""QR image for TOTP enrolment.

The otpauth URI is the same string ``MFAProvider.provisioning_uri`` gives an
authenticator app. The PNG is only a picture of that URI. The secret stays
pending until a code from the app verifies; this module never writes users.
"""

from __future__ import annotations

import io
from typing import List

import qrcode
from PIL import Image


def qr_modules(data: str, *, border: int = 2) -> List[List[bool]]:
    """Boolean module matrix for ``data`` (True = dark)."""
    if not data:
        raise ValueError("QR data must not be empty")
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=border,
    )
    code.add_data(data)
    code.make(fit=True)
    return code.get_matrix()


def qr_png_bytes(data: str, *, box_size: int = 6, border: int = 2) -> bytes:
    """PNG of a QR code that encodes ``data`` (the otpauth URI)."""
    if not data:
        raise ValueError("QR data must not be empty")
    if box_size < 1 or border < 0:
        raise ValueError("invalid QR geometry")
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    code.add_data(data)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_modules(png: bytes, *, box_size: int = 6, border: int = 2) -> List[List[bool]]:
    """Sample a QR PNG back into a module matrix (nearest pixel at each cell)."""
    image = Image.open(io.BytesIO(png)).convert("L")
    width, height = image.size
    modules = width // box_size
    if modules < 21 or modules * box_size != width or height != width:
        raise ValueError("PNG is not a square QR image at this box size")
    out: List[List[bool]] = []
    for y in range(modules):
        row: List[bool] = []
        for x in range(modules):
            # Centre of the module. Dark pixels are the QR data.
            pixel = image.getpixel((x * box_size + box_size // 2, y * box_size + box_size // 2))
            row.append(pixel < 128)
        out.append(row)
    if border and out[0][0]:
        # Quiet zone is light. A dark corner means the geometry does not match.
        raise ValueError("QR quiet zone is missing")
    return out
