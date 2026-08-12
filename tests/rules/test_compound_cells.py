from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import ApprovalRecord, SourceReference
from insulation_coordination.rules.importer.approval import ApprovalError
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ComponentFormulaCandidate,
    ImportedRuleDraft,
    ImportReviewItem,
    RawGrid,
    RawGridCell,
    RawGridSegment,
    SemanticProposal,
    _content_digest,
    canonical_model_sha256,
    compound_review_items,
    parse_compound_data_cell,
)
from insulation_coordination.rules.importer.identify import CompoundQuantitySpec
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    correct_component_association,
    correct_raw_component,
    mark_proposal_reviewed,
    proposal_for,
    record_correction,
    select_component_formula,
    unresolved_raw_review_items,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package

SYNTHETIC_SOURCE = SourceReference(
    document_id="synthetic-compound",
    standard="SYNTHETIC",
    edition="1",
    page=3,
    table="S7",
    row="grid row 1",
    column="grid column 1",
)


def test_compound_parser_preserves_order_values_and_source() -> None:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 dc",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    assert [(part.component_id, part.value) for part in parsed.components] == [
        ("ac", Decimal(11)),
        ("dc", Decimal(17)),
    ]
    assert all(part.source == SYNTHETIC_SOURCE for part in parsed.components)
    assert [part.raw_text for part in parsed.components] == ["11 ac", "17 dc"]


