"""Axis proposals: keyword grammar for three axes, reviewer-supplied for Table 3's columns."""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
    axis_positions,
    propose_axis_selectors,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import (
    TABLE_2,
    TABLE_3,
)

EXPECTED_TABLE_2_ROWS = {
    ("dvc_as", "dry"),
    ("dvc_as", "wet_and_saltwater_wet"),
    ("dvc_b", "not_applicable"),
    ("dvc_c", "not_applicable"),
}
EXPECTED_TABLE_2_COLUMNS = {
    ("normal", "working_voltage", "ac_rms"),
    ("normal", "working_voltage", "ac_peak"),
    ("normal", "working_voltage", "dc_mean"),
    ("normal", "impulse_withstand", "not_applicable"),
    ("single_fault_or_abnormal", "fault_voltage", "ac_peak_or_dc"),
}

_SOURCE = SourceReference(
    document_id="synthetic-axis-proposals",
    standard="SYNTHETIC",
    edition="1",
    page=1,
)


def _header_cell(row: int, column: int, text: str) -> RawGridCell:
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text,
        role="header",
        parse_status="text",
        source=_SOURCE,
    )


def _data_cell(row: int, column: int) -> RawGridCell:
    """A data-role cell. Only role, row and column matter to axis position derivation."""

    return RawGridCell(
        row=row,
        column=column,
        raw_text="1",
        role="data",
        logical_row=row,
        logical_column=f"column-{column}",
        parse_status="numeric",
        value=1,
        source=_SOURCE,
    )


_TABLE_2_DATA_ROWS = range(3, 7)
_TABLE_2_DATA_COLUMNS = range(1, 6)
_TABLE_3_DATA_ROWS = (3, 4, 6)
_TABLE_3_DATA_COLUMNS = range(1, 7)


def _voltage_limits_grid() -> RawGrid:
    """A synthetic Table 2 grid: invented header text carrying the recipe's keywords.

    Both pairings below are deranged against the licensed table: no physical position
    carries the keyword the source assigns it, and neither axis is the source's order
    displaced by a fixed step, so one recovered pairing yields nothing about the others.
    Read the sets of keywords, never the positions they sit at.
    """

    texts = {
        (3, 0): "c",
        (4, 0): "b",
        (5, 0): "as wet",
        (6, 0): "as dry",
        (2, 1): "peak",
        (2, 2): "mean",
        (2, 3): "fault",
        (2, 4): "rms",
        (2, 5): "impulse",
    }

    def cell(row: int, column: int) -> RawGridCell:
        if row in _TABLE_2_DATA_ROWS and column in _TABLE_2_DATA_COLUMNS:
            return _data_cell(row, column)
        return _header_cell(row, column, texts.get((row, column), "placeholder"))

    cells = tuple(cell(row, column) for row in range(8) for column in range(6))
    return RawGrid(
        id="raw-synthetic-table-2",
        rows=8,
        columns=6,
        target_unit="V",
        segments=(RawGridSegment(page_number=1, row_start=0, row_count=8, source=_SOURCE),),
        cells=cells,
        source=_SOURCE,
    )


def _grid_with_header_text(grid: RawGrid, updates: dict[tuple[int, int], str]) -> RawGrid:
    cells = tuple(
        cell.model_copy(update={"raw_text": updates[(cell.row, cell.column)]})
        if (cell.row, cell.column) in updates
        else cell
        for cell in grid.cells
    )
    return grid.model_copy(update={"cells": cells})


def _voltage_limits_grid_with_header_text(row_index: int, text: str) -> RawGrid:
    return _grid_with_header_text(_voltage_limits_grid(), {(row_index, 0): text})


def _voltage_limits_grid_with_column_header_text(mapping: dict[int, str]) -> RawGrid:
    """The synthetic Table 2 grid with the given columns' header row text replaced."""

    return _grid_with_header_text(
        _voltage_limits_grid(), {(2, column): text for column, text in mapping.items()}
    )


