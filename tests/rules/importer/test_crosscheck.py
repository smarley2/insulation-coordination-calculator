"""Cross-standard equivalence is proven cell by cell or refused. Synthetic values only."""

from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.crosscheck import compare_across_standards
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
)
from insulation_coordination.rules.importer.identify import (
    CrossStandardAxisMatchSpec,
    CrossStandardCheckSpec,
)

SOURCE = SourceReference(
    document_id="synthetic-cross-standard",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    clause="1",
)
CELL_IDS = ("0/first", "1/first")


def _grid(grid_id: str, *values: str, unit: str = "mm") -> RawGrid:
    cells = tuple(
        RawGridCell(
            row=index,
            column=0,
            raw_text=text,
            role="data",
            logical_row=index,
            logical_column="first",
            value=Decimal(text) if text.replace(".", "").isdigit() else None,
            parse_status="numeric" if text.replace(".", "").isdigit() else "text",
            source=SOURCE,
        )
        for index, text in enumerate(values)
    )
    return RawGrid(
        id=grid_id,
        rows=len(values),
        columns=1,
        target_unit=unit,
        segments=(
            RawGridSegment(page_number=1, row_start=0, row_count=len(values), source=SOURCE),
        ),
        cells=cells,
        source=SOURCE,
    )


def _spec(cell_map: tuple[tuple[str, str], ...] = ()) -> CrossStandardCheckSpec:
    pairs = cell_map or tuple((identifier, identifier) for identifier in CELL_IDS)
    return CrossStandardCheckSpec(
        id="synthetic-check",
        source_rule_id="raw-source",
        target_rule_id="raw-target",
        family="synthetic",
        cell_map=pairs,
        source_data_cell_ids=tuple(source_id for source_id, _target in pairs),
        source=SOURCE,
    )


def _grids(*grids: RawGrid) -> dict[str, RawGrid]:
    return {grid.id: grid for grid in grids}


def test_equal_grids_yield_one_unapproved_mapping_and_no_review_item() -> None:
    mapping, items = compare_across_standards(
        _grids(_grid("raw-source", "1.5", "3.0"), _grid("raw-target", "1.5", "3.0")),
        _spec(),
    )
    assert items == ()
    assert mapping is not None
    assert mapping.approved is False
    assert (mapping.source_rule_id, mapping.target_rule_id) == ("raw-source", "raw-target")


def test_a_difference_in_printed_form_alone_is_not_a_divergence() -> None:
    mapping, items = compare_across_standards(
        _grids(_grid("raw-source", "1.5", "3.0"), _grid("raw-target", "1.50", "3")),
        _spec(),
    )
    assert items == ()
    assert mapping is not None


def test_one_divergent_cell_blocks_and_produces_no_mapping() -> None:
    mapping, items = compare_across_standards(
        _grids(_grid("raw-source", "1.5", "3.0"), _grid("raw-target", "1.5", "3.2")),
        _spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_VALUE_DIVERGENCE"]
    assert "1/first" in items[0].expected_contract


def test_a_missing_target_cell_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(_grid("raw-source", "1.5", "3.0"), _grid("raw-target", "1.5")),
        _spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_TARGET_MISSING"]


def test_an_absent_grid_blocks() -> None:
    mapping, items = compare_across_standards(_grids(_grid("raw-source", "1.5", "3.0")), _spec())
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_GRID_MISSING"]
    assert "raw-target" in items[0].expected_contract


def test_equal_numbers_in_different_units_do_not_prove_equivalence() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _grid("raw-source", "1.5", "3.0"),
            _grid("raw-target", "1.5", "3.0", unit="kV"),
        ),
        _spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_UNIT_MISMATCH"]


def test_unparsed_cells_compare_by_their_source_text() -> None:
    mapping, items = compare_across_standards(
        _grids(_grid("raw-source", "see note", "3.0"), _grid("raw-target", "see note", "3.0")),
        _spec(),
    )
    assert items == ()
    assert mapping is not None