def test_reversed_compound_labels_keep_their_semantic_association() -> None:
    parsed = parse_compound_data_cell(
        text="17 dc / 11 ac",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    assert [(part.component_id, part.value) for part in parsed.components] == [
        ("dc", Decimal(17)),
        ("ac", Decimal(11)),
    ]


def test_raw_grid_cell_retains_the_complete_compound_source_text() -> None:
    raw_text = "11 ac / 17 dc"
    parsed = parse_compound_data_cell(
        text=raw_text,
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    cell = RawGridCell(
        row=0,
        column=0,
        raw_text=raw_text,
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        formula_candidates=parsed.formula_candidates,
        parse_status=parsed.parse_status,
        source=SYNTHETIC_SOURCE,
    )

    assert cell.raw_text == raw_text
    assert cell.components == parsed.components


def test_missing_compound_label_is_blocking_and_never_assigned_by_position() -> None:
    parsed = parse_compound_data_cell(
        text="11 / 17 dc",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    assert [(part.component_id, part.value) for part in parsed.components] == [
        (None, Decimal(11)),
        ("dc", Decimal(17)),
    ]
    assert parsed.parse_status == "ambiguous_compound"
    assert parsed.review_codes == ("AMBIGUOUS_COMPOUND_CELL",)


def test_duplicated_compound_label_is_blocking() -> None:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 ac",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    assert parsed.parse_status == "ambiguous_compound"
    assert parsed.review_codes == ("AMBIGUOUS_COMPOUND_CELL",)


def test_unknown_compound_label_is_blocking() -> None:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 unrelated",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )

    assert [(part.component_id, part.value) for part in parsed.components] == [
        ("ac", Decimal(11)),
        (None, Decimal(17)),
    ]
    assert parsed.review_codes == ("AMBIGUOUS_COMPOUND_CELL",)


def test_zero_formula_candidates_is_blocking() -> None:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 dc",
        spec=CompoundQuantitySpec(
            component_ids=("ac", "dc"),
            formula_candidates=(("ac", None),),
            allowed_formula_ids=(("ac", "synthetic-route-formula"),),
        ),
        source=SYNTHETIC_SOURCE,
    )

    assert parsed.review_codes == ("AMBIGUOUS_COMPONENT_FORMULA",)


def test_duplicate_association_can_be_relabelled_by_source_occurrence() -> None:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 ac",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )
    cell = RawGridCell(
        row=0,
        column=0,
        raw_text="11 ac / 17 ac",
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        parse_status=parsed.parse_status,
        source=SYNTHETIC_SOURCE,
    )
    grid = _grid_for_cell(cell)
    review_items = compound_review_items(grid)
    draft = _draft_with_compound_cell(cell, review_items)

    corrected = correct_component_association(
        draft,
        grid_id=grid.id,
        row=0,
        column=0,
        source_index=1,
        component_id="dc",
        actor="Synthetic Reviewer",
        notes="Associated the second source occurrence.",
    )

    parts = corrected.raw_grids[0].cells[0].components
    assert [(part.source_index, part.component_id, part.value) for part in parts] == [
        (0, "ac", Decimal(11)),
        (1, "dc", Decimal(17)),
    ]
    assert corrected.raw_grids[0].cells[0].raw_text == "11 ac / 17 ac"
    assert all(part.source == SYNTHETIC_SOURCE for part in parts)
    assert len(corrected.review_resolutions) == len(review_items)
    assert proposal_for(corrected, draft.tables[0].id).state == "proposed"


def test_missing_association_can_be_supplied_by_source_occurrence() -> None:
    parsed = parse_compound_data_cell(
        text="11 / 17 dc",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )
    assert [(part.source_index, part.component_id) for part in parsed.components] == [
        (0, None),
        (1, "dc"),
    ]
    cell = RawGridCell(
        row=0,
        column=0,
        raw_text="11 / 17 dc",
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        parse_status=parsed.parse_status,
        source=SYNTHETIC_SOURCE,
    )
    review_items = compound_review_items(_grid_for_cell(cell))
    draft = _draft_with_compound_cell(cell, review_items)

    corrected = correct_component_association(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        source_index=0,
        component_id="ac",
        actor="Synthetic Reviewer",
        notes="Associated the unlabeled source occurrence.",
    )

    assert [part.component_id for part in corrected.raw_grids[0].cells[0].components] == [
        "ac",
        "dc",
    ]
    assert len(corrected.review_resolutions) == len(review_items)


def _duplicate_formula_route_draft() -> ImportedRuleDraft:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 ac",
        spec=CompoundQuantitySpec(
            component_ids=("ac", "dc"),
            formula_candidates=(("ac", "synthetic-ac-formula"),),
            allowed_formula_ids=(
                ("ac", "synthetic-ac-formula"),
                ("dc", "synthetic-dc-formula"),
            ),
        ),
        source=SYNTHETIC_SOURCE,
    )
    cell = RawGridCell(
        row=0,
        column=0,
        raw_text="11 ac / 17 ac",
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        formula_candidates=parsed.formula_candidates,
        allowed_component_formula_ids=parsed.allowed_component_formula_ids,
        parse_status=parsed.parse_status,
        source=SYNTHETIC_SOURCE,
    )
    review_items = compound_review_items(_grid_for_cell(cell))
    assert [item.code for item in review_items] == [
        "AMBIGUOUS_COMPOUND_CELL",
        "AMBIGUOUS_COMPOUND_CELL",
    ]
    return _draft_with_compound_cell(cell, review_items)


def test_association_change_with_formula_route_requires_atomic_selection() -> None:
    draft = _duplicate_formula_route_draft()

    with pytest.raises(ValueError, match="route-local formula"):
        correct_component_association(
            draft,
            grid_id=draft.raw_grids[0].id,
            row=0,
            column=0,
            source_index=1,
            component_id="dc",
            actor="Synthetic Reviewer",
            notes="Missing the required formula selection.",
        )

    with pytest.raises(ValueError, match="component route"):
        correct_component_association(
            draft,
            grid_id=draft.raw_grids[0].id,
            row=0,
            column=0,
            source_index=1,
            component_id="dc",
            formula_id="synthetic-ac-formula",
            actor="Synthetic Reviewer",
            notes="Reject a formula from the old route.",
        )

    corrected = correct_component_association(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        source_index=1,
        component_id="dc",
        formula_id="synthetic-dc-formula",
        actor="Synthetic Reviewer",
        notes="Associated the occurrence with its exact formula.",
    )

    cell = corrected.raw_grids[0].cells[0]
    assert [part.component_id for part in cell.components] == ["ac", "dc"]
    assert [
        candidate.formula_id for candidate in cell.formula_candidates if candidate.source_index == 1
    ] == ["synthetic-dc-formula"]
    assert unresolved_raw_review_items(corrected) == ()
    assert proposal_for(corrected, draft.tables[0].id).state == "proposed"


def test_batch_association_requires_formula_for_the_same_occurrence() -> None:
    draft = _duplicate_formula_route_draft()
    key = (0, 0, 1)

    with pytest.raises(ValueError, match="route-local formula"):
        accept_raw_table(
            draft,
            grid_id=draft.raw_grids[0].id,
            corrections={},
            component_associations={key: "dc"},
            actor="Synthetic Reviewer",
            notes="Missing atomic formula selection.",
        )

    corrected = accept_raw_table(
        draft,
        grid_id=draft.raw_grids[0].id,
        corrections={},
        component_associations={key: "dc"},
        formula_selections={key: "synthetic-dc-formula"},
        actor="Synthetic Reviewer",
        notes="Applied the exact association and formula pair.",
    )

    assert unresolved_raw_review_items(corrected) == ()
    assert proposal_for(corrected, draft.tables[0].id).state == "proposed"


def test_approval_rejects_corrected_formula_route_without_formula() -> None:
    draft = _duplicate_formula_route_draft()
    grid = draft.raw_grids[0]
    cell = grid.cells[0]
    components = tuple(
        component.model_copy(update={"component_id": "dc"})
        if component.source_index == 1
        else component
        for component in cell.components
    )
    candidates = tuple(
        candidate for candidate in cell.formula_candidates if candidate.source_index != 1
    ) + (
        ComponentFormulaCandidate(
            source_index=1,
            component_id="dc",
            formula_id=None,
            source=SYNTHETIC_SOURCE,
        ),
    )
    changed_cell = cell.model_copy(
        update={
            "components": components,
            "formula_candidates": candidates,
            "parse_status": "compound",
        }
    )
    changed = draft.model_copy(
        update={"raw_grids": (grid.model_copy(update={"cells": (changed_cell,)}),)}
    )

    with pytest.raises(ApprovalError, match="exact formula candidate"):
        record_correction(
            draft,
            changed,
            actor="Synthetic Reviewer",
            notes="Must remain fail closed.",
            resolve=draft.review_items,
        )


def _grid_for_cell(cell: RawGridCell) -> RawGrid:
    return RawGrid(
        id=f"raw-{synthetic_rule_package().tables[0].id}",
        rows=1,
        columns=1,
        target_unit="mm",
        segments=(
            RawGridSegment(
                page_number=3,
                row_start=0,
                row_count=1,
                source=SYNTHETIC_SOURCE,
            ),
        ),
        cells=(cell,),
        source=SYNTHETIC_SOURCE,
    )


def _draft_with_compound_cell(
    cell: RawGridCell,
    review_items: tuple[ImportReviewItem, ...],
) -> ImportedRuleDraft:
    package = synthetic_rule_package()
    table = package.tables[0]
    grid = RawGrid(
        id=f"raw-{table.id}",
        rows=1,
        columns=1,
        target_unit=table.unit,
        segments=(
            RawGridSegment(
                page_number=SYNTHETIC_SOURCE.page or 1,
                row_start=0,
                row_count=1,
                source=SYNTHETIC_SOURCE,
            ),
        ),
        cells=(cell,),
        source=SYNTHETIC_SOURCE,
    )
    proposal = SemanticProposal(
        semantic_id=table.id,
        rule_kind="table",
        state="reviewed",
        rule_sha256=canonical_model_sha256(table),
        source_artifact_sha256=canonical_model_sha256(grid),
        review_item_sha256s=tuple(item.sha256 for item in review_items),
    )
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(update={"approved": False, "approval_records": ()}),
        tables=(table,),
        formulas=(),
        mappings=(),
        review_items=review_items,
        raw_grids=(grid,),
        semantic_proposals=(proposal,),
        source_identities=(),
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        draft.review_items,
        draft.raw_grids,
        draft.raw_clause_fragments,
        draft.manifest.source_documents,
    )
    extraction = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (extraction,)})}
    )


