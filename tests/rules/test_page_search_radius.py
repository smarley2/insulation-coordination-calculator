from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter

from insulation_coordination.rules.importer.extract import (
    ExtractionError,
    _extract_segment_in_window,
)
from insulation_coordination.rules.importer.identify import TableSegmentSpec
from tests.fixtures.synthetic_pdf import create_geometry_pdf

_SEGMENT = TableSegmentSpec(
    id="synthetic-segment",
    page_number=1,
    title_anchor="Table S1",
    expected_raw_rows=3,
    expected_raw_columns=3,
    expected_bbox=(72.0, 192.0, 252.0, 312.0),
    page_search_radius=2,
)


def _document(tmp_path: Path, blank_pages_before: int) -> Path:
    table_page = tmp_path / "table.pdf"
    create_geometry_pdf(
        table_page,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    writer = PdfWriter()
    for _ in range(blank_pages_before):
        writer.add_blank_page(width=612, height=792)
    writer.append(str(table_page))
    combined = tmp_path / f"combined-{blank_pages_before}.pdf"
    with combined.open("wb") as target:
        writer.write(target)
    return combined


def _resolve(path: Path, segment: TableSegmentSpec) -> int:
    with pdfplumber.open(path) as pdf:
        page_number, _ = _extract_segment_in_window(
            pdf,
            PdfReader(path),
            "synthetic-table",
            segment,
        )
    return page_number


def test_table_one_page_below_its_declared_position_is_located(tmp_path: Path) -> None:
    assert _resolve(_document(tmp_path, 1), _SEGMENT.model_copy(update={"page_number": 1})) == 2


def test_table_absent_from_the_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="found on 0 pages"):
        _resolve(_document(tmp_path, 5), _SEGMENT.model_copy(update={"page_number": 1}))


def test_radius_zero_keeps_the_existing_exact_page_behaviour(tmp_path: Path) -> None:
    exact = _SEGMENT.model_copy(update={"page_number": 1, "page_search_radius": 0})
    with pytest.raises(ExtractionError):
        _resolve(_document(tmp_path, 1), exact)
