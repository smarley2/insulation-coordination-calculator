from __future__ import annotations

from datetime import UTC, datetime

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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
    project_dvc_protection_matrix,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_3
from insulation_coordination.rules.importer.review import (
    build_reviewed_draft,
    mark_proposal_reviewed,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-table-3",
    standard="SYNTHETIC",
    edition="1",
    page=45,
    table="S3",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="3" * 64,
    page_count=45,
    recipe_id="synthetic-table-3",
)
DATA_ROWS = range(2, 9)
DATA_COLUMNS = range(2, 7)


def synthetic_identity() -> StandardIdentity:
    return IDENTITY


def _token(row: int, column: int) -> str:
    # One unique token per DVC row (a per-row column) so every projected row is
    # load-bearing for exhaustive coverage; the rest alternate.
    if column == 2 + ((row - 2) % 5):
        return "yes"
    return "no" if (row + column) % 2 else "yes"


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
    return RawGridCell(
        row=row,
        column=column,
        raw_text=_token(row, column),
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


def test_projection_emits_boolean_matchers_exhaustive_coverage_and_proposals() -> None:
    rules, proposals = project_dvc_protection_matrix(_grid(), synthetic_identity())
    boolean_match_values = {
        matcher.boolean
        for rule in rules
        for row in rule.rows
        for matcher in row.matchers
        if matcher.boolean is not None
    }
    assert boolean_match_values == {False, True}
    assert {proposal.semantic_id for proposal in proposals} == {rule.id for rule in rules}


def test_projection_mixes_categorical_axes_boolean_inputs_and_typed_outputs() -> None:
    rules, _ = project_dvc_protection_matrix(_grid(), synthetic_identity())
    assert all(
        any(item.name == "dvc" and item.kind == "categorical" for item in rule.inputs)
        and any(item.kind == "boolean" for item in rule.inputs)
        for rule in rules
    )
    assert all(rule.exhaustive for rule in rules)
    assert all(output.kind == "boolean" for rule in rules for output in rule.outputs)
    assert all(
        value.boolean is not None for rule in rules for row in rule.rows for value in row.values
    )


def test_projection_rows_carry_source_row_and_column_provenance() -> None:
    rules, _ = project_dvc_protection_matrix(_grid(), synthetic_identity())

    assert all(
        row.source.page is not None
        and row.source.table is not None
        and row.source.row is not None
        and row.source.column is not None
        for rule in rules
        for row in rule.rows
    )


def test_projection_rules_evaluate_the_reviewed_boolean_tokens() -> None:
    rules, _ = project_dvc_protection_matrix(_grid(), synthetic_identity())
    for rule in rules:
        boolean_inputs = tuple(item.name for item in rule.inputs if item.kind == "boolean")
        assert len(boolean_inputs) == 1
        for row in rule.rows:
            assignment: dict[str, str | bool] = {}
            for matcher in row.matchers:
                if matcher.boolean is not None:
                    assignment[matcher.input] = matcher.boolean
                else:
                    assignment[matcher.input] = matcher.values[0]
            result = evaluate_decision(rule, assignment)
            expected = {value.name: value.boolean for value in row.values}
            assert {value.name: value.boolean for value in result.values} == expected


def test_deleting_one_boolean_row_fails_exhaustive_rule_validation() -> None:
    from insulation_coordination.domain.rules import DecisionRule

    rules, _ = project_dvc_protection_matrix(_grid(), synthetic_identity())
    rule = rules[0]
    removed_any = False
    for candidate in rule.rows:
        broken = tuple(row for row in rule.rows if row is not candidate)
        try:
            DecisionRule(
                id=rule.id,
                inputs=rule.inputs,
                outputs=rule.outputs,
                rows=broken,
                exhaustive=True,
                source=rule.source,
            )
        except ValueError as error:
            assert "exhaustive" in str(error)
            removed_any = True
            break
    assert removed_any, "no single row deletion broke exhaustive coverage"


def test_unknown_boolean_token_blocks_projection() -> None:
    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "maybe"}) if (cell.row, cell.column) == (2, 2) else cell
        for cell in grid.cells
    )

    with pytest.raises(ValueError, match="unknown boolean token"):
        project_dvc_protection_matrix(
            grid.model_copy(update={"cells": cells}), synthetic_identity()
        )


def test_numeric_content_in_a_boolean_cell_blocks_projection() -> None:
    from decimal import Decimal

    grid = _grid()
    cells = tuple(
        cell.model_copy(update={"raw_text": "42", "value": Decimal(42), "parse_status": "numeric"})
        if (cell.row, cell.column) == (2, 2)
        else cell
        for cell in grid.cells
    )

    with pytest.raises(ValueError, match="unknown boolean token"):
        project_dvc_protection_matrix(
            grid.model_copy(update={"cells": cells}), synthetic_identity()
        )


def test_incomplete_cartesian_coverage_blocks_projection() -> None:
    grid = _grid()
    cells = tuple(cell for cell in grid.cells if (cell.row, cell.column) != (8, 6))

    with pytest.raises(ValueError, match="missing physical cell|coverage"):
        project_dvc_protection_matrix(
            grid.model_copy(update={"cells": cells}), synthetic_identity()
        )


def test_wrong_grid_identity_blocks_projection() -> None:
    grid = _grid().model_copy(update={"id": "raw-other-table"})

    with pytest.raises(ValueError, match="protection matrix"):
        project_dvc_protection_matrix(grid, synthetic_identity())


def _logged_table3_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    grid = apply_table_structure(_grid(), TABLE_3)
    review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_3_REVIEW",
        semantic_id=ids.DVC_PROTECTION_MATRIX,
        kind="table",
        source=SOURCE,
        expected_contract="synthetic structural Table 3 review",
    )
    derived_review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_3_DERIVED_REVIEW",
        semantic_id=f"{ids.DVC_PROTECTION_MATRIX}.applicable",
        kind="table",
        source=SOURCE,
        expected_contract="synthetic derived Table 3 review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic Table 3 source artifact.",
    )
    derived_resolution = ImportReviewResolution(
        review_item_sha256=derived_review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic derived Table 3 rule.",
    )
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "tables": (TABLE_3,),
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
        review_items=(review_item, derived_review_item),
        review_resolutions=(resolution, derived_resolution),
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
        _logged_table3_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 3 decisions.",
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
        cell.model_copy(update={"parse_status": "non_scalar"})
        if (cell.row, cell.column) == (2, 2)
        else cell
        for cell in grid.cells
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(update={"raw_grids": (grid.model_copy(update={"cells": cells}),)}),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic boolean token.",
    )

    assert all(proposal.state == "proposed" for proposal in corrected.semantic_proposals)
    assert {blocker.code for blocker in approval_blockers(corrected)} >= {
        "SEMANTIC_PROPOSAL_PROPOSED"
    }


def test_unrelated_prefixed_decision_cannot_borrow_table3_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table3_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 3 decisions.",
    )
    unrelated = built.decisions[0].model_copy(
        update={"id": f"{ids.DVC_PROTECTION_MATRIX}.unrelated"}
    )

    with pytest.raises(ApprovalError, match="review item inventory"):
        record_correction(
            built,
            built.model_copy(update={"decisions": (*built.decisions, unrelated)}),
            actor="Synthetic Rule Builder",
            notes="Attempt an unrelated prefixed decision.",
        )
