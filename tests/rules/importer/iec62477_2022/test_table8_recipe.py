"""Table 8 clearance recipe: declared structure, blank handling, and fill-down.

Synthetic values only. The pollution-degree axis values, the clearances, and the
correspondence voltages all belong to the licensed source, so the fixtures here invent
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
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.projection import project_table
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.spacing import TABLE_8

SOURCE = SourceReference(
    document_id="synthetic-table-8",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S8",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)
HEADER_ROWS = (0, 1, 2, 3)
DATA_ROWS = tuple(range(4, 14))
NOTE_ROW = 14
AXIS_COLUMN = 0
CONTEXT_COLUMNS = (1, 2)
CLEARANCE_COLUMNS = (3, 4, 5, 6)
DECLARED_BLANKS = frozenset((item.row, item.column) for item in TABLE_8.blank_cells)
#: Invented axis and data values. Every clearance column is a decade apart so a filled-down
#: cell is distinguishable from a printed one.
COLUMN_AXIS_VALUES = {3: "7", 4: "8", 5: "9", 6: "10"}


def _clearance_text(row: int, column: int, *, blank_at: tuple[int, int] | None) -> str:
    if (row, column) == blank_at or (row, column) in DECLARED_BLANKS:
        return ""
    return f"{(column - 2)}{row - 3},0"


def _cell(row: int, column: int, *, blank_at: tuple[int, int] | None) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if row in HEADER_ROWS:
        text = ""
        if row == 0:
            text = f"column {column + 1}"
        elif row == 1 and column in (AXIS_COLUMN, *CONTEXT_COLUMNS, 3):
            text = f"neutral title {column + 1}"
        elif row == 2 and column == 3:
            text = "neutral group title"
        elif row == 3 and column in CLEARANCE_COLUMNS:
            text = COLUMN_AXIS_VALUES[column]
        if not text:
            return RawGridCell(
                row=row, column=column, raw_text="", role="blank", parse_status="blank", source=source
            )
        numeric = text.isdigit()
        return RawGridCell(
            row=row,
            column=column,
            raw_text=text,
            role="header",
            value=Decimal(text) if numeric else None,
            parse_status="numeric" if numeric else "text",
            source=source,
        )
    if row == NOTE_ROW:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="synthetic note" if column == 0 else "",
            role="note" if column == 0 else "blank",
            parse_status="text" if column == 0 else "blank",
            source=source,
        )

    logical_row = DATA_ROWS.index(row)
    if column == AXIS_COLUMN:
        value = Decimal((logical_row + 1) * 100)
        return RawGridCell(
            row=row,
            column=column,
            raw_text=str(value),
            role="data",
            logical_row=logical_row,
            logical_column="impulse_withstand_voltage_v",
            value=value,
            parse_status="numeric",
            source=source,
        )
    if column in CONTEXT_COLUMNS:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"{(logical_row + 1) * 10}",
            role="note",
            parse_status="text",
            source=source,
        )

    text = _clearance_text(row, column, blank_at=blank_at)
    logical_column = f"clearance_pollution_degree_{column - 2}_mm"
    if not text:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="",
            role="blank",
            logical_row=logical_row,
            logical_column=logical_column,
            parse_status="blank",
            source=source,
        )
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text,
        role="data",
        logical_row=logical_row,
        logical_column=logical_column,
        value=Decimal(text.replace(",", ".")),
        parse_status="numeric",
        source=source,
    )


def _grid(*, blank_at: tuple[int, int] | None = None) -> RawGrid:
    return RawGrid(
        id=f"raw-{TABLE_8.semantic_id}",
        rows=TABLE_8.expected_raw_rows,
        columns=TABLE_8.expected_raw_columns,
        target_unit="mm",
        segments=(
            RawGridSegment(
                page_number=1, row_start=0, row_count=TABLE_8.expected_raw_rows, source=SOURCE
            ),
        ),
        cells=tuple(
            _cell(row, column, blank_at=blank_at)
            for row in range(TABLE_8.expected_raw_rows)
            for column in range(TABLE_8.expected_raw_columns)
        ),
        source=SOURCE,
    )


def test_the_spec_declares_the_measured_shape() -> None:
    assert (TABLE_8.expected_raw_rows, TABLE_8.expected_raw_columns) == (15, 7)
    assert TABLE_8.expected_data_rows == 10
    assert TABLE_8.expected_data_columns == 5
    assert TABLE_8.segments[0].data_rows == DATA_ROWS
    assert TABLE_8.target_unit == "mm"


def test_clearances_do_not_interpolate() -> None:
    assert TABLE_8.interpolation == "none"


def test_the_pollution_degree_axis_is_read_from_the_document() -> None:
    data = tuple(column for column in TABLE_8.columns if column.role == "data")
    assert len(data) == 4
    assert all(column.axis_value is None for column in data)
    assert {column.axis_value_source_row for column in data} == {3}
    assert all(row in TABLE_8.segments[0].header_rows for row in (3,))


def test_every_clearance_column_fills_down_and_the_voltage_columns_do_not() -> None:
    for column in TABLE_8.columns:
        assert column.fill_down is (column.role == "data")


def test_the_voltage_correspondence_columns_stay_out_of_the_millimetre_axis() -> None:
    context = tuple(column for column in TABLE_8.columns if column.role == "context")
    assert len(context) == 2
    assert all(column.unit == "V" for column in context)


def test_column_headings_are_author_written_descriptions() -> None:
    for column in TABLE_8.columns:
        assert column.heading
        assert column.heading == column.heading.lower()
        assert column.heading.replace(" ", "").isalnum()


def test_an_undeclared_blank_data_cell_blocks_extraction() -> None:
    with pytest.raises(ExtractionError, match="undeclared blank"):
        apply_table_structure(_grid(blank_at=(9, 3)), TABLE_8)


def test_the_declared_blanks_extract_without_a_review_item() -> None:
    structured = apply_table_structure(_grid(), TABLE_8)
    inherited = tuple(
        cell for cell in structured.cells if cell.blank_semantics == "inherit" and cell.role == "blank"
    )
    assert {(cell.row, cell.column) for cell in inherited} <= DECLARED_BLANKS


def test_a_blank_clearance_repeats_the_last_printed_value_in_its_own_column() -> None:
    table = project_table(IDENTITY, TABLE_8, apply_table_structure(_grid(), TABLE_8))
    by_row: dict[int, dict[int, Decimal]] = {}
    for cell in table.cells:
        by_row.setdefault(cell.row, {})[cell.column] = cell.value
    assert len(by_row) == 10
    assert all(len(columns) == 4 for columns in by_row.values())
    # Rows 1 and 2 print only the first clearance; the rest inherit row 0's values.
    first_row = by_row[0]
    for inheriting_row in (1, 2):
        assert by_row[inheriting_row][1] == first_row[1]
        assert by_row[inheriting_row][2] == first_row[2]
        assert by_row[inheriting_row][3] == first_row[3]


def test_the_filled_table_is_non_decreasing_across_the_pollution_degrees() -> None:
    """The reading that a blank repeats its column, checked rather than assumed.

    A higher pollution degree never permits a smaller clearance, so if the blanks meant
    anything else, some row would come out decreasing.
    """
    table = project_table(IDENTITY, TABLE_8, apply_table_structure(_grid(), TABLE_8))
    by_row: dict[int, list[Decimal]] = {}
    for cell in sorted(table.cells, key=lambda item: (item.row, item.column)):
        by_row.setdefault(cell.row, []).append(cell.value)
    for values in by_row.values():
        assert values == sorted(values)
