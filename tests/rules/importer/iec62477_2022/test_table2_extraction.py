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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2

SOURCE = SourceReference(
    document_id="synthetic-table-2",
    standard="SYNTHETIC",
    edition="1",
    page=44,
    table="S2",
)
REFERENCE_COORDINATES = {(3, 5), (5, 4)}
STRUCTURAL_BLANKS = {(7, column) for column in range(1, 6)}
INHERITED_BLANKS = {
    (1, 0),
    (2, 0),
    (0, 2),
    (0, 3),
    (0, 4),
    (0, 5),
    (1, 2),
    (1, 3),
    (1, 4),
    (4, 4),
    (4, 5),
    (5, 5),
    (6, 4),
}


def _cell(row: int, column: int) -> RawGridCell:
    data = row in range(3, 7) and column in range(1, 6)
    not_applicable = (row, column) == (6, 5)
    blank = (
        (row, column) in INHERITED_BLANKS
        or (row, column) in STRUCTURAL_BLANKS
        or not_applicable
    )
    reference = (row, column) in REFERENCE_COORDINATES
    text = (
        "NA"
        if not_applicable
        else ("" if blank else ("REF" if reference else f"H_{row}_{column}"))
    )
    value = Decimal(row * 10 + column) if data and not blank else None
    if reference:
        value = None
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text if value is None else str(value),
        role="data" if data else ("blank" if blank else "header"),
        logical_row=row - 3 if data else None,
        logical_column=(
            f"column-{column}" if data else None
        ),
        value=value,
        parse_status=(
            "non_scalar"
            if not_applicable
            else ("blank" if blank else ("numeric" if value is not None else "text"))
        ),
        source=SOURCE.model_copy(
            update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
        ),
    )


def _grid() -> RawGrid:
    return RawGrid(
        id=f"raw-{ids.DVC_VOLTAGE_LIMITS}",
        rows=8,
        columns=6,
        target_unit="V",
        segments=(RawGridSegment(page_number=44, row_start=0, row_count=8, source=SOURCE),),
        cells=tuple(_cell(row, column) for row in range(8) for column in range(6)),
        source=SOURCE,
    )


def test_table_2_recipe_is_structural_and_uses_existing_semantic_targets() -> None:
    assert TABLE_2.page_number == 44
    assert TABLE_2.expected_bbox == (70.9, 314.5, 524.4, 663.2)
    assert (TABLE_2.expected_raw_rows, TABLE_2.expected_raw_columns) == (8, 6)
    assert (TABLE_2.data_row_start, TABLE_2.data_column_start) == (3, 1)
    assert (TABLE_2.expected_data_rows, TABLE_2.expected_data_columns) == (4, 5)
    assert TABLE_2.merged_cells
    assert TABLE_2.blank_cells
    assert {slot.target_rule_id for slot in TABLE_2.reference_slots} == {
        ids.DVC_FAULT_TIME_VOLTAGE,
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
    }
    assert {(slot.row, slot.column) for slot in TABLE_2.reference_slots} == (
        REFERENCE_COORDINATES
    )


def test_merged_headers_and_data_expand_while_logical_coordinates_remain_typed() -> None:
    structured = apply_table_structure(_grid(), TABLE_2)
    cells = {(cell.row, cell.column): cell for cell in structured.cells}

    assert cells[(1, 0)].raw_text == cells[(0, 0)].raw_text
    assert cells[(1, 0)].blank_semantics == "inherit"
    assert cells[(4, 4)].value == cells[(3, 4)].value
    assert cells[(4, 5)].reference_token == cells[(3, 5)].reference_token
    assert cells[(5, 5)].reference_token == cells[(3, 5)].reference_token
    assert cells[(6, 4)].reference_token == cells[(5, 4)].reference_token
    assert (cells[(4, 4)].logical_row, cells[(4, 4)].logical_column) != (
        cells[(3, 4)].logical_row,
        cells[(3, 4)].logical_column,
    )
    assert cells[(6, 5)].blank_semantics == "not_applicable"
    assert cells[(6, 5)].blank_semantics != "missing"
    assert all(cells[coordinate].blank_semantics == "structural" for coordinate in STRUCTURAL_BLANKS)


def test_missing_physical_cell_blocks_structural_expansion() -> None:
    grid = _grid()
    incomplete = grid.model_copy(update={"cells": grid.cells[:-1]})

    with pytest.raises(ExtractionError, match="missing physical cell"):
        apply_table_structure(incomplete, TABLE_2)


def test_declared_blank_rejects_unexpected_numeric_content() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "999", "value": Decimal(999), "parse_status": "numeric"})
        if (cell.row, cell.column) == (6, 5)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ExtractionError, match="declared blank"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_2)


def test_undeclared_blank_header_blocks_structural_expansion() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "", "role": "blank", "parse_status": "blank"})
        if (cell.row, cell.column) == (1, 1)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ExtractionError, match="undeclared blank"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_2)


def test_empty_reference_slot_blocks_structural_expansion() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "", "value": None, "parse_status": "blank"})
        if (cell.row, cell.column) == (3, 5)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ExtractionError, match="reference slot"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_2)
