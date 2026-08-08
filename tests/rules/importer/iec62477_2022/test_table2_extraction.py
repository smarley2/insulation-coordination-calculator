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


def _cell(row: int, column: int) -> RawGridCell:
    blank = (row, column) in {
        (1, 0),
        (0, 2),
        (0, 3),
        (0, 4),
        (0, 5),
        (5, 5),
    }
    text = "" if blank else f"H_{row}_{column}"
    value = Decimal(row * 10 + column) if row >= 2 and column >= 2 and not blank else None
    not_applicable = (row, column) == (5, 5)
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text if value is None else str(value),
        role="data"
        if not_applicable
        else ("blank" if blank else ("data" if value is not None else "header")),
        logical_row=row - 2 if value is not None or not_applicable else None,
        logical_column=f"column-{column - 1}" if value is not None or not_applicable else None,
        value=value,
        parse_status="blank" if blank else ("numeric" if value is not None else "text"),
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
    assert TABLE_2.merged_cells
    assert TABLE_2.blank_cells
    assert {slot.target_rule_id for slot in TABLE_2.reference_slots} == {
        ids.DVC_FAULT_TIME_VOLTAGE,
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac",
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc",
    }


def test_merged_headers_expand_and_meaningful_blanks_remain_typed() -> None:
    structured = apply_table_structure(_grid(), TABLE_2)
    cells = {(cell.row, cell.column): cell for cell in structured.cells}

    assert cells[(1, 0)].raw_text == cells[(0, 0)].raw_text
    assert cells[(1, 0)].blank_semantics == "inherit"
    assert cells[(5, 5)].blank_semantics == "not_applicable"
    assert cells[(5, 5)].blank_semantics != "missing"


def test_missing_physical_cell_blocks_structural_expansion() -> None:
    grid = _grid()
    incomplete = grid.model_copy(update={"cells": grid.cells[:-1]})

    with pytest.raises(ExtractionError, match="missing physical cell"):
        apply_table_structure(incomplete, TABLE_2)
