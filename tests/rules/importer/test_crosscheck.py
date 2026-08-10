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
from insulation_coordination.rules.importer.identify import CrossStandardCheckSpec

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
