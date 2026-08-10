"""Tables 28 and 29 dielectric-value recipes: route splitting and segment declaration.

Synthetic values only. The system voltages, the working voltages, and every test voltage
belong to the licensed source, so the fixtures here invent their own.
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
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.projection import project_table
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    DIELECTRIC_SPECS,
)

SOURCE = SourceReference(
    document_id="synthetic-dielectric",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S28",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)


def _synthetic_grid(spec: TableAuditSpec) -> RawGrid:
    """A grid shaped like the spec's segments, with invented ascending values."""

    cells: list[RawGridCell] = []
    segments: list[RawGridSegment] = []
    row_start = 0
    logical_row = 0
    for segment in spec.segments:
        segments.append(
            RawGridSegment(
                page_number=segment.page_number,
                row_start=row_start,
                row_count=segment.expected_raw_rows,
                source=SOURCE,
            )
        )
        for row in range(segment.expected_raw_rows):
            data_row = row in segment.data_rows
            for column in range(spec.expected_raw_columns):
                source = SOURCE.model_copy(
                    update={
                        "row": f"grid row {row_start + row + 1}",
                        "column": f"grid column {column + 1}",
                    }
                )
                if data_row:
                    value = Decimal((logical_row + 1) * 100 + column)
                    cells.append(
                        RawGridCell(
                            row=row_start + row,
                            column=column,
                            raw_text=str(value),
                            role="data",
                            logical_row=logical_row,
                            logical_column=spec.columns[column].semantic_id,
                            value=value,
                            parse_status="numeric",
                            source=source,
                        )
                    )
                elif row in segment.header_rows:
                    cells.append(
                        RawGridCell(
                            row=row_start + row,
                            column=column,
                            raw_text=f"neutral header {row}-{column}",
                            role="header",
                            parse_status="text",
                            source=source,
                        )
                    )
                else:
                    cells.append(
                        RawGridCell(
                            row=row_start + row,
                            column=column,
                            raw_text="synthetic note" if column == 0 else "",
                            role="note" if column == 0 else "blank",
                            parse_status="text" if column == 0 else "blank",
                            source=source,
                        )
                    )
            if data_row:
                logical_row += 1
        row_start += segment.expected_raw_rows
    return RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=row_start,
        columns=spec.expected_raw_columns,
        target_unit=spec.target_unit,
        segments=tuple(segments),
        cells=tuple(cells),
        source=SOURCE,
    )


def _by_table(source_table: str) -> tuple[TableAuditSpec, ...]:
    return tuple(spec for spec in DIELECTRIC_SPECS if spec.source_table == source_table)


def test_both_tables_are_declared() -> None:
    assert len(_by_table("28")) == 4
    assert len(_by_table("29")) == 4
    assert len(DIELECTRIC_SPECS) == 8


def test_type_and_routine_values_are_separate_rules() -> None:
    ids_seen = {spec.semantic_id for spec in DIELECTRIC_SPECS}
    assert len(ids_seen) == len(DIELECTRIC_SPECS)
    assert any("type" in name for name in ids_seen)
    assert any("routine" in name for name in ids_seen)


def test_each_route_reads_exactly_one_test_purpose_and_one_supply_kind() -> None:
    for spec in DIELECTRIC_SPECS:
        data = tuple(column for column in spec.columns if column.role == "data")
        assert len(data) == 1
        assert spec.semantic_id.endswith((".ac", ".dc"))
    for source_table in ("28", "29"):
        purposes = {spec.semantic_id.rsplit(".", 2)[-2] for spec in _by_table(source_table)}
        assert len(purposes) == 2


def test_the_routes_hang_off_their_inventory_identifiers() -> None:
    for spec in _by_table("28"):
        assert spec.semantic_id.startswith(f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.")
    for spec in _by_table("29"):
        assert spec.semantic_id.startswith(f"{ids.TEST_NON_MAINS_DIELECTRIC_VALUES}.")


def test_the_mains_table_declares_the_measured_shape() -> None:
    for spec in _by_table("28"):
        segment = spec.segments[0]
        assert (segment.expected_raw_rows, segment.expected_raw_columns) == (10, 5)
        assert segment.header_rows == (0, 1, 2)
        assert segment.note_rows == (9,)
        assert segment.page_number == 127
        assert spec.expected_data_rows == 6


def test_the_non_mains_table_is_one_spec_over_two_segments() -> None:
    for spec in _by_table("29"):
        assert len(spec.segments) == 2
        assert [segment.page_number for segment in spec.segments] == [127, 128]
        assert spec.expected_raw_rows == sum(
            segment.expected_raw_rows for segment in spec.segments
        )
        assert [segment.expected_raw_rows for segment in spec.segments] == [16, 9]
        assert spec.segments[1].logical_row_offset == len(spec.segments[0].data_rows)
        assert spec.expected_data_rows == 18
        # The continuation prints no caption of its own, so it is anchored on the running
        # header instead of on the table title the first segment carries.
        assert spec.segments[0].title_anchor == "Table 29"
        assert spec.segments[1].title_anchor != "Table 29"


def test_the_mains_and_non_mains_tables_key_on_different_quantities() -> None:
    mains = _by_table("28")[0]
    non_mains = _by_table("29")[0]
    assert mains.row_axis_id != non_mains.row_axis_id


def test_column_headings_are_author_written_descriptions() -> None:
    for spec in DIELECTRIC_SPECS:
        for column in spec.columns:
            assert column.heading == column.heading.lower()
            assert column.unit == "V"


def test_every_spec_projects_a_complete_rectangle() -> None:
    for spec in DIELECTRIC_SPECS:
        table = project_table(IDENTITY, spec, _synthetic_grid(spec))
        data_columns = len([c for c in spec.columns if c.role == "data"])
        assert len(table.cells) == spec.expected_data_rows * data_columns
        assert list(table.row_axis.values) == sorted(table.row_axis.values)
