"""The one image a project may carry, validated as bytes rather than as a path.

A project is copied between computers, so an attachment is only trustworthy if
the project file itself holds the pixels. Every field here describes the bytes
in ``data_base64``; the validator rejects any document where the two disagree.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The image is embedded in the project file, so these limits bound the size of
#: every saved project as well as the cost of decoding one.
MAX_DIAGRAM_BYTES = 10 * 1024 * 1024
MAX_DIAGRAM_PIXELS = 40_000_000
MAX_DIAGRAM_DIMENSION = 16_384

#: The only attachment role a project supports; one image, at project level.
CIRCUIT_DIAGRAM_ROLE: Literal["circuit_diagram"] = "circuit_diagram"

_UNSAFE_FILENAME = re.compile(r"[/\\:]")


class ImageFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"


_SIGNATURES = {
    ImageFormat.PNG: b"\x89PNG\r\n\x1a\n",
    ImageFormat.JPEG: b"\xff\xd8\xff",
}
_MEDIA_TYPES = {ImageFormat.PNG: "image/png", ImageFormat.JPEG: "image/jpeg"}
_SUFFIXES = {ImageFormat.PNG: "png", ImageFormat.JPEG: "jpg"}


def detect_format(data: bytes) -> ImageFormat | None:
    """Read the format out of the bytes; a file extension proves nothing."""
    for image_format, signature in _SIGNATURES.items():
        if data.startswith(signature):
            return image_format
    return None


def media_type_of(image_format: ImageFormat) -> str:
    return _MEDIA_TYPES[image_format]


def suffix_of(image_format: ImageFormat) -> str:
    return _SUFFIXES[image_format]


class ProjectImageAttachment(BaseModel):
    """Normalized image bytes plus the metadata that describes them."""

    # Deliberately not domain.project.FrozenModel: Project imports this module,
    # and importing FrozenModel back would close the cycle.
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    role: Literal["circuit_diagram"] = CIRCUIT_DIAGRAM_ROLE
    original_filename: str = Field(min_length=1)
    format: ImageFormat
    media_type: str
    width_px: int = Field(gt=0, le=MAX_DIAGRAM_DIMENSION)
    height_px: int = Field(gt=0, le=MAX_DIAGRAM_DIMENSION)
    byte_size: int = Field(gt=0, le=MAX_DIAGRAM_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_base64: str = Field(min_length=1)
    caption: str = ""
    source_note: str = ""

    @model_validator(mode="after")
    def _requires_bytes_matching_the_metadata(self) -> Self:
        if self.width_px * self.height_px > MAX_DIAGRAM_PIXELS:
            raise ValueError(f"An image may not exceed {MAX_DIAGRAM_PIXELS} pixels")
        if self.media_type != media_type_of(self.format):
            raise ValueError(f"Media type {self.media_type} does not match format {self.format}")
        if _UNSAFE_FILENAME.search(self.original_filename) or self.original_filename.strip() in {
            "",
            ".",
            "..",
        }:
            raise ValueError("An attachment filename must be a plain file name")
        # Bound the encoded text before decoding it: byte_size is only a claim
        # until the payload has been read.
        if len(self.data_base64) > (MAX_DIAGRAM_BYTES // 3 + 1) * 4:
            raise ValueError(f"An image may not exceed {MAX_DIAGRAM_BYTES} bytes")
        data = self.decoded_bytes()
        if len(data) != self.byte_size:
            raise ValueError("Attachment byte size does not match the stored data")
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("Attachment SHA-256 does not match the stored data")
        if detect_format(data) is not self.format:
            raise ValueError(f"Attachment data is not a {self.format} image")
        return self

    def decoded_bytes(self) -> bytes:
        """The stored image bytes, or a ValueError when the payload is malformed."""
        try:
            return base64.b64decode(self.data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError(f"Attachment data is not valid base64: {error}") from error

    @property
    def staged_filename(self) -> str:
        """A deterministic, path-free name derived from the content hash."""
        return f"circuit-diagram-{self.sha256[:12]}.{suffix_of(self.format)}"