def _protection_matrix_grid() -> RawGrid:
    """A synthetic Table 3 grid. Column axis is reviewer-supplied, so no header text matters."""

    def cell(row: int, column: int) -> RawGridCell:
        if row in _TABLE_3_DATA_ROWS and column in _TABLE_3_DATA_COLUMNS:
            return _data_cell(row, column)
        return _header_cell(row, column, "placeholder")

    cells = tuple(cell(row, column) for row in range(9) for column in range(7))
    return RawGrid(
        id="raw-synthetic-table-3",
        rows=9,
        columns=7,
        target_unit="1",
        segments=(RawGridSegment(page_number=1, row_start=0, row_count=9, source=_SOURCE),),
        cells=cells,
        source=_SOURCE,
    )


def test_table_2_declares_its_reviewed_row_and_column_inventories() -> None:
    """Stated independently of the recipe, as unordered sets: physical order is private."""

    rows = {
        (rule.selector.designation, rule.selector.environment)
        for spec in TABLE_2.axis_selectors
        if spec.axis == "row"
        for rule in spec.keyword_rules
    }
    columns = {
        (rule.selector.operating_context, rule.selector.quantity, rule.selector.basis)
        for spec in TABLE_2.axis_selectors
        if spec.axis == "column"
        for rule in spec.keyword_rules
    }

    assert rows == EXPECTED_TABLE_2_ROWS
    assert columns == EXPECTED_TABLE_2_COLUMNS


def test_table_3_columns_are_reviewer_supplied_with_no_keyword_rules() -> None:
    """A text grammar for that axis would need the header hierarchy's wording in public code."""

    column_spec = next(spec for spec in TABLE_3.axis_selectors if spec.axis == "column")

    assert column_spec.reviewer_supplied is True
    assert column_spec.keyword_rules == ()
    assert column_spec.expected_positions == 6


def test_no_keyword_is_a_phrase() -> None:
    """Short neutral keywords only. A multi-word keyword would be source wording."""

    for spec in (*TABLE_2.axis_selectors, *TABLE_3.axis_selectors):
        for rule in spec.keyword_rules:
            for keyword in rule.keywords:
                assert " " not in keyword
                assert keyword == keyword.lower()
                assert 0 < len(keyword) <= 12


def test_reviewer_supplied_axes_propose_nothing_but_still_enumerate_positions() -> None:
    grid = _protection_matrix_grid()

    proposals = propose_axis_selectors(TABLE_3, grid)
    columns = [item for item in proposals if item.axis == "column"]

    assert len(columns) == 6
    assert all(item.selector is None for item in columns)
    assert {item.index for item in columns} == set(range(1, 7))


def test_a_reviewer_supplied_position_still_states_the_kind_it_must_be_confirmed_as() -> None:
    """No proposed reading, but the reviewer is told which of the three kinds to supply.

    Without this the review surface could not know which editor to offer, and a reviewer's
    wrong-kind choice would surface only at resolution.
    """

    column_spec = next(spec for spec in TABLE_3.axis_selectors if spec.axis == "column")

    columns = [
        item
        for item in propose_axis_selectors(TABLE_3, _protection_matrix_grid())
        if item.axis == "column"
    ]

    assert columns
    assert all(item.selector is None for item in columns)
    assert {item.selector_kind for item in columns} == {column_spec.selector_kind}


def test_a_keyword_match_proposes_the_declared_selector() -> None:
    grid = _voltage_limits_grid()

    proposals = propose_axis_selectors(TABLE_2, grid)
    rows = {
        item.index: item.selector
        for item in proposals
        if item.axis == "row" and item.selector is not None
    }

    assert rows
    assert {
        (selector.designation, selector.environment) for selector in rows.values()
    } <= EXPECTED_TABLE_2_ROWS


def test_an_ambiguous_or_absent_match_proposes_nothing_rather_than_guessing() -> None:
    """Zero matches and two matches are both "no confirmed reading", never a positional guess."""

    grid = _voltage_limits_grid_with_header_text(row_index=3, text="nothing recognisable here")

    proposals = propose_axis_selectors(TABLE_2, grid)
    proposal = next(item for item in proposals if item.axis == "row" and item.index == 3)

    assert proposal.selector is None


def test_a_non_contiguous_row_axis_proposes_the_rows_the_spec_declares() -> None:
    """A note row sits inside Table 3's data rows, so a contiguous range would skip a real row.

    The third designation row would get no proposal at all, and the note row would get one.
    """
    grid = _protection_matrix_grid()

    proposals = propose_axis_selectors(TABLE_3, grid)
    rows = sorted(item.index for item in proposals if item.axis == "row")

    assert rows == [3, 4, 6]


