"""Table 30 partial-discharge recipe: declared rows, projection, and applicability.

Synthetic values only. Every subject and condition in the source is licensed wording, so
the fixtures here invent their own.
"""

from __future__ import annotations

import pytest

from insulation_coordination.domain.rules import (
    MAX_PROCEDURE_STEP_LENGTH,
    MAX_REFERENCE_TEXT_LENGTH,
    DecisionRule,
    ProcedureRule,
    SourceReference,
)
from insulation_coordination.rules.importer.axis_selectors import ConfirmedAxes
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    PARTIAL_DISCHARGE_FIELD_ROWS,
    TABLE_30,
    ProcedureStructureError,
    project_partial_discharge,
)

SOURCE = SourceReference(
    document_id="iec62477-1-2022",
    standard="SYNTHETIC",
    edition="1",
    page=1,
    table="S30",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="0" * 64,
    page_count=1,
    recipe_id="iec62477-1-2022",
)


def _synthetic_grid(*, undeclared_row: bool = False, condition_length: int = 0) -> RawGrid:
    segment = TABLE_30.segments[0]
    cells: list[RawGridCell] = []
    for row in range(TABLE_30.expected_raw_rows):
        for column in range(TABLE_30.expected_raw_columns):
            if row in segment.header_rows:
                text, role = f"synthetic header {column}", "header"
            elif undeclared_row and row == segment.data_rows[-1]:
                text = "undeclared subject" if column == 0 else ""
                role = "note"
            elif column == 0:
                text, role = f"synthetic subject {row}", "note"
            else:
                text = f"synthetic condition {row}"
                if condition_length:
                    text = " ".join([text] * condition_length)[:condition_length]
                role = "note"
            cells.append(
                RawGridCell(
                    row=row,
                    column=column,
                    raw_text=text,
                    role=role,  # type: ignore[arg-type]
                    parse_status="text" if text else "blank",
                    source=SOURCE.model_copy(
                        update={
                            "row": f"grid row {row + 1}",
                            "column": f"grid column {column + 1}",
                        }
                    ),
                )
            )
    return RawGrid(
        id=f"raw-{ids.TEST_PARTIAL_DISCHARGE}",
        rows=TABLE_30.expected_raw_rows,
        columns=TABLE_30.expected_raw_columns,
        target_unit="1",
        segments=(
            RawGridSegment(
                page_number=1,
                row_start=0,
                row_count=TABLE_30.expected_raw_rows,
                source=SOURCE,
            ),
        ),
        cells=tuple(cells),
        source=SOURCE,
    )


def test_the_spec_declares_the_measured_shape() -> None:
    segment = TABLE_30.segments[0]
    assert (TABLE_30.expected_raw_rows, TABLE_30.expected_raw_columns) == (13, 2)
    assert segment.header_rows == (0,)
    assert segment.data_rows == tuple(range(1, 12))
    assert segment.note_rows == (12,)
    assert TABLE_30.page_number == 131
    assert TABLE_30.expected_data_rows == 11
    assert TABLE_30.text_field_table is True


def test_every_data_row_feeds_exactly_one_declared_field() -> None:
    rows = [row for row, _field in PARTIAL_DISCHARGE_FIELD_ROWS]
    assert len(rows) == len(set(rows))
    assert set(rows) == set(TABLE_30.segments[0].data_rows)


def test_field_names_are_author_written_not_source_wording() -> None:
    for _row, field in PARTIAL_DISCHARGE_FIELD_ROWS:
        assert field == field.lower()
        assert field.replace("_", "").isalnum()


def test_the_declared_route_is_on_the_spec() -> None:
    assert TABLE_30.decision_route_ids == (f"{ids.TEST_PARTIAL_DISCHARGE}.applicability",)


def test_applicability_is_a_separate_rule_from_the_procedure() -> None:
    rules, proposals = project_partial_discharge(_synthetic_grid(), IDENTITY, ConfirmedAxes())
    assert {type(rule).__name__ for rule in rules} == {"ProcedureRule", "DecisionRule"}
    assert {rule.id for rule in rules} == {
        ids.TEST_PARTIAL_DISCHARGE,
        f"{ids.TEST_PARTIAL_DISCHARGE}.applicability",
    }
    assert {proposal.rule_kind for proposal in proposals} == {"procedure", "decision"}
    assert len(proposals) == len(rules) == 2


