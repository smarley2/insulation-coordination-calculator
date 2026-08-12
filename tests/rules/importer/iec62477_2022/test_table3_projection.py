from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from insulation_coordination.domain.rules import ApprovalRecord, DecisionRule, SourceReference
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import approval_blockers, record_correction
from insulation_coordination.rules.importer.axis_selectors import (
    ConfirmedAxes,
    ProtectionTargetSelector,
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
    propose_axis_selectors,
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
    resolve_confirmed_axis_selectors,
    review_axis_selector,
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
#: Header text at each data row's column 0, carrying the row axis grammar's keywords. The
#: pairing is deranged against the licensed table -- no physical row carries the designation
#: the source assigns it -- and must not be read as its row layout. Three positions admit no
#: derangement that is not also a rotation, so this one stays as it is: with the column maps
#: below no longer sharing its structure, it yields nothing about them.
_ROW_HEADER_TEXT = {3: "DVC C", 4: "DVC AS", 6: "DVC B"}

EXPECTED_PROTECTION_TARGET_SELECTORS = {
    ("accessible_part", "connected_to_pe", "not_applicable", "not_applicable", "not_applicable"),
    (
        "accessible_part",
        "not_connected_to_pe",
        "general_access",
        "ordinary_or_skilled",
        "not_applicable",
    ),
    (
        "accessible_part",
        "not_connected_to_pe",
        "service_or_restricted_access",
        "skilled_only",
        "not_applicable",
    ),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_as"),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_b"),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_c"),
}
#: A canonical sorted order over the six published selectors, derived from the set above and
#: unrelated to the source's own order. Which physical column receives which selector is
#: exactly what ``_selector_index`` below deliberately varies between the two projections
#: under test -- neither its straight nor its reordered mapping may be read as the licensed
#: table's column layout.
_SELECTOR_ORDER = tuple(
    ProtectionTargetSelector(
        target=target,
        pe_relationship=pe_relationship,
        access_context=access_context,
        person_scope=person_scope,
        adjacent_dvc=adjacent_dvc,
    )
    for target, pe_relationship, access_context, person_scope, adjacent_dvc in sorted(
        EXPECTED_PROTECTION_TARGET_SELECTORS
    )
)


#: Which member of ``_SELECTOR_ORDER`` each physical column 1..6 carries in the straight
#: projection. Deranged against the licensed column layout and deliberately not that layout
#: displaced by a fixed step, so one recovered pairing yields nothing about the other five.
_STRAIGHT_SELECTOR_INDEXES = (5, 0, 3, 4, 1, 2)


def _selector_index(column: int, *, reorder_columns: bool) -> int:
    """Which of the six selectors physical ``column`` (1..6) carries.

    Both branches are invented assignments over ``_SELECTOR_ORDER`` -- one so the reordering
    test can reassign selectors to different columns, both deranged against the licensed
    column layout, and neither may be read as it.
    """

    return (6 - column) % 6 if reorder_columns else _STRAIGHT_SELECTOR_INDEXES[column - 1]


def _outcome(row: int, column: int, *, reorder_columns: bool) -> str:
    row_index = DATA_ROWS.index(row)
    return OUTCOMES[
        (row_index + _selector_index(column, reorder_columns=reorder_columns)) % len(OUTCOMES)
    ]


def _cell(row: int, column: int, *, reorder_columns: bool = False) -> RawGridCell:
    source = SOURCE.model_copy(
        update={"row": f"grid row {row + 1}", "column": f"grid column {column + 1}"}
    )
    if row in DATA_ROWS and column in DATA_COLUMNS:
        logical_row = DATA_ROWS.index(row)
        return RawGridCell(
            row=row,
            column=column,
            raw_text=_outcome(row, column, reorder_columns=reorder_columns),
            role="data",
            logical_row=logical_row,
            logical_column=f"protection-context-{column}",
            parse_status="non_scalar",
            source=source,
        )
    if row in DATA_ROWS and column == 0:
        raw_text, role = _ROW_HEADER_TEXT[row], "note"
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


def _grid(*, reorder_columns: bool = False) -> RawGrid:
    return RawGrid(
        id=f"raw-{ids.DVC_PROTECTION_MATRIX}",
        rows=9,
        columns=7,
        target_unit="1",
        segments=(RawGridSegment(page_number=45, row_start=0, row_count=9, source=SOURCE),),
        cells=tuple(
            _cell(row, column, reorder_columns=reorder_columns)
            for row in range(9)
            for column in range(7)
        ),
        source=SOURCE,
    )


