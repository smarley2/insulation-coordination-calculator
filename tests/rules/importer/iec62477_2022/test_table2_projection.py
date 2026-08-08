from __future__ import annotations

from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    ImportReviewItem,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    apply_table_structure,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
    project_dvc_voltage_limits,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from insulation_coordination.rules.importer.review import _require_current_proposal
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-table-2",
    standard="SYNTHETIC",
    edition="1",
    page=44,
    table="S2",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="2" * 64,
    page_count=44,
    recipe_id="synthetic-table-2",
)
REFERENCE_TARGETS = {
    (6, 2): ids.DVC_FAULT_TIME_VOLTAGE,
    (6, 3): ids.DVC_FAULT_TIME_VOLTAGE,
    (6, 4): ids.DVC_FAULT_TIME_VOLTAGE,
    (7, 4): f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac",
    (7, 5): f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc",
}
INHERITED_BLANKS = {(1, 0), (0, 2), (0, 3), (0, 4), (0, 5)}


def _cell(row: int, column: int) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if (row, column) == (5, 5):
        return RawGridCell(
            row=row,
            column=column,
            raw_text="",
            role="data",
            logical_row=row - 2,
            logical_column=f"column-{column - 1}",
            parse_status="blank",
            source=source,
        )
    if (row, column) in INHERITED_BLANKS:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="",
            role="blank",
            parse_status="blank",
            source=source,
        )
    if (row, column) in REFERENCE_TARGETS:
        return RawGridCell(
            row=row,
            column=column,
            raw_text="CURVE_REF" if row == 6 else "TOV_REF",
            role="data",
            logical_row=row - 2,
            logical_column=f"column-{column - 1}",
            parse_status="text",
            source=source,
        )
    if row >= 2 and column >= 2:
        value = Decimal(row * 100 + column * 7)
        return RawGridCell(
            row=row,
            column=column,
            raw_text=str(value),
            role="data",
            logical_row=row - 2,
            logical_column=f"column-{column - 1}",
            value=value,
            parse_status="numeric",
            source=source,
        )
    return RawGridCell(
        row=row,
        column=column,
        raw_text=f"HEADER_{row}_{column}",
        role="header",
        parse_status="text",
        source=source,
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


def test_projection_emits_numeric_and_semantic_outcomes_with_provenance() -> None:
    rules, proposals = project_dvc_voltage_limits(_grid(), IDENTITY)
    references = {
        output.reference
        for rule in rules
        for row in rule.rows
        for output in row.values
        if output.reference is not None
    }

    assert ids.DVC_FAULT_TIME_VOLTAGE in references
    assert f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac" in references
    assert f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc" in references
    assert all(proposal.state == "proposed" for proposal in proposals)
    assert any(
        value.numeric is not None for rule in rules for row in rule.rows for value in row.values
    )
    assert all(
        row.source.page is not None
        and row.source.table is not None
        and row.source.row is not None
        and row.source.column is not None
        for rule in rules
        for row in rule.rows
    )


def test_figure_reference_never_copies_a_curve_value() -> None:
    rules, _ = project_dvc_voltage_limits(_grid(), IDENTITY)
    curve_rows = [
        row
        for rule in rules
        for row in rule.rows
        if any(value.reference == ids.DVC_FAULT_TIME_VOLTAGE for value in row.values)
    ]

    assert curve_rows
    assert all(value.numeric is None for row in curve_rows for value in row.values)


def test_conditional_alternatives_use_boolean_matchers_and_evaluate_differently() -> None:
    rules, _ = project_dvc_voltage_limits(_grid(), IDENTITY)
    numeric = next(rule for rule in rules if rule.id == ids.DVC_VOLTAGE_LIMITS)
    conditional = next(item for item in numeric.inputs if item.name == "conditional_alternative")
    assert conditional.kind == "boolean"
    assert all(
        matcher.boolean is not None and not matcher.values
        for row in numeric.rows
        for matcher in row.matchers
        if matcher.input == "conditional_alternative"
    )

    common = {
        "dvc": "dvc-row-3",
        "operating_condition": "condition-row-3",
        "voltage_quantity": "quantity-1",
        "unit": "V",
    }
    false_result = evaluate_decision(numeric, {**common, "conditional_alternative": False})
    true_result = evaluate_decision(numeric, {**common, "conditional_alternative": True})
    assert false_result.values[0].numeric != true_result.values[0].numeric


def test_unresolved_neutral_token_blocks_projection() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "UNKNOWN", "value": None, "parse_status": "text"})
        if (cell.row, cell.column) == (2, 2)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ValueError, match="unresolved outcome"):
        project_dvc_voltage_limits(grid.model_copy(update={"cells": cells}), IDENTITY)


def test_every_projected_decision_is_grounded_by_the_table_grid_review_inventory() -> None:
    grid = apply_table_structure(_grid(), TABLE_2)
    rules, proposals = project_dvc_voltage_limits(grid, IDENTITY)
    review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_2_REVIEW",
        semantic_id=ids.DVC_VOLTAGE_LIMITS,
        kind="table",
        source=SOURCE,
        expected_contract="synthetic structural Table 2 review",
    )
    proposals = tuple(
        proposal.model_copy(update={"review_item_sha256s": (review_item.sha256,)})
        for proposal in proposals
    )
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={"approved": False, "compatible": False, "approval_records": ()}
        ),
        tables=(),
        formulas=(),
        mappings=(),
        decisions=rules,
        review_items=(review_item,),
        raw_grids=(grid,),
        semantic_proposals=proposals,
        source_identities=(),
    )

    for proposal in proposals:
        _require_current_proposal(draft, proposal, require_resolved_members=False)
