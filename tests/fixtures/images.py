"""Synthetic image bytes for attachment tests.

Everything here is generated at test time; no image file is committed.
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Any
from uuid import UUID

from PIL import Image, PngImagePlugin

from insulation_coordination.domain.attachments import (
    ImageFormat,
    ProjectImageAttachment,
    media_type_of,
)


def png_bytes(
    width: int = 6, height: int = 4, *, text: str | None = None, alpha: int = 90
) -> bytes:
    """An RGBA PNG, optionally carrying a text chunk to trace metadata with."""
    image = Image.new("RGBA", (width, height), (200, 30, 30, alpha))
    info = None
    if text is not None:
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", text)
    stream = io.BytesIO()
    image.save(stream, "PNG", pnginfo=info)
    return stream.getvalue()


def jpeg_bytes(width: int = 8, height: int = 4, *, orientation: int | None = None) -> bytes:
    """A JPEG, optionally tagged with an EXIF orientation."""
    image = Image.new("RGB", (width, height), (0, 120, 255))
    exif = image.getexif()
    if orientation is not None:
        exif[0x0112] = orientation
    stream = io.BytesIO()
    image.save(stream, "JPEG", exif=exif, quality=95)
    return stream.getvalue()


def gif_bytes() -> bytes:
    """An animated GIF: a supported-looking image in an unsupported format."""
    frames = [Image.new("P", (4, 4), index) for index in (0, 1)]
    stream = io.BytesIO()
    frames[0].save(stream, "GIF", save_all=True, append_images=frames[1:])
    return stream.getvalue()


def animated_png_bytes() -> bytes:
    """A multi-frame APNG."""
    frames = [Image.new("RGBA", (4, 4), (index * 40, 0, 0, 255)) for index in (1, 2)]
    stream = io.BytesIO()
    frames[0].save(stream, "PNG", save_all=True, append_images=frames[1:])
    return stream.getvalue()


def attachment_from(
    data: bytes,
    image_format: ImageFormat = ImageFormat.PNG,
    **overrides: Any,
) -> ProjectImageAttachment:
    """Build an attachment that describes ``data`` truthfully, then override fields."""
    fields: dict[str, Any] = {
        "id": UUID(int=7),
        "original_filename": "diagram.png",
        "format": image_format,
        "media_type": media_type_of(image_format),
        "width_px": 6,
        "height_px": 4,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
    fields.update(overrides)
    return ProjectImageAttachment.model_validate(fields)
