"""Table 27 impulse-selection recipe: the two parallel row axes and their projection.

Synthetic values only. The system voltages and the selected test voltages all belong to the
licensed source, so the fixtures here invent their own.
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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    TABLE_27_SPECS,
)

AC_SPECS = tuple(spec for spec in TABLE_27_SPECS if spec.semantic_id.endswith(".ac"))
DC_SPECS = tuple(spec for spec in TABLE_27_SPECS if spec.semantic_id.endswith(".dc"))

SOURCE = SourceReference(
    document_id="synthetic-table-27",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S27",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)


def _cell(spec: TableAuditSpec, row: int, column: int) -> RawGridCell:
    """One physical cell of the compacted grid the segment's ``source_columns`` select."""

    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    segment = spec.segments[0]
    if row in segment.header_rows:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"neutral header {row}-{column}",
            role="header",
            parse_status="text",
            source=source,
        )
    if row not in segment.data_rows:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="synthetic note" if column == 0 else "",
            role="note" if column == 0 else "blank",
            parse_status="text" if column == 0 else "blank",
            source=source,
        )
    logical_row = segment.data_rows.index(row)
    value = Decimal((logical_row + 1) * 100 + column)
    return RawGridCell(
        row=row,
        column=column,
        raw_text=str(value),
        role="data",
        logical_row=logical_row,
        logical_column=spec.columns[column].semantic_id,
        value=value,
        parse_status="numeric",
        source=source,
    )


def _synthetic_grid(spec: TableAuditSpec) -> RawGrid:
    return RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=spec.expected_raw_rows,
        columns=spec.expected_raw_columns,
        target_unit=spec.target_unit,
        segments=(
            RawGridSegment(
                page_number=1, row_start=0, row_count=spec.expected_raw_rows, source=SOURCE
            ),
        ),
        cells=tuple(
            _cell(spec, row, column)
            for row in range(spec.expected_raw_rows)
            for column in range(spec.expected_raw_columns)
        ),
        source=SOURCE,
    )


def test_the_spec_declares_the_measured_shape() -> None:
    for spec in TABLE_27_SPECS:
        segment = spec.segments[0]
        assert (segment.expected_raw_rows, segment.expected_raw_columns) == (12, 6)
        assert segment.header_rows == (0, 1, 2)
        assert segment.note_rows == (10, 11)
        assert spec.page_number == 125
        assert spec.expected_raw_columns == len(segment.source_columns)


def test_the_ac_and_dc_routes_read_their_own_axis_column() -> None:
    assert len(AC_SPECS) == len(DC_SPECS) == 2
    for ac, dc in zip(AC_SPECS, DC_SPECS, strict=True):
        assert ac.row_axis_id != dc.row_axis_id
        ac_axis = next(c for c in ac.columns if c.role == "axis")
        dc_axis = next(c for c in dc.columns if c.role == "axis")
        assert (ac_axis.source_column, dc_axis.source_column) == (0, 1)


def test_the_ac_route_drops_the_dc_only_row() -> None:
    """The last data row states no AC system voltage, so the AC route never reads it."""

    for ac, dc in zip(AC_SPECS, DC_SPECS, strict=True):
        ac_rows = ac.segments[0].data_rows
        dc_rows = dc.segments[0].data_rows
        assert dc_rows == (*ac_rows, dc_rows[-1])
        assert (ac.expected_data_rows, dc.expected_data_rows) == (6, 7)


def test_each_spec_covers_one_column_pair() -> None:
    """Four routes: two column pairs of two data columns each, times two supply kinds."""

    assert len(TABLE_27_SPECS) == 4
    pairs = {
        tuple(c.source_column for c in spec.columns if c.role == "data")
        for spec in TABLE_27_SPECS
    }
    assert pairs == {(2, 3), (4, 5)}
    for spec in TABLE_27_SPECS:
        assert spec.expected_data_columns == len(spec.columns) == 3


def test_the_two_column_pairs_do_not_share_one_interpolation_setting() -> None:
    """The source permits interpolation for one pair and refuses it for the other.

    One ``interpolation`` flag per spec cannot state both, so a single shared setting means
    the recipe is no longer saying what the source says.
    """

    by_pair = {
        tuple(c.source_column for c in spec.columns if c.role == "data"): spec.interpolation
        for spec in TABLE_27_SPECS
    }
    assert len(set(by_pair.values())) == 2
    assert by_pair == {(2, 3): "linear", (4, 5): "none"}


def test_the_routes_are_suffixed_off_the_inventory_identifier() -> None:
    assert {spec.semantic_id.rsplit(".", 1)[1] for spec in TABLE_27_SPECS} == {"ac", "dc"}
    for ac, dc in zip(AC_SPECS, DC_SPECS, strict=True):
        assert ac.semantic_id.removesuffix(".ac") == dc.semantic_id.removesuffix(".dc")
    roots = {spec.semantic_id.rsplit(".", 2)[0] for spec in TABLE_27_SPECS}
    assert roots == {"iec62477_2022.test.impulse_selection"}


def test_column_headings_are_author_written_descriptions() -> None:
    for spec in TABLE_27_SPECS:
        for column in spec.columns:
            assert column.heading == column.heading.lower()
            assert column.unit == "V"


def test_both_routes_project_a_complete_rectangle() -> None:
    for spec in TABLE_27_SPECS:
        table = project_table(IDENTITY, spec, _synthetic_grid(spec))
        data_columns = len([c for c in spec.columns if c.role == "data"])
        # Extraction gives the axis column a logical coordinate too, so the spec's
        # ``expected_data_columns`` is one greater than the projected column count.
        assert (data_columns, spec.expected_data_columns) == (2, 3)
        assert len(table.cells) == spec.expected_data_rows * data_columns
        assert list(table.row_axis.values) == sorted(table.row_axis.values)
