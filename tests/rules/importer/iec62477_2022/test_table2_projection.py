from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import ApprovalRecord, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    _content_digest,
    apply_table_structure,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    projection as table2_projection,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
    project_dvc_voltage_limits,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from insulation_coordination.rules.importer.review import (
    build_reviewed_draft,
    mark_proposal_reviewed,
)
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


def _logged_table2_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    grid = apply_table_structure(_grid(), TABLE_2)
    review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_2_REVIEW",
        semantic_id=ids.DVC_VOLTAGE_LIMITS,
        kind="table",
        source=SOURCE,
        expected_contract="synthetic structural Table 2 review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic Table 2 source artifact.",
    )
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "tables": (TABLE_2,),
            "formulas": (),
            "mappings": (),
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        review_items=(review_item,),
        review_resolutions=(resolution,),
        raw_grids=(grid,),
        source_identities=(IDENTITY,),
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        draft.review_items,
        draft.raw_grids,
        draft.manifest.source_documents,
        draft.source_identities,
        draft.review_resolutions,
    )
    extraction = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (extraction,)})}
    )


def test_build_and_review_lifecycle_resets_after_authoritative_grid_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table2_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 2 decisions.",
    )
    assert built.semantic_proposals
    assert all(proposal.state == "proposed" for proposal in built.semantic_proposals)

    reviewed = built
    for proposal in built.semantic_proposals:
        reviewed = mark_proposal_reviewed(
            reviewed,
            proposal.semantic_id,
            actor="Synthetic Semantic Reviewer",
            notes="Reviewed the generated decision.",
        )
    assert all(proposal.state == "reviewed" for proposal in reviewed.semantic_proposals)

    grid = reviewed.raw_grids[0]
    cells = tuple(
        cell.model_copy(update={"value": cell.value + Decimal(1)})
        if (cell.row, cell.column) == (2, 2) and cell.value is not None
        else cell
        for cell in grid.cells
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(
            update={"raw_grids": (grid.model_copy(update={"cells": cells}),)}
        ),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic source quantity.",
    )

    assert all(proposal.state == "proposed" for proposal in corrected.semantic_proposals)
    assert {blocker.code for blocker in approval_blockers(corrected)} >= {
        "SEMANTIC_PROPOSAL_PROPOSED"
    }


def test_unrelated_prefixed_decision_cannot_borrow_table2_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table2_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 2 decisions.",
    )
    unrelated = built.decisions[0].model_copy(
        update={"id": f"{ids.DVC_VOLTAGE_LIMITS}.unrelated"}
    )

    with pytest.raises(ApprovalError, match="review item inventory"):
        record_correction(
            built,
            built.model_copy(update={"decisions": (*built.decisions, unrelated)}),
            actor="Synthetic Rule Builder",
            notes="Attempt an unrelated prefixed decision.",
        )


def test_reference_target_kind_mismatch_blocks_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = TABLE_2.reference_slots[0].model_copy(update={"target_kind": "table"})
    broken = TABLE_2.model_copy(
        update={"reference_slots": (first, *TABLE_2.reference_slots[1:])}
    )
    monkeypatch.setattr(table2_projection, "TABLE_2", broken)

    with pytest.raises(ValueError, match="target kind"):
        project_dvc_voltage_limits(_grid(), IDENTITY)
