from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from insulation_coordination.domain.attachments import ImageFormat
from insulation_coordination.project import image_attachments
from insulation_coordination.project.image_attachments import (
    ImageAttachmentError,
    load_project_image,
    stage_report_image,
)
from tests.fixtures.images import animated_png_bytes, gif_bytes, jpeg_bytes, png_bytes


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_png_is_accepted_and_described_by_its_own_bytes(tmp_path: Path) -> None:
    path = write(tmp_path, "diagram.png", png_bytes(6, 4))

    attachment = load_project_image(path)

    assert attachment.format is ImageFormat.PNG
    assert (attachment.width_px, attachment.height_px) == (6, 4)
    assert attachment.original_filename == "diagram.png"
    assert attachment.byte_size == len(attachment.decoded_bytes())
    assert attachment.decoded_bytes().startswith(b"\x89PNG")


def test_jpeg_is_accepted_with_caption_and_note(tmp_path: Path) -> None:
    path = write(tmp_path, "topology.jpg", jpeg_bytes(8, 4))

    attachment = load_project_image(path, caption="Topology", source_note="Drawn in EDA")

    assert attachment.format is ImageFormat.JPEG
    assert attachment.media_type == "image/jpeg"
    assert (attachment.caption, attachment.source_note) == ("Topology", "Drawn in EDA")
    assert attachment.decoded_bytes().startswith(b"\xff\xd8\xff")


def test_png_transparency_survives_normalization(tmp_path: Path) -> None:
    path = write(tmp_path, "diagram.png", png_bytes(6, 4, alpha=90))

    attachment = load_project_image(path)

    with Image.open(io.BytesIO(attachment.decoded_bytes())) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 90


def test_normalization_drops_image_metadata(tmp_path: Path) -> None:
    path = write(tmp_path, "diagram.png", png_bytes(text="confidential-metadata"))

    attachment = load_project_image(path)

    assert b"confidential-metadata" not in attachment.decoded_bytes()
    assert b"Comment" not in attachment.decoded_bytes()


def test_exif_orientation_is_baked_into_the_stored_pixels(tmp_path: Path) -> None:
    path = write(tmp_path, "rotated.jpg", jpeg_bytes(8, 4, orientation=6))

    attachment = load_project_image(path)

    assert (attachment.width_px, attachment.height_px) == (4, 8)
    with Image.open(io.BytesIO(attachment.decoded_bytes())) as image:
        assert image.size == (4, 8)
        assert 0x0112 not in image.getexif()


def test_content_decides_the_format_not_the_extension(tmp_path: Path) -> None:
    path = write(tmp_path, "diagram.jpg", png_bytes())

    attachment = load_project_image(path)

    assert attachment.format is ImageFormat.PNG
    assert attachment.original_filename == "diagram.jpg"


def test_unsupported_format_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "animation.png", gif_bytes())

    with pytest.raises(ImageAttachmentError, match="PNG and JPEG"):
        load_project_image(path)


def test_animated_png_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "animated.png", animated_png_bytes())

    with pytest.raises(ImageAttachmentError, match="[Aa]nimated"):
        load_project_image(path)


def test_truncated_image_is_rejected(tmp_path: Path) -> None:
    data = png_bytes(40, 40)
    path = write(tmp_path, "cut.png", data[: len(data) // 2])

    with pytest.raises(ImageAttachmentError, match="corrupt|decoded"):
        load_project_image(path)


def test_corrupt_payload_is_rejected(tmp_path: Path) -> None:
    data = bytearray(png_bytes(40, 40))
    data[40:200] = b"\x00" * 160
    path = write(tmp_path, "corrupt.png", bytes(data))

    with pytest.raises(ImageAttachmentError):
        load_project_image(path)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "empty.png", b"")

    with pytest.raises(ImageAttachmentError, match="empty"):
        load_project_image(path)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ImageAttachmentError, match="Could not read"):
        load_project_image(tmp_path / "absent.png")


def test_oversized_file_is_rejected_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_attachments, "MAX_DIAGRAM_BYTES", 32)
    path = write(tmp_path, "big.png", png_bytes(40, 40))

    with pytest.raises(ImageAttachmentError, match="larger than"):
        load_project_image(path)


def test_oversized_dimensions_are_rejected_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_attachments, "MAX_DIAGRAM_DIMENSION", 4)
    path = write(tmp_path, "wide.png", png_bytes(6, 4))

    with pytest.raises(ImageAttachmentError, match="too large"):
        load_project_image(path)


def test_oversized_pixel_count_is_rejected_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_attachments, "MAX_DIAGRAM_PIXELS", 8)
    path = write(tmp_path, "many.png", png_bytes(6, 4))

    with pytest.raises(ImageAttachmentError, match="too large"):
        load_project_image(path)


def test_staging_writes_a_deterministic_name_and_leaves_no_temporary(tmp_path: Path) -> None:
    attachment = load_project_image(write(tmp_path, "diagram.png", png_bytes()))
    build = tmp_path / "build"

    first = stage_report_image(attachment, build)
    second = stage_report_image(attachment, build)

    assert first == second == build / f"circuit-diagram-{attachment.sha256[:12]}.png"
    assert first.read_bytes() == attachment.decoded_bytes()
    assert sorted(item.name for item in build.iterdir()) == [first.name]


def test_staging_a_jpeg_uses_the_jpg_suffix(tmp_path: Path) -> None:
    attachment = load_project_image(write(tmp_path, "diagram.jpg", jpeg_bytes()))

    staged = stage_report_image(attachment, tmp_path / "build")

    assert staged.name.endswith(".jpg")
    assert staged.read_bytes().startswith(b"\xff\xd8\xff")


def test_staging_reports_a_specific_error_when_the_directory_cannot_be_used(
    tmp_path: Path,
) -> None:
    attachment = load_project_image(write(tmp_path, "diagram.png", png_bytes()))
    blocked = write(tmp_path, "blocked", b"not a directory")

    with pytest.raises(ImageAttachmentError, match="Could not stage"):
        stage_report_image(attachment, blocked)
