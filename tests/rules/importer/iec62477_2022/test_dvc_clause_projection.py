"""Synthetic DVC fault-applicability clause projection. No IEC content."""

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
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
    normalize_clause_fragment,
)
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    _content_digest,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import ClauseAuditSpec, StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    project_dvc_fault_applicability,
)
from insulation_coordination.rules.importer.review import (
    build_reviewed_draft,
    mark_proposal_reviewed,
    missing_required_content,
    unresolved_clause_items,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-clause",
    standard="SYNTHETIC",
    edition="1",
    page=44,
    clause="9.9.9",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="5" * 64,
    page_count=44,
    recipe_id="synthetic-clause",
)
SPEC = ClauseAuditSpec(
    semantic_id=ids.DVC_FAULT_APPLICABILITY,
    clause="9.9.9",
    page_number=44,
    expected_bbox=(70.0, 660.0, 524.0, 760.0),
    expected_root_kind="paragraph",
    output_kind="decision",
)


def synthetic_identity() -> StandardIdentity:
    return IDENTITY


def _node(order: int, text: str) -> ClauseNode:
    return ClauseNode(
        order=order,
        kind="paragraph",
        raw_text=text,
        source=SOURCE.model_copy(update={"row": f"bullet {order + 1}"}),
    )


def _token(kind: str, raw: str, normalized: str, order: int) -> ClauseToken:
    return ClauseToken(
        kind=kind,
        raw_text=raw,
        normalized=normalized,
        source=SOURCE.model_copy(update={"row": f"bullet {order + 1}"}),
    )


def _fragment(*, references: tuple[str, ...] = ("figure-5", "figure-6", "figure-7")) -> RawClauseFragment:
    nodes = (_node(0, "neutral fault-voltage paragraph with three figure slots"),)
    tokens = [
        _token("reference", f"slot {figure}", figure, 0)
        for figure in references
    ]
    fragment = RawClauseFragment(
        id=f"raw-{ids.DVC_FAULT_APPLICABILITY}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=tuple(tokens),
        source=SOURCE,
    )
    return fragment.model_copy(
        update={"raw_sha256": canonical_model_sha256(fragment)}
    )


def test_projection_emits_typed_applicability_inputs_and_outputs() -> None:
    rules, proposals = project_dvc_fault_applicability(_fragment(), synthetic_identity())
    assert len(rules) == 1
    rule = rules[0]
    assert rule.id == ids.DVC_FAULT_APPLICABILITY
    assert {item.name for item in rule.inputs} == {
        "subject",
        "voltage_basis",
    }
    assert {output.name for output in rule.outputs} == {
        "curve_applicability",
        "required_curve",
    }
    kinds = {output.name: output.kind for output in rule.outputs}
    assert kinds["curve_applicability"] == "boolean"
    # categorical, not reference: package validation resolves reference outputs only
    # against decision/procedure/guidance IDs, never curve IDs. The curve rule ID is
    # carried as a categorical value.
    assert kinds["required_curve"] == "categorical"
    assert {proposal.semantic_id for proposal in proposals} == {rule.id}
    assert all(proposal.state == "proposed" for proposal in proposals)


def test_projection_evaluates_all_four_curve_selector_routes() -> None:
    rules, _ = project_dvc_fault_applicability(_fragment(), synthetic_identity())
    rule = rules[0]
    for subject, basis in (
        ("accessible_circuit", "dc"),
        ("accessible_circuit", "ac_peak"),
        ("conductive_accessible_part", "dc"),
        ("conductive_accessible_part", "ac_unspecified"),
    ):
        result = evaluate_decision(rule, {"subject": subject, "voltage_basis": basis})
        assert result.values[0].boolean is True
        curve_value = next(value for value in result.values if value.name == "required_curve")
        assert curve_value.categorical == ids.DVC_FAULT_TIME_VOLTAGE


def test_missing_or_unknown_figure_reference_blocks_projection() -> None:
    for references in (("figure-5", "figure-6"), ("figure-5", "figure-6", "figure-8")):
        with pytest.raises(ValueError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
            project_dvc_fault_applicability(
                _fragment(references=references), synthetic_identity()
            )


def test_wrong_fragment_identity_blocks_projection() -> None:
    fragment = _fragment().model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="fault applicability"):
        project_dvc_fault_applicability(fragment, synthetic_identity())


def test_normalization_is_hash_stable_for_projection() -> None:
    fragment = normalize_clause_fragment(_fragment())
    _rules, proposals = project_dvc_fault_applicability(fragment, synthetic_identity())
    assert proposals[0].source_artifact_sha256 == canonical_model_sha256(fragment)


