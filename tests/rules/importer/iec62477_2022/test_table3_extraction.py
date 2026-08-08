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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_3

SOURCE = SourceReference(
    document_id="synthetic-table-3",
    standard="SYNTHETIC",
    edition="1",
    page=45,
    table="S3",
)


def _cell(row: int, column: int) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if (row, column) == (1, 0):
        return RawGridCell(
            row=row,
            column=column,
            raw_text="",
            role="blank",
            parse_status="blank",
            source=source,
        )
    if row <= 1:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"HEADER_{row}_{column}",
            role="header",
            parse_status="text",
            source=source,
        )
    if column == 0:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"dvc-row-{row - 1}",
            role="header",
            parse_status="text",
            source=source,
        )
    if column == 1:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"category-row-{row - 1}",
            role="header",
            parse_status="text",
            source=source,
        )
    token = "yes" if (row + column) % 2 else "no"
    return RawGridCell(
        row=row,
        column=column,
        raw_text=token,
        role="data",
        logical_row=row - 2,
        logical_column=f"boolean-column-{column - 1}",
        parse_status="text",
        source=source,
    )


def _grid() -> RawGrid:
    return RawGrid(
        id=f"raw-{ids.DVC_PROTECTION_MATRIX}",
        rows=9,
        columns=7,
        target_unit="1",
        segments=(RawGridSegment(page_number=45, row_start=0, row_count=9, source=SOURCE),),
        cells=tuple(_cell(row, column) for row in range(9) for column in range(7)),
        source=SOURCE,
    )


def test_table_3_recipe_is_structural_and_uses_the_protection_matrix_target() -> None:
    assert TABLE_3.semantic_id == ids.DVC_PROTECTION_MATRIX
    assert TABLE_3.source_table == "3"
    assert TABLE_3.title_anchor == "Table 3"
    assert TABLE_3.page_number == 45
    assert TABLE_3.expected_bbox == (71.0, 265.3, 524.3, 744.2)
    assert (TABLE_3.expected_raw_rows, TABLE_3.expected_raw_columns) == (9, 7)
    assert TABLE_3.page_search_radius == 2
    assert TABLE_3.merged_cells


def test_merged_dvc_banner_expands_down_and_blank_stays_typed() -> None:
    structured = apply_table_structure(_grid(), TABLE_3)
    cells = {(cell.row, cell.column): cell for cell in structured.cells}

    assert cells[(1, 0)].raw_text == cells[(0, 0)].raw_text
    assert cells[(1, 0)].blank_semantics == "inherit"


def test_missing_physical_cell_blocks_structural_expansion() -> None:
    grid = _grid()
    incomplete = grid.model_copy(update={"cells": grid.cells[:-1]})

    with pytest.raises(ExtractionError, match="missing physical cell"):
        apply_table_structure(incomplete, TABLE_3)


def test_declared_blank_rejects_unexpected_content() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(
            update={"raw_text": "999", "value": Decimal(999), "parse_status": "numeric"}
        )
        if (cell.row, cell.column) == (1, 0)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ExtractionError, match="declared blank"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_3)


def test_undeclared_blank_blocks_structural_expansion() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "", "role": "blank", "parse_status": "blank"})
        if (cell.row, cell.column) == (0, 3)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ExtractionError, match="undeclared blank"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_3)
