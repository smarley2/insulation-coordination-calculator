"""Source-only curve figure extraction. Synthetic data only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
from insulation_coordination.rules.importer.curves import extract_raw_figure
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
    return PdfReader(path), pdfplumber.open(path)


def test_vector_paths_win_even_when_an_image_exists(curve_pdf: Path) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), IDENTITY
        )
    assert figure.source_mode == "vector_path"
    assert figure.pixel_size is not None


def test_raster_only_page_falls_back_to_lossless_xobject(curve_pdf: Path) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[1],
            pdf.pages[1],
            synthetic_curve_spec().model_copy(update={"page_number": 2}),
            IDENTITY,
        )
    assert figure.source_mode == "image_xobject"
    assert figure.pixel_size is not None
    assert all(value > 0 for value in figure.pixel_size)


def test_source_artifact_hash_is_deterministic(curve_pdf: Path) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        first = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), IDENTITY
        )
        second = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), IDENTITY
        )
    assert first.artifact_sha256 == second.artifact_sha256
    assert len(first.artifact_sha256) == 64


def test_crop_bbox_and_vector_transform_are_retained(curve_pdf: Path) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        figure = extract_raw_figure(
            reader.pages[0], pdf.pages[0], synthetic_curve_spec(), IDENTITY
        )
    assert figure.source_bbox == tuple(Decimal(str(value)) for value in BBOX)
    assert len(figure.transform) == 6
    assert figure.transform[0] > 0
    assert figure.transform[3] < 0


def test_ambiguous_images_block_extraction(
    curve_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        page = reader.pages[1]
        images = list(page.images)
        monkeypatch.setattr(type(page), "images", property(lambda _self: images * 2))
        with pytest.raises(ExtractionError, match="CURVE_SOURCE_AMBIGUOUS"):
            extract_raw_figure(
                page,
                pdf.pages[1],
                synthetic_curve_spec().model_copy(update={"page_number": 2}),
                IDENTITY,
            )


def test_missing_source_in_declared_bbox_blocks_extraction(curve_pdf: Path) -> None:
    reader, pdf = _pages(curve_pdf)
    with pdf:
        spec = synthetic_curve_spec().model_copy(
            update={"expected_bbox": (450.0, 700.0, 520.0, 780.0)}
        )
        with pytest.raises(ExtractionError, match="CURVE_SOURCE"):
            extract_raw_figure(reader.pages[0], pdf.pages[0], spec, IDENTITY)


def test_lossy_image_blocks_before_decode(
    curve_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pypdf.generic import NameObject

    reader, pdf = _pages(curve_pdf)
    with pdf:
        page = reader.pages[1]
        xobject = page["/Resources"]["/XObject"]["/Im1"].get_object()
        xobject.update({NameObject("/Filter"): NameObject("/DCTDecode")})
        with pytest.raises(ExtractionError, match="CURVE_SOURCE_LOSSY"):
            extract_raw_figure(
                page,
                pdf.pages[1],
                synthetic_curve_spec().model_copy(update={"page_number": 2}),
                IDENTITY,
            )


def test_vector_clipping_path_blocks_extraction(curve_pdf: Path) -> None:
    from pypdf.generic import DecodedStreamObject, NameObject

    clipped = curve_pdf.parent / "clipped.pdf"
    writer = PdfWriter()
    writer.append(curve_pdf)
    page = writer.pages[0]
    contents = page.get_contents()
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 612 792 re W n\n" + contents.get_data())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with clipped.open("wb") as target:
        writer.write(target)
    reader, pdf = _pages(clipped)
    with pdf, pytest.raises(ExtractionError, match="CURVE_SOURCE_CLIPPED"):
        extract_raw_figure(reader.pages[0], pdf.pages[0], synthetic_curve_spec(), IDENTITY)


def test_image_sized_clip_and_placement_transform_are_retained(curve_pdf: Path) -> None:
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
            IDENTITY,
        )
    assert figure.source_mode == "image_xobject"
    assert figure.transform == (
        Decimal(40),
        Decimal(0),
        Decimal(0),
        Decimal(40),
        Decimal(100),
        Decimal(350),
    )
