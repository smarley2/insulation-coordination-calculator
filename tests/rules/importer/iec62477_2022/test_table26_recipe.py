"""Table 26 impulse-procedure recipe: declared rows, variants, and projection.

Synthetic values only. Every subject and condition in the source is licensed wording, so
the fixtures invent their own.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    CONTINUATION_ROWS,
    FIELD_ROWS,
    TABLE_26,
    VARIANT_COLUMNS,
    ProcedureStructureError,
    project_impulse_procedure,
)

SOURCE = SourceReference(
    document_id="iec62477-1-2022",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S26",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)
#: Rows whose condition is stated once for every variant, so only the first condition
#: column is filled and the other variants inherit it.
SPANNING_ROWS = (1, 2, 16)


def _text(row: int, column: int) -> str:
    if column == 0:
        return "" if row in CONTINUATION_ROWS else f"synthetic subject {row}"
    if row in SPANNING_ROWS:
        return f"synthetic spanning condition {row}" if column == 1 else ""
    return f"synthetic condition {row} variant {column}"


def _grid(*, undeclared_row: bool = False, empty_variant: int | None = None) -> RawGrid:
    cells: list[RawGridCell] = []
    for row in range(TABLE_26.expected_raw_rows):
        for column in range(TABLE_26.expected_raw_columns):
            if row == 0:
                text, role = f"synthetic header {column}", "header"
            elif undeclared_row and row == max(CONTINUATION_ROWS) - 1:
                # A subject the recipe does not declare as a field or a continuation.
                text, role = ("undeclared subject" if column == 0 else ""), "note"
            elif empty_variant is not None and column == empty_variant:
                text, role = "", "note"
            else:
                text, role = _text(row, column), "note"
            cells.append(
                RawGridCell(
                    row=row,
                    column=column,
                    raw_text=text,
                    role=role,  # type: ignore[arg-type]
                    parse_status="text" if text else "blank",
                    source=SOURCE.model_copy(
                        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
                    ),
                )
            )
    return RawGrid(
        id=f"raw-{ids.TEST_IMPULSE_PROCEDURE}",
        rows=TABLE_26.expected_raw_rows,
        columns=TABLE_26.expected_raw_columns,
        target_unit="1",
        segments=(
            RawGridSegment(
                page_number=1,
                row_start=0,
                row_count=TABLE_26.expected_raw_rows,
                source=SOURCE,
            ),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def test_the_spec_declares_the_measured_shape() -> None:
    assert (TABLE_26.expected_raw_rows, TABLE_26.expected_raw_columns) == (20, 4)
    assert TABLE_26.segments[0].header_rows == (0,)
    assert len(TABLE_26.segments[0].data_rows) == 19
    assert TABLE_26.expected_data_rows == 19


def test_every_data_row_is_either_a_declared_field_or_a_declared_continuation() -> None:
    declared = {row for row, _field in FIELD_ROWS} | set(CONTINUATION_ROWS)
    assert declared == set(TABLE_26.segments[0].data_rows)


def test_no_row_feeds_two_fields() -> None:
    rows = [row for row, _field in FIELD_ROWS]
    assert len(rows) == len(set(rows))
    assert set(rows).isdisjoint(CONTINUATION_ROWS)


def test_field_and_variant_names_are_author_written() -> None:
    for _row, field in FIELD_ROWS:
        assert field == field.lower()
        assert field.replace("_", "").isalnum()
    for variant, _column in VARIANT_COLUMNS:
        assert variant == variant.lower()
        assert variant.replace("_", "").isalnum()


def test_the_spec_declares_one_route_per_variant() -> None:
    assert TABLE_26.decision_route_ids == tuple(
        f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}" for variant, _column in VARIANT_COLUMNS
    )


def test_the_cells_are_reviewed_text_not_quantities() -> None:
    """No cell here is a number, so none is flagged for numeric retyping."""

    assert TABLE_26.text_field_table is True
    assert TABLE_26.comparison_only is False
    assert TABLE_26.target_unit == "1"
    assert [column.unit for column in TABLE_26.columns] == ["1"] * len(TABLE_26.columns)


def test_the_projection_yields_one_procedure_per_variant() -> None:
    rules, proposals = project_impulse_procedure(_grid(), IDENTITY)
    assert {rule.id for rule in rules} == set(TABLE_26.decision_route_ids)
    assert {proposal.rule_kind for proposal in proposals} == {"procedure"}
    assert len(proposals) == len(rules) == 3
    for rule in rules:
        assert rule.procedure_steps
        assert rule.repetitions
        assert rule.preparation_steps


def test_procedure_steps_are_numbered_consecutively_from_one() -> None:
    rules, _proposals = project_impulse_procedure(_grid(), IDENTITY)
    for rule in rules:
        assert [step.order for step in rule.procedure_steps] == list(
            range(1, len(rule.procedure_steps) + 1)
        )


def test_a_condition_stated_once_reaches_every_variant() -> None:
    rules, _proposals = project_impulse_procedure(_grid(), IDENTITY)
    assert len({rule.repetitions for rule in rules}) == 1


def test_a_variant_specific_condition_stays_with_its_variant() -> None:
    rules, _proposals = project_impulse_procedure(_grid(), IDENTITY)
    equipment = {
        rule.id: tuple(step.text for step in rule.procedure_steps) for rule in rules
    }
    assert len({steps for steps in equipment.values()}) == 3


def test_every_step_carries_the_row_it_came_from() -> None:
    rules, _proposals = project_impulse_procedure(_grid(), IDENTITY)
    for rule in rules:
        for step in rule.procedure_steps:
            assert step.source.row is not None
            assert step.source.table == "26"


def test_a_printing_with_an_extra_subject_row_blocks() -> None:
    """A row the recipe has never seen must not pass through unnoticed."""

    grid = _grid()
    extra = tuple(
        RawGridCell(
            row=TABLE_26.expected_raw_rows,
            column=column,
            raw_text="unexpected subject" if column == 0 else "",
            role="note",
            parse_status="text" if column == 0 else "blank",
            source=SOURCE,
        )
        for column in range(TABLE_26.expected_raw_columns)
    )
    taller = grid.model_copy(
        update={
            "rows": grid.rows + 1,
            "cells": (*grid.cells, *extra),
            "segments": (
                grid.segments[0].model_copy(update={"row_count": grid.rows + 1}),
            ),
        }
    )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_impulse_procedure(taller, IDENTITY)


def test_a_variant_column_that_disappears_blocks() -> None:
    grid = _grid()
    narrower = grid.model_copy(
        update={
            "columns": grid.columns - 1,
            "cells": tuple(
                cell for cell in grid.cells if cell.column < TABLE_26.expected_raw_columns - 1
            ),
        }
    )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_impulse_procedure(narrower, IDENTITY)


def test_a_grid_from_another_document_is_refused() -> None:
    with pytest.raises(ValueError, match="does not match its identified source"):
        project_impulse_procedure(_grid(), IDENTITY.model_copy(update={"edition": "2"}))


def test_a_foreign_grid_is_refused() -> None:
    grid = _grid()
    with pytest.raises(ValueError, match="requires its own grid"):
        project_impulse_procedure(grid.model_copy(update={"id": "raw-other"}), IDENTITY)