def test_a_contiguous_row_axis_is_unaffected() -> None:
    grid = _voltage_limits_grid()

    proposals = propose_axis_selectors(TABLE_2, grid)
    rows = sorted(item.index for item in proposals if item.axis == "row")

    assert rows == [3, 4, 5, 6]


def test_a_declared_position_count_that_disagrees_with_the_spec_is_refused() -> None:
    """The count and the spec must agree, or one of them is wrong and both are load-bearing."""

    wrong = TABLE_3.model_copy(
        update={
            "axis_selectors": tuple(
                item.model_copy(update={"expected_positions": 4}) if item.axis == "row" else item
                for item in TABLE_3.axis_selectors
            )
        }
    )

    with pytest.raises(ValueError):
        propose_axis_selectors(wrong, _protection_matrix_grid())


def test_positions_are_global_grid_coordinates_not_segment_local_ones() -> None:
    """Segment data_rows are segment-local; grid cell rows are global.

    Deriving positions from the grid's own data cells is correct for a multi-segment grid
    without any offset arithmetic, and cannot silently read the wrong row.
    """
    grid = _protection_matrix_grid()
    data_rows = sorted({cell.row for cell in grid.cells if cell.role == "data"})

    row_spec = next(item for item in TABLE_3.axis_selectors if item.axis == "row")

    assert axis_positions(TABLE_3, row_spec, grid) == tuple(data_rows)


def test_a_grid_whose_data_rows_do_not_match_the_declared_count_is_refused() -> None:
    grid = _protection_matrix_grid()
    trimmed = grid.model_copy(update={"cells": tuple(cell for cell in grid.cells if cell.row != 6)})
    row_spec = next(item for item in TABLE_3.axis_selectors if item.axis == "row")

    with pytest.raises(ValueError):
        axis_positions(TABLE_3, row_spec, trimmed)


def test_exclusions_are_what_let_an_ambiguous_column_still_propose() -> None:
    """One generic keyword occurs in several column headers, which is why exclusions exist.

    Without them each affected rule matches several positions and, under exactly-one-match,
    every one of those positions proposes nothing.
    """
    grid = _voltage_limits_grid_with_column_header_text(
        {
            1: "alpha rms",
            2: "alpha peak",
            3: "alpha mean",
            4: "alpha impulse peak",
            5: "alpha fault peak",
        }
    )

    proposals = propose_axis_selectors(TABLE_2, grid)
    columns = {item.index: item.selector for item in proposals if item.axis == "column"}

    assert columns[2] is not None, "the peak column must still propose despite the shared keyword"
    assert columns[4] is not None, "the impulse column must still propose"
    assert columns[5] is not None, "the fault column must still propose"
    assert columns[2].basis == "ac_peak"
    assert columns[4].quantity == "impulse_withstand"
    assert columns[5].quantity == "fault_voltage"


def test_without_exclusions_the_ambiguous_columns_propose_nothing() -> None:
    """Proves the exclusions are load-bearing rather than decorative.

    Column 2's own header text never carries "impulse" or "fault", so the peak rule matches
    it uniquely with or without the exclusion -- that column is a control, not one of the
    ones the exclusion protects. Columns 4 and 5 carry "peak" alongside their own keyword, so
    without the exclusion the peak rule also matches there, and exactly-one-match turns that
    into no proposal at all.
    """

    stripped = TABLE_2.model_copy(
        update={
            "axis_selectors": tuple(
                item.model_copy(
                    update={
                        "keyword_rules": tuple(
                            rule.model_copy(update={"excluded_keywords": ()})
                            for rule in item.keyword_rules
                        )
                    }
                )
                for item in TABLE_2.axis_selectors
            )
        }
    )
    grid = _voltage_limits_grid_with_column_header_text(
        {
            1: "alpha rms",
            2: "alpha peak",
            3: "alpha mean",
            4: "alpha impulse peak",
            5: "alpha fault peak",
        }
    )

    proposals = propose_axis_selectors(stripped, grid)
    columns = {item.index: item.selector for item in proposals if item.axis == "column"}

    assert columns[2] is not None, "unaffected control: its header never carries impulse or fault"
    assert columns[4] is None
    assert columns[5] is None