def _confirmed_axes(grid: RawGrid, *, reorder_columns: bool = False) -> ConfirmedAxes:
    """Propose, review and resolve every Table 3 axis position for a synthetic grid.

    The row axis proposes from header keywords, mirroring Table 2's lifecycle. The column
    axis is reviewer-supplied by contract (no public grammar exists for it), so this records
    one exact review per physical column itself, choosing an assignment of the six published
    selectors from ``_SELECTOR_ORDER``. The projector under test never inspects review state
    itself -- it only ever consumes the ``ConfirmedAxes`` this builds.
    """

    proposals = propose_axis_selectors(TABLE_3, grid)
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
        raw_grids=(grid,),
        source_identities=(IDENTITY,),
        axis_selector_proposals=proposals,
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        raw_grids=draft.raw_grids,
        source_documents=draft.manifest.source_documents,
        source_identities=draft.source_identities,
        axis_selector_proposals=draft.axis_selector_proposals,
    )
    record = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    draft = draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (record,)})}
    )
    for proposal in proposals:
        if proposal.axis == "row":
            assert proposal.selector is not None, "every synthetic row position proposes a reading"
            selector = proposal.selector
        else:
            selector = _SELECTOR_ORDER[
                _selector_index(proposal.index, reorder_columns=reorder_columns)
            ]
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=selector,
            actor="Synthetic Axis Reviewer",
            notes="Confirmed the synthetic axis reading.",
        )
    return resolve_confirmed_axis_selectors(TABLE_3, grid, draft)


def _project(*, reorder_columns: bool = False) -> tuple[tuple[DecisionRule, ...], ConfirmedAxes]:
    """Build a synthetic grid, review its axes, and project Table 3's decisions."""

    grid = _grid(reorder_columns=reorder_columns)
    axes = _confirmed_axes(grid, reorder_columns=reorder_columns)
    rules, _ = project_dvc_protection_matrix(grid, IDENTITY, axes)
    return rules, axes


def test_the_six_reviewed_protection_targets_are_the_contract() -> None:
    """An unordered set: which physical column produced which selector stays private."""

    _rules, confirmed = _project()
    selectors = {
        (
            item.target,
            item.pe_relationship,
            item.access_context,
            item.person_scope,
            item.adjacent_dvc,
        )
        for item in confirmed.columns.values()
    }

    assert selectors == EXPECTED_PROTECTION_TARGET_SELECTORS


def test_no_positional_identifier_reaches_the_runtime_contract() -> None:
    rules, _ = _project()

    for rule in rules:
        for declared in rule.inputs:
            for value in declared.allowed_values:
                assert not re.fullmatch(r"dvc-\d+|protection-context-\d+", value)
        for row in rule.rows:
            for matcher in row.matchers:
                for value in matcher.values:
                    assert not re.fullmatch(r"dvc-\d+|protection-context-\d+", str(value))


def test_the_declared_inputs_are_the_semantic_dimensions() -> None:
    rules, _ = _project()

    assert {item.name for item in rules[0].inputs} == {
        "dvc",
        "target",
        "pe_relationship",
        "access_context",
        "person_scope",
        "adjacent_dvc",
    }


def test_an_adjacent_circuit_column_evaluates_with_its_not_applicable_dimensions() -> None:
    rules, _ = _project()

    result = evaluate_decision(
        rules[0],
        {
            "dvc": "dvc_b",
            "target": "adjacent_circuit",
            "pe_relationship": "not_applicable",
            "access_context": "not_applicable",
            "person_scope": "not_applicable",
            "adjacent_dvc": "dvc_c",
        },
    )

    assert result.status == "matched"
    assert result.values[0].categorical == "basic_protection"


def test_a_reordered_grid_projects_the_same_semantics() -> None:
    straight, _ = _project()
    reordered, _ = _project(reorder_columns=True)

    def semantics(rules):
        return {
            (
                rule.id,
                tuple(sorted((m.input, tuple(map(str, m.values))) for m in row.matchers)),
                tuple(value.categorical for value in row.values),
            )
            for rule in rules
            for row in rule.rows
        }

    assert semantics(reordered) == semantics(straight)


def test_projection_emits_one_categorical_matrix_rule() -> None:
    rules, _ = _project()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.id == ids.DVC_PROTECTION_MATRIX
    assert not rule.exhaustive
    assert len(rule.rows) == 18
    assert rule.outputs[0].name == "protection_requirement"
    assert rule.outputs[0].kind == "categorical"
    assert rule.outputs[0].allowed_values == TYPED_OUTCOMES


