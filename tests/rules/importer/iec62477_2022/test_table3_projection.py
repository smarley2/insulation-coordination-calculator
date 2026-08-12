from __future__ import annotations

from datetime import UTC, datetime

import pytest

from insulation_coordination.domain.rules import ApprovalRecord, DecisionRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import approval_blockers, record_correction
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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import RECIPE as IEC_RECIPE
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
DATA_ROWS = (3, 4, 6)
DATA_COLUMNS = range(1, 7)
OUTCOMES = ("none", "basic protection", "enhanced protection")
TYPED_OUTCOMES = ("none", "basic_protection", "enhanced_protection")


def _outcome(row: int, column: int) -> str:
    return OUTCOMES[(DATA_ROWS.index(row) + column) % len(OUTCOMES)]


def _cell(row: int, column: int) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if row in DATA_ROWS and column in DATA_COLUMNS:
        logical_row = DATA_ROWS.index(row)
        return RawGridCell(
            row=row,
            column=column,
            raw_text=_outcome(row, column),
            role="data",
            logical_row=logical_row,
            logical_column=f"protection-context-{column}",
            parse_status="non_scalar",
            source=source,
        )
    if row in DATA_ROWS and column == 0:
        raw_text, role = f"DVC {DATA_ROWS.index(row) + 1}", "note"
    elif (row, column) in {(5, 4), (7, 5)}:
        raw_text, role = "source continuation", "note"
    elif row == 8 and column == 0:
        raw_text, role = "source notes", "footnote"
    elif row <= 2:
        raw_text, role = f"HEADER_{row}_{column}", "header"
    else:
        raw_text, role = "", "blank"
    return RawGridCell(
        row=row,
        column=column,
        raw_text=raw_text,
        role=role,
        parse_status="blank" if not raw_text else "text",
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


def test_projection_emits_one_exhaustive_categorical_matrix() -> None:
    rules, proposals = project_dvc_protection_matrix(_grid(), IDENTITY)
    assert len(rules) == len(proposals) == 1
    rule = rules[0]
    assert rule.id == ids.DVC_PROTECTION_MATRIX
    assert rule.exhaustive
    assert len(rule.rows) == 18
    assert [(item.name, item.kind, len(item.allowed_values)) for item in rule.inputs] == [
        ("dvc", "categorical", 3),
        ("protection_context", "categorical", 6),
    ]
    assert rule.outputs[0].name == "protection_requirement"
    assert rule.outputs[0].kind == "categorical"
    assert rule.outputs[0].allowed_values == TYPED_OUTCOMES
    assert proposals[0].semantic_id == rule.id


def test_every_source_combination_evaluates_to_its_reviewed_category() -> None:
    rule = project_dvc_protection_matrix(_grid(), IDENTITY)[0][0]
    for logical_row, physical_row in enumerate(DATA_ROWS, start=1):
        for column in DATA_COLUMNS:
            result = evaluate_decision(
                rule,
                {"dvc": f"dvc-{logical_row}", "protection_context": f"protection-context-{column}"},
            )
            expected = TYPED_OUTCOMES[OUTCOMES.index(_outcome(physical_row, column))]
            assert result.values[0].categorical == expected


def test_rows_carry_exact_cell_provenance() -> None:
    rule = project_dvc_protection_matrix(_grid(), IDENTITY)[0][0]
    assert {(row.source.row, row.source.column) for row in rule.rows} == {
        (f"grid row {row + 1}", f"grid column {column + 1}")
        for row in DATA_ROWS
        for column in DATA_COLUMNS
    }


def test_unknown_or_numeric_outcome_blocks_projection() -> None:
    grid = _grid()
    unknown = tuple(
        cell.model_copy(update={"raw_text": "maybe"}) if (cell.row, cell.column) == (3, 1) else cell
        for cell in grid.cells
    )
    with pytest.raises(ValueError, match="unknown categorical token"):
        project_dvc_protection_matrix(grid.model_copy(update={"cells": unknown}), IDENTITY)

    numeric = tuple(
        cell.model_copy(update={"value": 1, "parse_status": "numeric"})
        if (cell.row, cell.column) == (3, 1)
        else cell
        for cell in grid.cells
    )
    with pytest.raises(ValueError, match="unknown categorical token"):
        project_dvc_protection_matrix(grid.model_copy(update={"cells": numeric}), IDENTITY)


def test_missing_cell_and_wrong_identity_block_projection() -> None:
    grid = _grid()
    with pytest.raises(ValueError, match="missing physical cell"):
        project_dvc_protection_matrix(grid.model_copy(update={"cells": grid.cells[:-1]}), IDENTITY)
    with pytest.raises(ValueError, match="protection matrix"):
        project_dvc_protection_matrix(grid.model_copy(update={"id": "raw-other"}), IDENTITY)


def test_deleting_one_outcome_breaks_exhaustive_coverage() -> None:
    rule = project_dvc_protection_matrix(_grid(), IDENTITY)[0][0]
    with pytest.raises(ValueError, match="exhaustive"):
        DecisionRule(
            id=rule.id,
            inputs=rule.inputs,
            outputs=rule.outputs,
            rows=rule.rows[:-1],
            exhaustive=True,
            source=rule.source,
        )


def _logged_table3_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    grid = apply_table_structure(_grid(), TABLE_3)
    review_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_3_REVIEW",
        semantic_id=ids.DVC_PROTECTION_MATRIX,
        kind="table",
        source=SOURCE,
        expected_contract="synthetic structural Table 3 review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic Table 3 source artifact.",
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


def test_review_lifecycle_resets_after_authoritative_grid_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_table3_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build Table 3 decision.",
    )
    assert len(built.semantic_proposals) == 1
    reviewed = mark_proposal_reviewed(
        built,
        ids.DVC_PROTECTION_MATRIX,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed the generated decision.",
    )
    grid = reviewed.raw_grids[0]
    cells = tuple(
        cell.model_copy(update={"parse_status": "text"})
        if (cell.row, cell.column) == (3, 1)
        else cell
        for cell in grid.cells
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(update={"raw_grids": (grid.model_copy(update={"cells": cells}),)}),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic category.",
    )
    assert corrected.semantic_proposals[0].state == "proposed"
    assert {blocker.code for blocker in approval_blockers(corrected)} >= {
        "SEMANTIC_PROPOSAL_PROPOSED"
    }