def _compound_cell(
    *,
    formula_candidates: tuple[ComponentFormulaCandidate, ...] = (),
) -> RawGridCell:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 dc",
        spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
        source=SYNTHETIC_SOURCE,
    )
    return RawGridCell(
        row=0,
        column=0,
        raw_text="11 ac / 17 dc",
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        formula_candidates=formula_candidates,
        allowed_component_formula_ids=tuple(
            (candidate.component_id, candidate.formula_id)
            for candidate in formula_candidates
            if candidate.formula_id is not None
        ),
        parse_status="compound",
        source=SYNTHETIC_SOURCE,
    )


def test_component_correction_changes_only_the_selected_part_and_records_provenance() -> None:
    table_item = ImportReviewItem(
        code="SYNTHETIC_TABLE_REVIEW",
        semantic_id=synthetic_rule_package().tables[0].id,
        kind="table",
        source=SYNTHETIC_SOURCE,
        expected_contract="synthetic compound table",
    )
    draft = _draft_with_compound_cell(_compound_cell(), (table_item,))

    corrected = correct_raw_component(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        component_id="dc",
        value=Decimal(19),
        actor="Synthetic Reviewer",
        notes="Retyped the selected component.",
    )

    parts = corrected.raw_grids[0].cells[0].components
    assert [(part.component_id, part.value) for part in parts] == [
        ("ac", Decimal(11)),
        ("dc", Decimal(19)),
    ]
    assert parts[0].source == SYNTHETIC_SOURCE
    assert parts[1].source == SYNTHETIC_SOURCE
    assert corrected.manifest.approval_records[-1].actor == "Synthetic Reviewer"
    assert proposal_for(corrected, draft.tables[0].id).state == "proposed"


