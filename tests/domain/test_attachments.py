from __future__ import annotations

import base64
import hashlib

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.attachments import (
    MAX_DIAGRAM_BYTES,
    MAX_DIAGRAM_DIMENSION,
    ImageFormat,
    detect_format,
    media_type_of,
)
from tests.fixtures.images import attachment_from, gif_bytes, jpeg_bytes, png_bytes


def test_valid_attachment_returns_the_stored_bytes() -> None:
    data = png_bytes()

    attachment = attachment_from(data)

    assert attachment.decoded_bytes() == data
    assert attachment.role == "circuit_diagram"
    assert attachment.format is ImageFormat.PNG
    assert attachment.caption == ""


def test_jpeg_attachment_declares_its_own_media_type() -> None:
    attachment = attachment_from(
        jpeg_bytes(), ImageFormat.JPEG, original_filename="diagram.jpg", width_px=8
    )

    assert attachment.media_type == "image/jpeg"
    assert attachment.staged_filename.endswith(".jpg")


def test_detect_format_reads_the_bytes_not_the_extension() -> None:
    assert detect_format(png_bytes()) is ImageFormat.PNG
    assert detect_format(jpeg_bytes()) is ImageFormat.JPEG
    assert detect_format(gif_bytes()) is None
    assert detect_format(b"") is None


def test_checksum_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SHA-256"):
        attachment_from(png_bytes(), sha256="0" * 64)


def test_byte_size_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="byte size"):
        attachment_from(png_bytes(), byte_size=3)


def test_malformed_base64_is_rejected() -> None:
    with pytest.raises(ValidationError, match="base64"):
        attachment_from(png_bytes(), data_base64="not base64 £")


def test_media_type_must_match_the_format() -> None:
    with pytest.raises(ValidationError, match="Media type"):
        attachment_from(png_bytes(), media_type="image/jpeg")


def test_declared_format_must_match_the_bytes() -> None:
    data = jpeg_bytes()

    with pytest.raises(ValidationError, match="not a png image"):
        attachment_from(
            data,
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            data_base64=base64.b64encode(data).decode("ascii"),
        )


def test_unsupported_image_bytes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not a png image"):
        attachment_from(gif_bytes())


@pytest.mark.parametrize("field", ["width_px", "height_px"])
@pytest.mark.parametrize("value", [0, -1, MAX_DIAGRAM_DIMENSION + 1])
def test_dimensions_must_be_positive_and_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        attachment_from(png_bytes(), **{field: value})


def test_pixel_count_is_bounded() -> None:
    with pytest.raises(ValidationError, match="pixels"):
        attachment_from(png_bytes(), width_px=16_000, height_px=16_000)


def test_byte_size_is_bounded() -> None:
    with pytest.raises(ValidationError):
        attachment_from(png_bytes(), byte_size=MAX_DIAGRAM_BYTES + 1)


def test_oversized_payload_is_rejected_before_the_size_claim_is_believed() -> None:
    oversized = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * MAX_DIAGRAM_BYTES).decode("ascii")

    with pytest.raises(ValidationError, match="bytes"):
        attachment_from(png_bytes(), data_base64=oversized)


@pytest.mark.parametrize(
    "filename", ["../evil.png", "sub/dir.png", r"sub\dir.png", "C:evil.png", ".", ".."]
)
def test_filenames_that_are_paths_are_rejected(filename: str) -> None:
    with pytest.raises(ValidationError, match="plain file name"):
        attachment_from(png_bytes(), original_filename=filename)


def test_only_the_circuit_diagram_role_exists() -> None:
    with pytest.raises(ValidationError):
        attachment_from(png_bytes(), role="schematic")


def test_attachment_is_frozen_and_rejects_unknown_fields() -> None:
    attachment = attachment_from(png_bytes())

    with pytest.raises(ValidationError):
        attachment.caption = "new"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        attachment_from(png_bytes(), unexpected="x")


def test_staged_filename_is_derived_from_the_content_hash() -> None:
    attachment = attachment_from(png_bytes())

    assert attachment.staged_filename == f"circuit-diagram-{attachment.sha256[:12]}.png"
    assert media_type_of(attachment.format) == "image/png"