def test_the_procedure_carries_every_declared_row() -> None:
    rules, _proposals = project_partial_discharge(_synthetic_grid(), IDENTITY, ConfirmedAxes())
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert [step.order for step in procedure.procedure_steps] == list(
        range(1, len(procedure.procedure_steps) + 1)
    )
    assert [step.order for step in procedure.preparation_steps] == list(
        range(1, len(procedure.preparation_steps) + 1)
    )
    assert (
        len(procedure.procedure_steps) + len(procedure.preparation_steps)
        == len(PARTIAL_DISCHARGE_FIELD_ROWS) - 2
    )
    for step in (*procedure.procedure_steps, *procedure.preparation_steps):
        assert step.source.row is not None
        assert step.source.table == "30"


def test_one_declared_condition_yields_exactly_one_step() -> None:
    """One source condition is one action, so no row may spread over several steps."""

    rules, _proposals = project_partial_discharge(_synthetic_grid(), IDENTITY, ConfirmedAxes())
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    steps = (*procedure.preparation_steps, *procedure.procedure_steps)
    rows = [step.source.row for step in steps]
    assert len(rows) == len(set(rows))
    assert len(rows) == len(PARTIAL_DISCHARGE_FIELD_ROWS) - 2


def test_a_condition_longer_than_the_reference_cap_is_still_one_step() -> None:
    """The longest source condition runs past ``MAX_REFERENCE_TEXT_LENGTH``.

    ``ProcedureStep.text`` therefore carries its own larger cap. Were it back on the
    reference cap, this projection would have to split or truncate the condition.
    """

    long_enough = MAX_REFERENCE_TEXT_LENGTH + 100
    rules, _proposals = project_partial_discharge(
        _synthetic_grid(condition_length=long_enough), IDENTITY, ConfirmedAxes()
    )
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    steps = (*procedure.preparation_steps, *procedure.procedure_steps)
    assert len(steps) == len(PARTIAL_DISCHARGE_FIELD_ROWS) - 2
    assert all(len(step.text) > MAX_REFERENCE_TEXT_LENGTH for step in steps)
    assert MAX_PROCEDURE_STEP_LENGTH > MAX_REFERENCE_TEXT_LENGTH


def test_the_procedure_points_at_its_applicability_rule() -> None:
    rules, _proposals = project_partial_discharge(_synthetic_grid(), IDENTITY, ConfirmedAxes())
    procedure = next(rule for rule in rules if isinstance(rule, ProcedureRule))
    assert procedure.applicability_rule_id == f"{ids.TEST_PARTIAL_DISCHARGE}.applicability"
    assert procedure.test_kind == "partial_discharge"


def test_a_missing_engineering_input_is_not_reported_as_not_required() -> None:
    rules, _proposals = project_partial_discharge(_synthetic_grid(), IDENTITY, ConfirmedAxes())
    decision = next(rule for rule in rules if isinstance(rule, DecisionRule))
    outcomes = {
        value.categorical
        for row in decision.rows
        for value in row.values
        if value.categorical is not None
    }
    assert "engineering_input_required" in outcomes
    assert "not_required" not in outcomes
    assert decision.exhaustive is False


def test_a_grid_with_an_undeclared_subject_row_blocks() -> None:
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_partial_discharge(_synthetic_grid(undeclared_row=True), IDENTITY, ConfirmedAxes())


def test_a_grid_of_the_wrong_shape_blocks() -> None:
    grid = _synthetic_grid()
    narrower = grid.model_copy(
        update={
            "columns": grid.columns - 1,
            "cells": tuple(cell for cell in grid.cells if cell.column == 0),
        }
    )
    with pytest.raises(ProcedureStructureError, match="AMBIGUOUS_PROCEDURE_STRUCTURE"):
        project_partial_discharge(narrower, IDENTITY, ConfirmedAxes())


def test_a_foreign_grid_is_refused() -> None:
    grid = _synthetic_grid()
    with pytest.raises(ValueError, match="requires its own grid"):
        project_partial_discharge(
            grid.model_copy(update={"id": "raw-other"}), IDENTITY, ConfirmedAxes()
        )
