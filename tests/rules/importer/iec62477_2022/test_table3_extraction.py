from __future__ import annotations

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
DATA_ROWS = (3, 4, 6)
DATA_COLUMNS = range(1, 7)
CONTINUATIONS = {(5, 4), (7, 5)}
OUTCOMES = ("none", "basic protection", "enhanced protection")


def _cell(row: int, column: int) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if row in DATA_ROWS and column in DATA_COLUMNS:
        logical_row = DATA_ROWS.index(row)
        return RawGridCell(
            row=row,
            column=column,
            raw_text=OUTCOMES[(logical_row + column) % len(OUTCOMES)],
            role="data",
            logical_row=logical_row,
            logical_column=f"protection-context-{column}",
            parse_status="non_scalar",
            source=source,
        )
    if row in DATA_ROWS and column == 0:
        return RawGridCell(
            row=row,
            column=column,
            raw_text=f"DVC {DATA_ROWS.index(row) + 1}",
            role="note",
            parse_status="text",
            source=source,
        )
    if (row, column) in CONTINUATIONS:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="source continuation",
            role="note",
            parse_status="text",
            source=source,
        )
    if row == 8 and column == 0:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="source notes",
            role="footnote",
            parse_status="text",
            source=source,
        )
    raw_text = f"HEADER_{row}_{column}" if row <= 2 else ""
    return RawGridCell(
        row=row,
        column=column,
        raw_text=raw_text,
        role="header" if raw_text else "blank",
        parse_status="text" if raw_text else "blank",
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


def test_table_3_recipe_declares_physical_and_semantic_structure() -> None:
    assert TABLE_3.semantic_id == ids.DVC_PROTECTION_MATRIX
    assert TABLE_3.source_table == "3"
    assert TABLE_3.page_number == 45
    assert TABLE_3.expected_bbox == (71.0, 265.3, 524.3, 744.2)
    assert (TABLE_3.expected_raw_rows, TABLE_3.expected_raw_columns) == (9, 7)
    assert (TABLE_3.expected_data_rows, TABLE_3.expected_data_columns) == (3, 6)
    assert TABLE_3.segments[0].header_rows == (0, 1, 2)
    assert TABLE_3.segments[0].data_rows == DATA_ROWS
    assert TABLE_3.segments[0].note_rows == (5, 7)
    assert TABLE_3.segments[0].footnote_rows == (8,)
    assert tuple(column.source_column for column in TABLE_3.columns) == tuple(range(7))


def test_category_prefix_grammar_resolves_only_neutral_outcomes() -> None:
    grammar = TABLE_3.token_grammar
    assert grammar is not None
    assert grammar.target == "categorical"
    assert grammar.resolve("None with source marker") == "none"
    assert grammar.resolve("Basic protection with source marker") == "basic_protection"
    assert grammar.resolve("Enhanced protection with source marker") == "enhanced_protection"
    assert grammar.resolve("unknown") is None


def test_structure_retains_exactly_eighteen_data_cells_and_source_continuations() -> None:
    structured = apply_table_structure(_grid(), TABLE_3)
    data = tuple(cell for cell in structured.cells if cell.role == "data")
    assert len(data) == 18
    assert {(cell.logical_row, cell.logical_column) for cell in data} == {
        (row, f"protection-context-{column}") for row in range(3) for column in range(1, 7)
    }
    assert all(
        next(cell for cell in structured.cells if (cell.row, cell.column) == coordinate).role
        == "note"
        for coordinate in CONTINUATIONS
    )


def test_missing_physical_cell_blocks_structural_expansion() -> None:
    grid = _grid()
    with pytest.raises(ExtractionError, match="missing physical cell"):
        apply_table_structure(grid.model_copy(update={"cells": grid.cells[:-1]}), TABLE_3)


def test_unknown_category_blocks_structural_expansion() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "unknown"})
        if (cell.row, cell.column) == (3, 1)
        else cell
        for cell in grid.cells
    )
    with pytest.raises(ExtractionError, match="unknown categorical token"):
        apply_table_structure(grid.model_copy(update={"cells": cells}), TABLE_3)
