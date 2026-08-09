"""Vector-first curve source extraction with XObject fallback. Synthetic only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
from insulation_coordination.rules.importer.curves import (
    OcrEngineIdentity,
    OcrToken,
    PixelBox,
    _raster_traces,
    extract_raw_figure,
)
from insulation_coordination.rules.importer.extract import ExtractionError
from insulation_coordination.rules.importer.identify import CurveAuditSpec, StandardIdentity
from tests.fixtures.synthetic_pdf import create_curve_source_pdf

IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="7" * 64,
    page_count=2,
    recipe_id="synthetic-curve",
)
BBOX = (70.0, 200.0, 400.0, 500.0)


class FakeOcrEngine:
    identity = OcrEngineIdentity(name="fake", version="1", config_sha256="0" * 64)

    def recognize(self, image) -> tuple[OcrToken, ...]:
        return (
            OcrToken(
                text="ms",
                confidence=Decimal("0.95"),
                box=PixelBox(left=1, top=2, right=3, bottom=4),
            ),
        )


def synthetic_curve_spec() -> CurveAuditSpec:
    return CurveAuditSpec(
        semantic_id="synthetic.curve.example",
        figure="SF-1",
        page_number=1,
        expected_bbox=BBOX,
        expected_pixel_size=None,
        x_quantity_kind="duration",
        x_unit="s",
        y_quantity_kind="voltage",
        y_unit="V",
        x_scale="log10",
        y_scale="log10",
        variant_slots=(
            FaultTimeVoltageSelector(
                subject="accessible_circuit",
                voltage_basis="ac_rms",
                dvc_context=None,
                environment_context=None,
            ),
        ),
        permitted_segment_types=("continuous",),
        permitted_interpolations=("log_log",),
    )


@pytest.fixture
def curve_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "curves.pdf"
    create_curve_source_pdf(path)
    return path


def _pages(path: Path):
    reader = PdfReader(path)
    pdf = pdfplumber.open(path)
    return reader, pdf


def test_vector_paths_win_even_when_an_image_exists(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
    assert figure.source_mode == "vector_path"
    assert figure.traces
    assert all(trace.points for trace in figure.traces)
    assert all(point.space == "pixel" for trace in figure.traces for point in trace.points)
    assert figure.pixel_size is not None
    assert figure.ocr_tokens


def test_raster_only_page_falls_back_to_xobject(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[1], pdf.pages[1],
            synthetic_curve_spec().model_copy(update={"page_number": 2}),
            FakeOcrEngine(),
            IDENTITY,
        )
    assert figure.source_mode == "image_xobject"
    assert figure.pixel_size is not None
    assert figure.pixel_size[0] > 0 and figure.pixel_size[1] > 0
    assert figure.traces == ()


def test_extraction_is_deterministic(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        first = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
        second = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
    assert first.artifact_sha256 == second.artifact_sha256
    assert len(first.artifact_sha256) == 64


def test_crop_bbox_and_transform_are_retained(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
    assert figure.source_bbox == tuple(Decimal(str(v)) for v in BBOX)
    assert len(figure.transform) == 6


def test_vector_geometry_is_mapped_into_rendered_crop_pixels(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
    assert figure.pixel_size is not None
    width, height = figure.pixel_size
    for trace in figure.traces:
        for point in trace.points:
            assert Decimal(0) <= point.x <= Decimal(width)
            assert Decimal(0) <= point.y <= Decimal(height)


def test_raster_figure_carries_ocr_tokens(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[1], pdf.pages[1],
            synthetic_curve_spec().model_copy(update={"page_number": 2}),
            FakeOcrEngine(),
            IDENTITY,
        )
    assert figure.ocr_tokens
    assert figure.ocr_tokens[0].text == "ms"


def test_lossless_raster_curve_recovers_one_pixel_trace() -> None:
    image = Image.new("L", (200, 160), color=255)
    draw = ImageDraw.Draw(image)
    for x in range(20, 181):
        y = 20 + (x - 20) // 2
        draw.line((x, y, x, y + 1), fill=0, width=1)
    draw.line((10, 140, 190, 140), fill=0, width=1)
    draw.line((10, 10, 10, 150), fill=0, width=1)

    traces = _raster_traces(image, ())

    assert len(traces) == 1
    assert traces[0].points[0].space == "pixel"
    assert traces[0].points[0].x == Decimal(20)
    assert traces[0].points[-1].x == Decimal(180)


def test_colored_solid_and_dashed_curves_are_recovered_in_voltage_order() -> None:
    image = Image.new("RGB", (240, 180), color="white")
    draw = ImageDraw.Draw(image)
    for x in range(20, 221, 20):
        draw.line((x, 10, x, 155), fill=(40, 40, 40), width=1)
    for y in range(15, 156, 20):
        draw.line((20, y, 220, y), fill=(40, 40, 40), width=1)
    draw.line((20, 45, 220, 45), fill=(205, 75, 70), width=4)
    for start in range(20, 221, 18):
        draw.line((start, 80, min(start + 10, 220), 80), fill=(75, 135, 195), width=4)
        draw.line((start, 115, min(start + 10, 220), 115), fill=(25, 80, 140), width=4)

    traces = _raster_traces(image, (), 3)

    assert len(traces) == 3
    endpoint_heights = [trace.points[-1].y for trace in traces]
    assert endpoint_heights == sorted(endpoint_heights)


def test_colored_trace_recovery_does_not_hide_an_extra_candidate() -> None:
    image = Image.new("RGB", (240, 180), color="white")
    draw = ImageDraw.Draw(image)
    for y, color in zip(
        (35, 65, 95),
        ((205, 75, 70), (75, 135, 195), (25, 80, 140)),
        strict=True,
    ):
        draw.line((20, y, 220, y), fill=color, width=4)
    draw.line((40, 125, 200, 125), fill=(60, 180, 70), width=2)

    traces = _raster_traces(image, (), 3)

    assert len(traces) == 4


def test_colored_trace_recovery_merges_antialias_shades_of_one_stroke() -> None:
    image = Image.new("RGB", (240, 180), color="white")
    draw = ImageDraw.Draw(image)
    draw.line((20, 79, 220, 79), fill=(225, 155, 150), width=1)
    draw.line((20, 80, 220, 80), fill=(205, 75, 70), width=2)
    draw.line((20, 82, 220, 82), fill=(235, 185, 180), width=1)

    traces = _raster_traces(image, (), 1)

    assert len(traces) == 1


def test_colored_trace_recovery_keeps_spatially_separate_same_hue_strokes() -> None:
    image = Image.new("RGB", (240, 180), color="white")
    draw = ImageDraw.Draw(image)
    draw.line((20, 45, 220, 45), fill=(205, 75, 70), width=3)
    draw.line((20, 115, 220, 115), fill=(235, 185, 180), width=3)

    traces = _raster_traces(image, (), 1)

    assert len(traces) == 2


def test_ambiguous_images_block_extraction(curve_pdf, monkeypatch) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        page = reader.pages[1]
        plumber_page = pdf.pages[1]
        original_images = type(page).images

        class _Doubled:
            def __iter__(self):
                images = list(original_images.fget(page))
                return iter([images[0], images[0]])

        monkeypatch.setattr(type(page), "images", property(lambda self: list(_Doubled())))
        with pytest.raises(ExtractionError, match="CURVE_SOURCE_AMBIGUOUS"):
            extract_raw_figure(
                page,
                plumber_page,
                synthetic_curve_spec().model_copy(update={"page_number": 2}),
                FakeOcrEngine(),
                IDENTITY,
            )


def test_wrong_bbox_blocks_extraction(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        spec = synthetic_curve_spec().model_copy(
            update={"expected_bbox": (450.0, 700.0, 520.0, 780.0)}
        )
        with pytest.raises(ExtractionError, match="CURVE_SOURCE"):
            extract_raw_figure(
                reader.pages[0], pdf.pages[0], spec, FakeOcrEngine(), IDENTITY
            )


def test_raw_points_carry_source_geometry_unlike_curve_points(curve_pdf) -> None:
    from insulation_coordination.domain.rules import CurvePoint

    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), FakeOcrEngine(), IDENTITY
        )
    raw = figure.traces[0].points[0]
    assert raw.primitive_ref
    semantic_fields = set(CurvePoint.model_fields)
    assert semantic_fields == {"x", "y"}


def test_lossy_image_filter_blocks_extraction(curve_pdf, monkeypatch) -> None:
    """A DCTDecode (lossy) figure image blocks before decode."""
    from pypdf.generic import NameObject

    reader, pdf = _pages(curve_pdf)
    with pdf:
        page = reader.pages[1]
        xobj = page["/Resources"]["/XObject"]["/Im1"].get_object()
        xobj.update({NameObject("/Filter"): NameObject("/DCTDecode")})
        with pytest.raises(ExtractionError, match="CURVE_SOURCE_LOSSY"):
            extract_raw_figure(
                page,
                pdf.pages[1],
                synthetic_curve_spec().model_copy(update={"page_number": 2}),
                FakeOcrEngine(),
                IDENTITY,
            )


def test_clipping_path_blocks_extraction(curve_pdf) -> None:
    """A clipping path makes in-bbox membership uncertain; extraction blocks."""
    from pypdf import PdfWriter

    _reader, pdf = _pages(curve_pdf)
    clipped = curve_pdf.parent / "clipped.pdf"
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter()
    writer.append(curve_pdf)
    page = writer.pages[0]
    contents = page.get_contents()
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 612 792 re W n\n" + contents.get_data())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with clipped.open("wb") as target:
        writer.write(target)
    reader2, pdf2 = _pages(clipped)
    with pdf, pdf2, pytest.raises(ExtractionError, match="CURVE_SOURCE_CLIPPED"):
        extract_raw_figure(
            reader2.pages[0],
            pdf2.pages[0],
            synthetic_curve_spec(),
            FakeOcrEngine(),
            IDENTITY,
        )


def test_rectangular_clip_that_exactly_contains_lossless_image_is_allowed(curve_pdf) -> None:
    """A reviewed image-sized clip does not alter the lossless source geometry."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    clipped = curve_pdf.parent / "clipped-image.pdf"
    writer = PdfWriter()
    writer.append(curve_pdf)
    page = writer.pages[1]
    contents = page.get_contents()
    stream = DecodedStreamObject()
    stream.set_data(b"100 350 40 40 re W n\n" + contents.get_data())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with clipped.open("wb") as target:
        writer.write(target)

    reader, pdf = _pages(clipped)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[1],
            pdf.pages[1],
            synthetic_curve_spec().model_copy(update={"page_number": 2}),
            FakeOcrEngine(),
            IDENTITY,
        )
    assert figure.source_mode == "image_xobject"
    assert figure.transform == (
        Decimal(40), Decimal(0), Decimal(0), Decimal(40), Decimal(100), Decimal(350),
    )


def test_image_branch_retains_placement_transform(curve_pdf) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[1],
            pdf.pages[1],
            synthetic_curve_spec().model_copy(update={"page_number": 2}),
            FakeOcrEngine(),
            IDENTITY,
        )
    assert figure.transform == (
        Decimal(40), Decimal(0), Decimal(0), Decimal(40), Decimal(100), Decimal(350),
    )