def test_a_cell_map_that_omits_a_source_data_cell_is_rejected() -> None:
    with pytest.raises(ValueError, match="cover every source data cell"):
        CrossStandardCheckSpec(
            id="partial",
            source_rule_id="raw-source",
            target_rule_id="raw-target",
            family="synthetic",
            cell_map=(("0/first", "0/first"),),
            source_data_cell_ids=CELL_IDS,
            source=SOURCE,
        )


def _axis_grid(
    grid_id: str,
    rows: tuple[tuple[str, ...], ...],
    *,
    columns: tuple[str, ...],
    axis_column: str = "axis",
) -> RawGrid:
    """One grid whose first column is the row axis and the rest carry requirements."""

    names = (axis_column, *columns)
    cells = tuple(
        RawGridCell(
            row=row_index,
            column=column_index,
            raw_text=text,
            role="data" if text.strip() else "blank",
            logical_row=row_index,
            logical_column=names[column_index],
            value=Decimal(text) if text.strip().replace(".", "").isdigit() else None,
            parse_status=(
                "numeric" if text.strip().replace(".", "").isdigit() else "blank"
                if not text.strip()
                else "text"
            ),
            source=SOURCE,
        )
        for row_index, row in enumerate(rows)
        for column_index, text in enumerate(row)
    )
    return RawGrid(
        id=grid_id,
        rows=len(rows),
        columns=len(names),
        target_unit="mm",
        segments=(RawGridSegment(page_number=1, row_start=0, row_count=len(rows), source=SOURCE),),
        cells=cells,
        source=SOURCE,
    )


def _axis_spec(**overrides: object) -> CrossStandardCheckSpec:
    """A source stated in thousandths of the target's axis unit, one compared column."""

    fields: dict[str, object] = {
        "source_axis_column": "axis",
        "target_axis_column": "axis",
        "axis_value_scale": Decimal("0.001"),
        "column_pairs": (("first", "first"),),
    }
    fields.update(overrides)
    return CrossStandardCheckSpec(
        id="synthetic-axis-check",
        source_rule_id="raw-source",
        target_rule_id="raw-target",
        family="synthetic",
        axis_match=CrossStandardAxisMatchSpec.model_validate(fields),
        source=SOURCE,
    )


def test_rows_pair_by_their_axis_value_in_the_target_unit_not_by_position() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"), ("4000", "3.0")), columns=("first",)),
            _axis_grid(
                "raw-target",
                (("1", "0.8"), ("2", "1.5"), ("3", "2.2"), ("4", "3.0")),
                columns=("first",),
            ),
        ),
        _axis_spec(),
    )
    assert items == ()
    assert mapping is not None


def test_a_source_row_the_target_axis_does_not_reach_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("500", "0.4"), ("2000", "1.5")), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_AXIS_ROW_UNMATCHED"]
    assert "source row 0" in items[0].expected_contract


def test_a_declared_row_without_a_counterpart_is_excluded_and_named_in_the_notes() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("500", "0.4"), ("2000", "1.5")), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(uncompared_source_rows=((0, "the target standard's axis stops above it"),)),
    )
    assert items == ()
    assert mapping is not None
    assert "source row 0" in mapping.notes
    assert "the target standard's axis stops above it" in mapping.notes


def test_a_declared_row_the_target_agrees_on_is_refused() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(uncompared_source_rows=((0, "claimed to have no counterpart"),)),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_ROW_EXCLUSION_UNNEEDED"]


def test_a_declared_row_the_target_has_no_requirement_on_stays_excluded() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", ""),), columns=("first",)),
        ),
        _axis_spec(uncompared_source_rows=((0, "the target carries no requirement there"),)),
    )
    assert items == ()
    assert mapping is not None


def test_a_source_column_that_is_neither_paired_nor_declared_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5", "2.5"),), columns=("first", "second")),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_COLUMN_UNDECLARED"]
    assert "second" in items[0].expected_contract