def test_ambiguous_formula_requires_an_exact_reviewed_candidate() -> None:
    candidates = (
        ComponentFormulaCandidate(
            component_id="ac", formula_id="formula-a", source=SYNTHETIC_SOURCE
        ),
        ComponentFormulaCandidate(
            component_id="ac", formula_id="formula-b", source=SYNTHETIC_SOURCE
        ),
    )
    cell = _compound_cell(formula_candidates=candidates)
    grid = RawGrid(
        id=f"raw-{synthetic_rule_package().tables[0].id}",
        rows=1,
        columns=1,
        target_unit="mm",
        segments=(
            RawGridSegment(
                page_number=3,
                row_start=0,
                row_count=1,
                source=SYNTHETIC_SOURCE,
            ),
        ),
        cells=(cell,),
        source=SYNTHETIC_SOURCE,
    )
    review_items = compound_review_items(grid)
    assert [item.code for item in review_items] == ["AMBIGUOUS_COMPONENT_FORMULA"]
    draft = _draft_with_compound_cell(cell, review_items)
    before = proposal_for(draft, draft.tables[0].id)

    corrected = select_component_formula(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        component_id="ac",
        formula_id="formula-b",
        actor="Synthetic Reviewer",
        notes="Selected the exact extracted candidate.",
    )

    after = proposal_for(corrected, draft.tables[0].id)
    assert corrected.raw_grids[0].cells[0].formula_candidates == (candidates[1],)
    assert after.source_artifact_sha256 != before.source_artifact_sha256
    assert after.state == "proposed"
    reviewed = mark_proposal_reviewed(
        corrected,
        after.semantic_id,
        actor="Synthetic Reviewer",
        notes="Reviewed the corrected association.",
    )
    assert proposal_for(reviewed, after.semantic_id).state == "reviewed"


