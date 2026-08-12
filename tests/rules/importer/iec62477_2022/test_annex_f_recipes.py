"""Annex F grid recipes: declared structure and blank handling.

Synthetic values only. The peak voltages, the clearances and creepage distances, and the
frequency band boundaries all belong to the licensed source, so the fixtures here invent
their own.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.extract import (
    ExtractionError,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    apply_table_structure,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.annex_f import (
    ANNEX_F_TABLES,
    TABLE_F1,
    TABLE_F2,
    TABLE_F3,
)

SOURCE = SourceReference(
    document_id="synthetic-annex-f",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="SF1",
)
F1_DECLARED_BLANKS = frozenset((item.row, item.column) for item in TABLE_F1.blank_cells)


def _f1_cell(row: int, column: int, *, blank_at: tuple[int, int] | None) -> RawGridCell:
    """One synthetic Table F.1 cell: header row, eight data rows, then a note row."""

    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if (row, column) == blank_at or (row, column) in F1_DECLARED_BLANKS:
        text, role, value = "", "blank", None
    elif row in TABLE_F1.segments[0].header_rows:
        text, role, value = f"neutral title {column + 1}", "header", None
    elif row in TABLE_F1.segments[0].note_rows:
        text, role, value = "synthetic note", "note", None
    else:
        text, role, value = f"{column + 1}{row},0", "data", Decimal(f"{column + 1}{row}.0")
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text,
        role=role,  # type: ignore[arg-type]
        logical_row=row - 1 if role == "data" else None,
        logical_column=TABLE_F1.columns[column].semantic_id if role == "data" else None,
        value=value,
        parse_status="numeric" if value is not None else ("blank" if not text else "text"),
        source=source,
    )


def _f1_grid(*, blank_at: tuple[int, int] | None = None) -> RawGrid:
    return RawGrid(
        id=f"raw-{TABLE_F1.semantic_id}",
        rows=TABLE_F1.expected_raw_rows,
        columns=TABLE_F1.expected_raw_columns,
        target_unit=TABLE_F1.target_unit,
        segments=(
            RawGridSegment(
                page_number=TABLE_F1.page_number,
                row_start=0,
                row_count=TABLE_F1.expected_raw_rows,
                source=SOURCE,
            ),
        ),
        cells=tuple(
            _f1_cell(row, column, blank_at=blank_at)
            for row in range(TABLE_F1.expected_raw_rows)
            for column in range(TABLE_F1.expected_raw_columns)
        ),
        source=SOURCE,
    )


def test_the_three_specs_declare_the_measured_shapes() -> None:
    assert tuple(spec.semantic_id for spec in ANNEX_F_TABLES) == (
        f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f1",
        f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f2",
        f"{ids.HIGH_FREQUENCY_APPLICABILITY}.annex_f3",
    )
    shapes = {
        spec.semantic_id: (
            spec.page_number,
            spec.expected_raw_rows,
            spec.expected_raw_columns,
            spec.expected_data_rows,
            spec.expected_data_columns,
        )
        for spec in ANNEX_F_TABLES
    }
    assert shapes == {
        TABLE_F1.semantic_id: (197, 10, 2, 8, 2),
        TABLE_F2.semantic_id: (197, 5, 2, 4, 2),
        TABLE_F3.semantic_id: (199, 21, 8, 18, 8),
    }


def test_every_segment_repeats_its_spec_shape_and_covers_its_rows_once() -> None:
    for spec in ANNEX_F_TABLES:
        segment = spec.segments[0]
        assert (segment.expected_raw_rows, segment.expected_raw_columns) == (
            spec.expected_raw_rows,
            spec.expected_raw_columns,
        )
        assert segment.expected_bbox == spec.expected_bbox
        classified = (
            *segment.header_rows,
            *segment.data_rows,
            *segment.note_rows,
            *segment.footnote_rows,
        )
        assert sorted(classified) == list(range(spec.expected_raw_rows))
        assert len(segment.data_rows) == spec.expected_data_rows


def test_no_axis_value_is_declared_and_the_band_axis_comes_from_the_document() -> None:
    for spec in ANNEX_F_TABLES:
        assert all(column.axis_value is None for column in spec.columns)
    data = [column for column in TABLE_F3.columns if column.role == "data"]
    assert len(data) == 7
    assert {column.axis_value_source_row for column in data} == {1}
    # The two-column grids state one bound per data row, not a per-column axis value.
    assert all(
        column.axis_value_source_row is None
        for spec in (TABLE_F1, TABLE_F2)
        for column in spec.columns
    )


def test_no_column_heading_repeats_source_wording() -> None:
    """Headings are author-written descriptions; a digit may only index a column.

    The check guards against a future edit pasting a source heading, which would carry
    its bounds, units, and comparison signs with it.
    """

    for spec in ANNEX_F_TABLES:
        for column in spec.columns:
            assert column.heading == column.heading.lower()
            assert not any(sign in column.heading for sign in ("≤", "<", ">", "="))
            digits = [word for word in column.heading.split() if any(c.isdigit() for c in word)]
            assert digits in ([], [str(column.source_column)])


def test_the_annex_grids_are_extracted_for_comparison_only() -> None:
    for spec in ANNEX_F_TABLES:
        assert spec.decision_route_ids == ()
        assert spec.reference_slots == ()
        assert spec.token_grammar is None


def test_the_band_grid_claims_no_monotonic_axis() -> None:
    """Table F.2's row axis is a range, so the monotonic assertion would be a guess."""

    assert "strictly_increasing_axes" not in TABLE_F2.assertions
    assert "strictly_increasing_axes" in TABLE_F1.assertions
    assert "strictly_increasing_axes" in TABLE_F3.assertions


def test_the_declared_note_blank_extracts_and_an_undeclared_blank_blocks() -> None:
    assert apply_table_structure(_f1_grid(), TABLE_F1) is not None
    with pytest.raises(ExtractionError, match="undeclared blank"):
        apply_table_structure(_f1_grid(blank_at=(5, 1)), TABLE_F1)