def test_a_declared_column_without_a_counterpart_is_excluded_and_named_in_the_notes() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5", "2.5"),), columns=("first", "second")),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(
            uncompared_source_columns=(("second", "the target standard has no such column"),)
        ),
    )
    assert items == ()
    assert mapping is not None
    assert "source column second" in mapping.notes
    assert "the target standard has no such column" in mapping.notes


def test_a_divergent_cell_on_a_matched_row_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.6"),), columns=("first",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_VALUE_DIVERGENCE"]
    assert "0/first" in items[0].expected_contract


def test_a_target_that_repeats_one_axis_value_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"), ("2", "1.5")), columns=("first",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_TARGET_AXIS_AMBIGUOUS"]


def test_a_row_whose_axis_cell_holds_no_number_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("see note", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_AXIS_UNREADABLE"]


def test_a_paired_column_absent_from_the_target_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("other",)),
        ),
        _axis_spec(),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_TARGET_MISSING"]


def test_a_declared_row_the_source_does_not_have_blocks() -> None:
    mapping, items = compare_across_standards(
        _grids(
            _axis_grid("raw-source", (("2000", "1.5"),), columns=("first",)),
            _axis_grid("raw-target", (("2", "1.5"),), columns=("first",)),
        ),
        _axis_spec(uncompared_source_rows=((7, "a row index that no longer exists"),)),
    )
    assert mapping is None
    assert [item.code for item in items] == ["CROSS_STANDARD_SOURCE_MISSING"]


def test_a_check_declaring_both_pairing_kinds_is_rejected() -> None:
    with pytest.raises(ValueError, match="either an explicit cell map or an axis match"):
        CrossStandardCheckSpec(
            id="both",
            source_rule_id="raw-source",
            target_rule_id="raw-target",
            family="synthetic",
            cell_map=(("0/first", "0/first"),),
            source_data_cell_ids=("0/first",),
            axis_match=CrossStandardAxisMatchSpec(
                source_axis_column="axis",
                target_axis_column="axis",
                column_pairs=(("first", "first"),),
            ),
            source=SOURCE,
        )


def test_a_check_declaring_no_pairing_at_all_is_rejected() -> None:
    with pytest.raises(ValueError, match="either an explicit cell map or an axis match"):
        CrossStandardCheckSpec(
            id="neither",
            source_rule_id="raw-source",
            target_rule_id="raw-target",
            family="synthetic",
            source=SOURCE,
        )


def test_an_axis_match_that_declares_one_column_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="each source column once"):
        CrossStandardAxisMatchSpec(
            source_axis_column="axis",
            target_axis_column="axis",
            column_pairs=(("first", "first"),),
            uncompared_source_columns=(("first", "and also excluded"),),
        )


def test_an_axis_match_that_compares_its_own_axis_column_is_rejected() -> None:
    with pytest.raises(ValueError, match="its own axis column"):
        CrossStandardAxisMatchSpec(
            source_axis_column="axis",
            target_axis_column="axis",
            column_pairs=(("axis", "axis"),),
        )


def test_an_axis_match_with_a_non_positive_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="scale must be positive"):
        CrossStandardAxisMatchSpec(
            source_axis_column="axis",
            target_axis_column="axis",
            axis_value_scale=Decimal(0),
            column_pairs=(("first", "first"),),
        )


def test_an_axis_match_that_declares_one_row_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="each source row once"):
        CrossStandardAxisMatchSpec(
            source_axis_column="axis",
            target_axis_column="axis",
            column_pairs=(("first", "first"),),
            uncompared_source_rows=((0, "one reason"), (0, "another reason")),
        )


def test_a_cell_map_that_repeats_a_source_cell_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not repeat a source cell"):
        CrossStandardCheckSpec(
            id="repeated",
            source_rule_id="raw-source",
            target_rule_id="raw-target",
            family="synthetic",
            cell_map=(("0/first", "0/first"), ("0/first", "1/first")),
            source_data_cell_ids=("0/first",),
            source=SOURCE,
        )