def test_the_rule_carries_one_row_per_reviewed_combination() -> None:
    """Exhaustive coverage of the declared vocabularies is impossible under the structured
    contract, so the guarantee that replaces it is coverage of every reviewed combination.
    """
    rules, axes = _project()
    rule = rules[0]

    assert len(rule.rows) == len(axes.rows) * len(axes.columns)
    matcher_sets = {
        tuple(sorted((matcher.input, tuple(matcher.values)) for matcher in row.matchers))
        for row in rule.rows
    }
    assert len(matcher_sets) == len(rule.rows), "two rows share one matcher combination"


def test_a_combination_no_reviewed_column_states_is_no_match_not_an_error() -> None:
    """A non-exhaustive rule answers no_match instead of raising, which consumers must handle.

    The structured dimensions can be combined in ways no reviewed column carries; that is a
    question the source does not answer, and the rule says so rather than guessing.
    """
    rules, _axes = _project()

    result = evaluate_decision(
        rules[0],
        {
            "dvc": "dvc_b",
            "target": "adjacent_circuit",
            "pe_relationship": "connected_to_pe",
            "access_context": "general_access",
            "person_scope": "skilled_only",
            "adjacent_dvc": "dvc_as",
        },
    )

    assert result.status == "no_match"


def test_every_source_combination_evaluates_to_its_reviewed_category() -> None:
    rules, axes = _project()
    rule = rules[0]
    row_designation = {index: selector.designation for index, selector in axes.rows.items()}
    column_selector = axes.columns
    for row in DATA_ROWS:
        for column in DATA_COLUMNS:
            target = column_selector[column]
            result = evaluate_decision(
                rule,
                {
                    "dvc": row_designation[row],
                    "target": target.target,
                    "pe_relationship": target.pe_relationship,
                    "access_context": target.access_context,
                    "person_scope": target.person_scope,
                    "adjacent_dvc": target.adjacent_dvc,
                },
            )
            expected = TYPED_OUTCOMES[OUTCOMES.index(_outcome(row, column, reorder_columns=False))]
            assert result.values[0].categorical == expected


def test_rows_carry_exact_cell_provenance() -> None:
    rules, _ = _project()
    rule = rules[0]
    assert {(row.source.row, row.source.column) for row in rule.rows} == {
        (f"grid row {row + 1}", f"grid column {column + 1}")
        for row in DATA_ROWS
        for column in DATA_COLUMNS
    }


def test_unknown_or_numeric_outcome_blocks_projection() -> None:
    grid = _grid()
    axes = _confirmed_axes(grid)
    unknown = tuple(
        cell.model_copy(update={"raw_text": "maybe"}) if (cell.row, cell.column) == (3, 1) else cell
        for cell in grid.cells
    )
    with pytest.raises(ValueError, match="unknown categorical token"):
        project_dvc_protection_matrix(grid.model_copy(update={"cells": unknown}), IDENTITY, axes)

    numeric = tuple(
        cell.model_copy(update={"value": 1, "parse_status": "numeric"})
        if (cell.row, cell.column) == (3, 1)
        else cell
        for cell in grid.cells
    )
    with pytest.raises(ValueError, match="unknown categorical token"):
        project_dvc_protection_matrix(grid.model_copy(update={"cells": numeric}), IDENTITY, axes)


def test_missing_cell_and_wrong_identity_block_projection() -> None:
    grid = _grid()
    axes = _confirmed_axes(grid)
    with pytest.raises(ValueError, match="missing physical cell"):
        project_dvc_protection_matrix(
            grid.model_copy(update={"cells": grid.cells[:-1]}), IDENTITY, axes
        )
    with pytest.raises(ValueError, match="protection matrix"):
        project_dvc_protection_matrix(grid.model_copy(update={"id": "raw-other"}), IDENTITY, axes)


def _logged_table3_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    grid = apply_table_structure(_grid(), TABLE_3)
    axis_proposals = propose_axis_selectors(TABLE_3, grid)
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
        axis_selector_proposals=axis_proposals,
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
        axis_selector_proposals=draft.axis_selector_proposals,
    )
    extraction = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    draft = draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (extraction,)})}
    )
    for proposal in axis_proposals:
        if proposal.axis == "row":
            assert proposal.selector is not None, "every synthetic row position proposes a reading"
            selector = proposal.selector
        else:
            selector = _SELECTOR_ORDER[_selector_index(proposal.index, reorder_columns=False)]
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=selector,
            actor="Synthetic Axis Reviewer",
            notes="Confirmed the synthetic axis reading.",
        )
    return draft


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