def _logged_clause_extraction(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    fragment = _fragment()
    review_item = ImportReviewItem(
        code="SYNTHETIC_CLAUSE_REVIEW",
        semantic_id=ids.DVC_FAULT_APPLICABILITY,
        kind="clause",
        source=SOURCE,
        expected_contract="synthetic clause review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic clause source artifact.",
    )
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "tables": (),
            "formulas": (),
            "mappings": (),
            "clauses": (SPEC,),
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
        raw_grids=(),
        raw_clause_fragments=(fragment,),
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
    recorded_at = datetime(2026, 8, 8, tzinfo=UTC)
    records = tuple(
        ApprovalRecord(
            action="extraction",
            actor=f"icc-importer/{IMPORTER_VERSION}",
            recorded_at=recorded_at,
            notes=note,
        )
        for note in (
            f"identity:{IDENTITY.recipe_id}",
            f"layout:{IDENTITY.recipe_id}",
            f"raw-clause:{fragment.id}",
            f"review:{review_item.code}:{review_item.semantic_id}",
            f"content:{digest}",
        )
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": records})}
    )


def test_build_and_review_lifecycle_resets_after_fragment_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_clause_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build clause decisions.",
    )
    proposal = next(
        item
        for item in built.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_APPLICABILITY
    )
    assert proposal.state == "proposed"

    reviewed = mark_proposal_reviewed(
        built,
        ids.DVC_FAULT_APPLICABILITY,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed the generated clause decision.",
    )
    assert (
        next(
            item
            for item in reviewed.semantic_proposals
            if item.semantic_id == ids.DVC_FAULT_APPLICABILITY
        ).state
        == "reviewed"
    )

    fragment = reviewed.raw_clause_fragments[0]
    changed = fragment.model_copy(
        update={
            "tokens": tuple(
                token.model_copy(update={"raw_text": "corrected source figure slot"})
                if token.normalized == "figure-5"
                else token
                for token in fragment.tokens
            )
        }
    )
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(update={"raw_clause_fragments": (changed,)}),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic clause reference.",
    )
    assert (
        next(
            item
            for item in corrected.semantic_proposals
            if item.semantic_id == ids.DVC_FAULT_APPLICABILITY
        ).state
        == "proposed"
    )
    assert {blocker.code for blocker in approval_blockers(corrected)} >= {
        "SEMANTIC_PROPOSAL_PROPOSED"
    }


def test_unrelated_prefixed_decision_cannot_borrow_clause_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = build_reviewed_draft(
        _logged_clause_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build clause decisions.",
    )
    rule = next(
        item for item in built.decisions if item.id == ids.DVC_FAULT_APPLICABILITY
    )
    unrelated = rule.model_copy(update={"id": f"{ids.DVC_FAULT_APPLICABILITY}.unrelated"})

    with pytest.raises(ApprovalError, match="review item inventory"):
        record_correction(
            built,
            built.model_copy(update={"decisions": (*built.decisions, unrelated)}),
            actor="Synthetic Rule Builder",
            notes="Attempt an unrelated prefixed decision.",
        )


def test_recipe_emits_clause_review_item_and_build_blocks_until_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insulation_coordination.rules.importer.extract import _manual_review_items

    draft = _logged_clause_extraction(monkeypatch)
    recipe = next(
        item for item in recipe_registry.RECIPES if item.id == IDENTITY.recipe_id
    )
    clause_items = tuple(
        item
        for item in _manual_review_items(IDENTITY, recipe)
        if item.kind == "clause"
    )
    assert [item.code for item in clause_items] == ["MANUAL_CLAUSE_DEFINITION_REQUIRED"]
    assert clause_items[0].semantic_id == ids.DVC_FAULT_APPLICABILITY

    gated = draft.model_copy(
        update={"review_items": (*draft.review_items, *clause_items)}
    )
    assert unresolved_clause_items(gated) == clause_items
    with pytest.raises(ValueError, match="Review extracted clauses first"):
        build_reviewed_draft(gated, actor="Synthetic Rule Builder", notes="Build.")


def test_missing_clause_fragment_is_flagged_as_required_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _logged_clause_extraction(monkeypatch).model_copy(
        update={"raw_clause_fragments": ()}
    )
    missing = missing_required_content(draft)
    clause_missing = [item for item in missing if item.kind == "clause"]
    assert [item.semantic_id for item in clause_missing] == [ids.DVC_FAULT_APPLICABILITY]


def test_rule_change_with_unchanged_artifact_resets_reviewed_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule changed, artifact and review hashes unchanged -> fresh proposed probe."""
    built = build_reviewed_draft(
        _logged_clause_extraction(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build clause decisions.",
    )
    reviewed = mark_proposal_reviewed(
        built,
        ids.DVC_FAULT_APPLICABILITY,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed the generated clause decision.",
    )
    rule = next(
        item for item in reviewed.decisions if item.id == ids.DVC_FAULT_APPLICABILITY
    )
    changed_rule = rule.model_copy(update={"applicability": "reviewed synthetic route"})
    corrected = record_correction(
        reviewed,
        reviewed.model_copy(
            update={
                "decisions": tuple(
                    changed_rule if item.id == rule.id else item
                    for item in reviewed.decisions
                )
            }
        ),
        actor="Synthetic Rule Builder",
        notes="Clarify the clause decision applicability.",
    )
    proposal = next(
        item
        for item in corrected.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_APPLICABILITY
    )
    assert proposal.state == "proposed"
    assert proposal.rule_sha256 == canonical_model_sha256(changed_rule)
