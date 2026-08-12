"""Load, normalize, and stage the one image a project can carry.

Import normalizes once: orientation is baked into the pixels, metadata is
dropped, and the result is re-encoded as plain PNG or JPEG. Saving, loading,
and reporting then move those bytes unchanged, so the checksum recorded at
import stays valid for the life of the project.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from insulation_coordination.domain.attachments import (
    MAX_DIAGRAM_BYTES,
    MAX_DIAGRAM_DIMENSION,
    MAX_DIAGRAM_PIXELS,
    ImageFormat,
    ProjectImageAttachment,
    detect_format,
    media_type_of,
)

#: Re-encoding quality for JPEG imports. Import is the only re-encode, so this
#: is paid once rather than on every save.
_JPEG_QUALITY = 92


class ImageAttachmentError(ValueError):
    """An image cannot be attached to a project or staged for a report."""


def load_project_image(
    path: Path, *, caption: str = "", source_note: str = ""
) -> ProjectImageAttachment:
    """Read one PNG or JPEG file and return normalized, portable bytes."""
    path = Path(path)
    data = _read_bounded(path)
    image_format = detect_format(data)
    if image_format is None:
        raise ImageAttachmentError("Only PNG and JPEG images are supported")
    if image_format is ImageFormat.PNG and _is_animated_png(data):
        raise ImageAttachmentError("Animated images are not supported")
    normalized, width, height = _normalize(data, image_format)
    try:
        return ProjectImageAttachment(
            id=uuid4(),
            original_filename=path.name,
            format=image_format,
            media_type=media_type_of(image_format),
            width_px=width,
            height_px=height,
            byte_size=len(normalized),
            sha256=hashlib.sha256(normalized).hexdigest(),
            data_base64=base64.b64encode(normalized).decode("ascii"),
            caption=caption,
            source_note=source_note,
        )
    except ValidationError as error:
        raise ImageAttachmentError(f"The image cannot be attached: {error}") from error


def stage_report_image(attachment: ProjectImageAttachment, directory: Path) -> Path:
    """Write the stored bytes into ``directory`` under their deterministic name."""
    directory = Path(directory)
    target = directory / attachment.staged_filename
    try:
        directory.mkdir(parents=True, exist_ok=True)
        data = attachment.decoded_bytes()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    except (OSError, ValueError) as error:
        raise ImageAttachmentError(f"Could not stage the circuit diagram: {error}") from error
    return target


def _read_bounded(path: Path) -> bytes:
    """Read at most one image's worth of bytes, so a huge file cannot be decoded."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_DIAGRAM_BYTES + 1)
    except OSError as error:
        raise ImageAttachmentError(f"Could not read the image: {error}") from error
    if not data:
        raise ImageAttachmentError("The image file is empty")
    if len(data) > MAX_DIAGRAM_BYTES:
        raise ImageAttachmentError(f"The image is larger than the {MAX_DIAGRAM_BYTES} byte limit")
    return data


def _is_animated_png(data: bytes) -> bool:
    """True for an APNG: its control chunk precedes the first image chunk."""
    first_image = data.find(b"IDAT")
    header = data if first_image < 0 else data[:first_image]
    return b"acTL" in header


def _check_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ImageAttachmentError("The image is corrupt or has no pixels")
    if width > MAX_DIAGRAM_DIMENSION or height > MAX_DIAGRAM_DIMENSION:
        raise ImageAttachmentError(
            f"The image is too large: no side may exceed {MAX_DIAGRAM_DIMENSION} pixels"
        )
    if width * height > MAX_DIAGRAM_PIXELS:
        raise ImageAttachmentError(
            f"The image is too large: it may not exceed {MAX_DIAGRAM_PIXELS} pixels"
        )


def _normalize(data: bytes, image_format: ImageFormat) -> tuple[bytes, int, int]:
    """Decode with Qt and re-encode clean pixels of the same format."""
    # Qt is imported here so that loading a project, rendering a report, or
    # running the CLI never pulls in the GUI stack for its own sake.
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QImage, QImageReader

    # QBuffer borrows the byte array, so it has to outlive the reader.
    payload = QByteArray(data)
    source = QBuffer(payload)
    source.open(QBuffer.OpenModeFlag.ReadOnly)
    # The format comes from the signature, never from the file name, so a
    # renamed file cannot steer Qt into a different decoder.
    reader = QImageReader(source, QByteArray(image_format.value.encode("ascii")))
    reader.setAutoTransform(True)
    if not reader.canRead():
        raise ImageAttachmentError("The image is corrupt or not a supported image")
    if reader.imageCount() > 1:
        raise ImageAttachmentError("Animated images are not supported")
    header = reader.size()
    _check_dimensions(header.width(), header.height())
    image = reader.read()
    if image.isNull():
        raise ImageAttachmentError(f"The image could not be decoded: {reader.errorString()}")
    _check_dimensions(image.width(), image.height())

    target = (
        QImage.Format.Format_RGBA8888
        if image_format is ImageFormat.PNG
        else QImage.Format.Format_RGB888
    )
    converted = image.convertToFormat(target)
    # A fresh image over the same pixels: Qt copies text chunks along with an
    # image, and only a rebuild from raw bits leaves them behind.
    clean = QImage(
        converted.constBits(),
        converted.width(),
        converted.height(),
        converted.bytesPerLine(),
        target,
    ).copy()
    output = QBuffer()
    output.open(QBuffer.OpenModeFlag.WriteOnly)
    # The PySide6 stub types ``format`` as bytes, but only str is accepted at
    # run time; bytes raises "called with wrong argument values".
    written = clean.save(
        output,
        "PNG" if image_format is ImageFormat.PNG else "JPEG",  # type: ignore[call-overload]
        -1 if image_format is ImageFormat.PNG else _JPEG_QUALITY,
    )
    normalized = bytes(output.data().data())
    output.close()
    if not written or not normalized:
        raise ImageAttachmentError("The image could not be normalized")
    return normalized, clean.width(), clean.height()
