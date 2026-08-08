"""Vector-first curve source extraction with XObject fallback. Synthetic only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
from insulation_coordination.rules.importer.curves import (
    OcrEngineIdentity,
    OcrToken,
    PixelBox,
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
    assert all(point.space == "pdf" for trace in figure.traces for point in trace.points)


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