def _cell_with_formula_contract(
    *,
    candidates: tuple[tuple[str, str | None], ...],
    allowed: tuple[tuple[str, str], ...],
) -> RawGridCell:
    parsed = parse_compound_data_cell(
        text="11 ac / 17 dc",
        spec=CompoundQuantitySpec(
            component_ids=("ac", "dc"),
            formula_candidates=candidates,
            allowed_formula_ids=allowed,
        ),
        source=SYNTHETIC_SOURCE,
    )
    return RawGridCell(
        row=0,
        column=0,
        raw_text="11 ac / 17 dc",
        role="data",
        logical_row=0,
        logical_column="compound",
        components=parsed.components,
        compound_component_ids=parsed.compound_component_ids,
        formula_candidates=parsed.formula_candidates,
        allowed_component_formula_ids=parsed.allowed_component_formula_ids,
        parse_status=parsed.parse_status,
        source=SYNTHETIC_SOURCE,
    )


def test_formula_selection_is_restricted_to_the_exact_component_route() -> None:
    cell = _cell_with_formula_contract(
        candidates=(("ac", None),),
        allowed=(("ac", "synthetic-tov-ac-formula"),),
    )
    draft = _draft_with_compound_cell(
        cell,
        compound_review_items(_grid_for_cell(cell)),
    )

    with pytest.raises(ValueError, match="component route"):
        select_component_formula(
            draft,
            grid_id=draft.raw_grids[0].id,
            row=0,
            column=0,
            source_index=0,
            component_id="ac",
            formula_id="synthetic-impulse-formula",
            actor="Synthetic Reviewer",
            notes="Must reject a formula from another route.",
        )

    corrected = select_component_formula(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        source_index=0,
        component_id="ac",
        formula_id="synthetic-tov-ac-formula",
        actor="Synthetic Reviewer",
        notes="Selected the route-local candidate.",
    )

    selected = corrected.raw_grids[0].cells[0].formula_candidates
    assert [(item.source_index, item.component_id, item.formula_id) for item in selected] == [
        (0, "ac", "synthetic-tov-ac-formula")
    ]
    assert proposal_for(corrected, draft.tables[0].id).state == "proposed"


def test_two_formula_blockers_are_unique_and_independently_resolvable() -> None:
    cell = _cell_with_formula_contract(
        candidates=(("ac", None), ("dc", None)),
        allowed=(
            ("ac", "synthetic-tov-ac-formula"),
            ("dc", "synthetic-tov-dc-formula"),
        ),
    )
    review_items = compound_review_items(_grid_for_cell(cell))
    assert [item.code for item in review_items] == [
        "AMBIGUOUS_COMPONENT_FORMULA",
        "AMBIGUOUS_COMPONENT_FORMULA",
    ]
    assert len({item.semantic_id for item in review_items}) == 2
    draft = _draft_with_compound_cell(cell, review_items)

    ac_selected = select_component_formula(
        draft,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        source_index=0,
        component_id="ac",
        formula_id="synthetic-tov-ac-formula",
        actor="Synthetic Reviewer",
        notes="Selected AC formula.",
    )
    assert len(unresolved_raw_review_items(ac_selected)) == 1

    dc_selected = select_component_formula(
        ac_selected,
        grid_id=draft.raw_grids[0].id,
        row=0,
        column=0,
        source_index=1,
        component_id="dc",
        formula_id="synthetic-tov-dc-formula",
        actor="Synthetic Reviewer",
        notes="Selected DC formula.",
    )
    assert unresolved_raw_review_items(dc_selected) == ()
    reviewed = mark_proposal_reviewed(
        dc_selected,
        draft.tables[0].id,
        actor="Synthetic Reviewer",
        notes="Reviewed both exact formula associations.",
    )
    assert proposal_for(reviewed, draft.tables[0].id).state == "reviewed"
