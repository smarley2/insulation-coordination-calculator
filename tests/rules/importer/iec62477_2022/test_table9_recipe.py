"""Table 9 creepage recipes: row strategy, column selection, and interpolation.

Synthetic values only. Working voltages and creepage distances belong to the licensed
source, so the fixtures invent their own.
"""

from __future__ import annotations

from decimal import Decimal

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
)
from insulation_coordination.rules.importer.identify import StandardIdentity, TableAuditSpec
from insulation_coordination.rules.importer.projection import project_table
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.spacing import (
    TABLE_8,
    TABLE_9_OTHER_INSULATORS,
    TABLE_9_PRINTED_WIRING,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLES

SOURCE = SourceReference(
    document_id="synthetic-table-9",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S9",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)
BOTH = (TABLE_9_PRINTED_WIRING, TABLE_9_OTHER_INSULATORS)
#: Columns 7 and 11 of the source grid carry no data on any row.
ARTIFACT_COLUMNS = (7, 11)


def _grid(spec: TableAuditSpec) -> RawGrid:
    """A grid holding only the rows and columns this spec declares, with invented values."""

    segment = spec.segments[0]
    data_columns = tuple(column for column in spec.columns if column.role == "data")
    cells: list[RawGridCell] = []
    for logical_row, physical_row in enumerate(segment.data_rows):
        axis_value = Decimal((logical_row + 1) * 10)
        cells.append(
            RawGridCell(
                row=physical_row,
                column=0,
                raw_text=str(axis_value),
                role="data",
                logical_row=logical_row,
                logical_column=spec.row_axis_id,
                value=axis_value,
                parse_status="numeric",
                source=SOURCE,
            )
        )
        for ordinal, column in enumerate(data_columns, start=1):
            value = Decimal(f"{logical_row + 1}.{ordinal}")
            cells.append(
                RawGridCell(
                    row=physical_row,
                    # Extraction compacts the declared source columns, so a grid column
                    # index is the column's position in the spec, not its source index.
                    column=ordinal,
                    raw_text=str(value),
                    role="data",
                    logical_row=logical_row,
                    logical_column=column.semantic_id,
                    value=value,
                    parse_status="numeric",
                    source=SOURCE,
                )
            )
    return RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=spec.expected_raw_rows,
        columns=spec.expected_raw_columns,
        target_unit="mm",
        segments=(
            RawGridSegment(
                page_number=1, row_start=0, row_count=spec.expected_raw_rows, source=SOURCE
            ),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def test_row_boundaries_come_from_text_lines_not_ruling_lines() -> None:
    """Table 9 rules one box around several working voltages, so lines cannot split rows."""

    for spec in BOTH:
        assert spec.segments[0].row_strategy == "text"


def test_the_default_row_strategy_is_unchanged_for_every_other_table() -> None:
    for spec in TABLES:
        for segment in spec.segments:
            if spec.semantic_id.startswith("iec62477_2022.creepage."):
                continue
            assert segment.row_strategy == "lines"


def test_creepage_permits_interpolation_where_clearance_does_not() -> None:
    assert {spec.interpolation for spec in BOTH} == {"linear"}
    assert TABLE_8.interpolation == "none"


def test_the_three_spacing_and_stress_tables_do_not_share_one_interpolation_default() -> None:
    table_7 = tuple(spec for spec in TABLES if spec.source_table == "7")
    assert {spec.interpolation for spec in table_7} == {"none", "linear"}


def test_no_spec_reads_a_column_that_holds_no_data() -> None:
    for spec in BOTH:
        read = {column.source_column for column in spec.columns}
        assert read.isdisjoint(ARTIFACT_COLUMNS)
        assert set(spec.segments[0].source_columns).isdisjoint(ARTIFACT_COLUMNS)


def test_the_printed_wiring_lookup_stops_where_its_data_stops() -> None:
    """Above its limit the source prints a footnote marker, not a value.

    The spec covers the rows that carry values and leaves the rest to the footnote in the
    raw grid, rather than classifying nine rows of absent requirements.
    """
    printed = TABLE_9_PRINTED_WIRING.segments[0].data_rows
    other = TABLE_9_OTHER_INSULATORS.segments[0].data_rows
    assert len(printed) == 21
    assert len(other) == 30
    assert printed == other[:21]


def test_each_spec_fixes_one_construction_and_reads_its_material_groups() -> None:
    printed = tuple(c for c in TABLE_9_PRINTED_WIRING.columns if c.role == "data")
    other = tuple(c for c in TABLE_9_OTHER_INSULATORS.columns if c.role == "data")
    assert len(printed) == 2
    assert len(other) == 7
    assert all(column.unit == "mm" for column in (*printed, *other))
    assert TABLE_9_PRINTED_WIRING.column_axis_id != TABLE_9_OTHER_INSULATORS.column_axis_id


def test_column_headings_are_author_written_descriptions() -> None:
    for spec in BOTH:
        for column in spec.columns:
            assert column.heading == column.heading.lower()
            assert column.heading.replace(" ", "").isalnum()


def test_both_specs_project_a_complete_rectangle() -> None:
    for spec in BOTH:
        table = project_table(IDENTITY, spec, _grid(spec))
        data_columns = len(tuple(column for column in spec.columns if column.role == "data"))
        assert len(table.row_axis.values) == spec.expected_data_rows
        assert len(table.column_axis.values) == data_columns
        assert len(table.cells) == spec.expected_data_rows * data_columns
        assert list(table.row_axis.values) == sorted(table.row_axis.values)
