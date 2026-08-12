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
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    data = row in range(3, 7) and column in range(1, 6)
    not_applicable = (row, column) == (6, 5)
    blank = (
        (row, column) in INHERITED_BLANKS or (row, column) in STRUCTURAL_BLANKS or not_applicable
    )
    reference = (row, column) in REFERENCE_COORDINATES
    text = "NA" if not_applicable else ("" if blank else ("REF" if reference else "HEADER"))
    value = Decimal(row * 100 + column * 7) if data and not blank else None
    if reference:
        value = None
    return RawGridCell(
        row=row,
        column=column,
        raw_text=text if value is None else str(value),
        role="data" if data else ("blank" if blank else "header"),
        logical_row=row - 3 if data else None,
        logical_column=f"column-{column}" if data else None,
        value=value,
        parse_status=(
            "non_scalar"
            if not_applicable
            else ("blank" if blank else ("numeric" if value is not None else "text"))
        ),
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


def test_projection_emits_five_quantities_without_synthetic_inputs() -> None:
    rules, proposals = project_dvc_voltage_limits(_grid(), IDENTITY)
    numeric = next(rule for rule in rules if rule.id == ids.DVC_VOLTAGE_LIMITS)
    assert {item.name for item in numeric.inputs} == {"dvc", "voltage_quantity", "unit"}
    quantity = next(item for item in numeric.inputs if item.name == "voltage_quantity")
    assert len(quantity.allowed_values) == 5
    assert not any(
        matcher.input in {"operating_condition", "conditional_alternative"}
        for row in numeric.rows
        for matcher in row.matchers
    )
    assert all(proposal.state == "proposed" for proposal in proposals)
    assert all(
        row.source.page is not None
        and row.source.table is not None
        and row.source.row is not None
        and row.source.column is not None
        for rule in rules
        for row in rule.rows
    )


def test_curve_reference_rule_targets_only_the_fault_time_curve() -> None:
    rules, _ = project_dvc_voltage_limits(_grid(), IDENTITY)
    rule = next(
        item for item in rules if item.id == f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference"
    )
    assert [output.name for output in rule.outputs] == ["fault_time_voltage"]
    assert {value.reference for row in rule.rows for value in row.values} == {
        ids.DVC_FAULT_TIME_VOLTAGE
    }
    assert all(value.numeric is None for row in rule.rows for value in row.values)


def test_impulse_reference_rule_targets_exact_ac_and_dc_tables() -> None:
    rules, _ = project_dvc_voltage_limits(_grid(), IDENTITY)
    rule = next(item for item in rules if item.id == f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference")
    assert {output.name for output in rule.outputs} == {"ac_reference", "dc_reference"}
    assert all(
        {value.reference for value in row.values}
        == {
            f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
            f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
        }
        for row in rule.rows
    )


def test_numeric_rule_evaluates_a_physical_row_and_quantity_column() -> None:
    numeric = next(
        rule
        for rule in project_dvc_voltage_limits(_grid(), IDENTITY)[0]
        if rule.id == ids.DVC_VOLTAGE_LIMITS
    )
    result = evaluate_decision(
        numeric,
        {
            "dvc": "dvc-1",
            "voltage_quantity": "voltage-quantity-1",
            "unit": "V",
        },
    )
    assert result.values[0].numeric == Decimal(307)


def test_unresolved_neutral_token_blocks_projection() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "UNKNOWN", "value": None, "parse_status": "text"})
        if (cell.row, cell.column) == (3, 1)
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
        draft.raw_clause_fragments,
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
        if (cell.row, cell.column) == (3, 1) and cell.value is not None
        else cell
        for cell in grid.cells
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(update={"raw_grids": (grid.model_copy(update={"cells": cells}),)}),
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
    unrelated = built.decisions[0].model_copy(update={"id": f"{ids.DVC_VOLTAGE_LIMITS}.unrelated"})

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
    broken = TABLE_2.model_copy(update={"reference_slots": (first, *TABLE_2.reference_slots[1:])})
    monkeypatch.setattr(table2_projection, "TABLE_2", broken)

    with pytest.raises(ValueError, match="target kind"):
        project_dvc_voltage_limits(_grid(), IDENTITY)
