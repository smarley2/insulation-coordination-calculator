from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    CurveAxis,
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    PiecewiseCurveRule,
    RuleKind,
    SourceGeometryReference,
)
from insulation_coordination.rules.archive import _canonical_json
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    approve_draft,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    SemanticProposal,
    _content_digest,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.review import (
    mark_proposal_reviewed,
    proposal_for,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package


def _curve(source, artifact_sha256: str) -> PiecewiseCurveRule:
    return PiecewiseCurveRule(
        id="synthetic-curve",
        variants=(
            FaultTimeVoltageVariant(
                id="synthetic-curve-variant",
                selector=FaultTimeVoltageSelector(
                    subject="accessible_circuit",
                    voltage_basis="dc",
                    dvc_context=None,
                    environment_context=None,
                ),
                x_axis=CurveAxis(
                    quantity_kind="synthetic-time",
                    unit="s",
                    scale="linear",
                    minimum=Decimal(1),
                    maximum=Decimal(9),
                ),
                y_axis=CurveAxis(
                    quantity_kind="synthetic-voltage",
                    unit="V",
                    scale="linear",
                    minimum=Decimal(2),
                    maximum=Decimal(8),
                ),
                points=(
                    CurvePoint(x=Decimal(1), y=Decimal(8)),
                    CurvePoint(x=Decimal(9), y=Decimal(2)),
                ),
                segments=(
                    CurveSegment(
                        start=0,
                        end=1,
                        segment_type="continuous",
                        interpolation="linear",
                    ),
                ),
                applicability="Synthetic only.",
                source=source,
                reviewed_artifact_sha256=artifact_sha256,
            ),
        ),
        source=source,
    )


def _draft_with_every_rule_kind() -> ImportedRuleDraft:
    package = synthetic_rule_package()
    rules = (
        ("table", package.tables[0]),
        ("formula", package.formulas[0]),
        ("mapping", package.mappings[0].model_copy(update={"approved": False})),
        ("decision", package.decisions[0]),
        ("procedure", package.procedures[0]),
        ("guidance", package.guidance[0]),
    )
    artifact_sha256s = tuple(f"{index:x}" * 64 for index in range(1, 8))
    curve = _curve(package.tables[0].source, artifact_sha256s[-1])
    rules = (*rules, ("curve", curve))
    review_items = tuple(
        ImportReviewItem(
            code=f"SYNTHETIC_SEMANTIC_REVIEW_{index}",
            semantic_id=rule.id,
            kind="semantic",
            source=rule.source.model_copy(
                update={
                    "geometry": SourceGeometryReference(
                        artifact_sha256=artifact_sha256,
                    )
                }
            ),
            expected_contract=f"synthetic:{kind}:{rule.id}",
        )
        for index, ((kind, rule), artifact_sha256) in enumerate(
            zip(rules, artifact_sha256s, strict=True),
            start=1,
        )
    )
    resolutions = tuple(
        ImportReviewResolution(
            review_item_sha256=item.sha256,
            actor="Synthetic Reviewer",
            recorded_at=datetime(2026, 1, 3, tzinfo=UTC),
            notes="Synthetic artifact reviewed.",
        )
        for item in review_items
    )
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind=kind,
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
            review_item_sha256s=(item.sha256,),
        )
        for (kind, rule), artifact_sha256, item in zip(
            rules,
            artifact_sha256s,
            review_items,
            strict=True,
        )
    )
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "approval_records": (),
            }
        ),
        tables=package.tables,
        formulas=package.formulas,
        mappings=(package.mappings[0].model_copy(update={"approved": False}),),
        decisions=package.decisions,
        procedures=package.procedures,
        guidance=package.guidance,
        curves=(curve,),
        review_items=review_items,
        review_resolutions=resolutions,
        semantic_proposals=proposals,
        source_identities=(),
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        draft.review_items,
        source_documents=draft.manifest.source_documents,
        review_resolutions=draft.review_resolutions,
        decisions=draft.decisions,
        procedures=draft.procedures,
        guidance=draft.guidance,
        curves=draft.curves,
    )
    record = package.manifest.approval_records[0].model_copy(
        update={
            "action": "extraction",
            "actor": f"icc-importer/{IMPORTER_VERSION}",
            "notes": f"content:{digest}",
        }
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (record,)})}
    )


def _review_all_proposals(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    for proposal in draft.semantic_proposals:
        draft = mark_proposal_reviewed(
            draft,
            proposal.semantic_id,
            actor="Synthetic Reviewer",
            notes="Synthetic semantic review.",
        )
    return draft


def _replace_proposal(
    draft: ImportedRuleDraft,
    replacement: SemanticProposal,
) -> ImportedRuleDraft:
    return draft.model_copy(
        update={
            "semantic_proposals": tuple(
                replacement if item.semantic_id == replacement.semantic_id else item
                for item in draft.semantic_proposals
            )
        }
    )


@pytest.mark.parametrize(
    "rule_kind",
    ("table", "formula", "mapping", "decision", "procedure", "guidance", "curve"),
)
def test_proposal_review_and_correction_lifecycle_covers_every_rule_kind(
    rule_kind: RuleKind,
) -> None:
    draft = _review_all_proposals(_draft_with_every_rule_kind())
    proposal = next(item for item in draft.semantic_proposals if item.rule_kind == rule_kind)

    assert proposal_for(draft, proposal.semantic_id).state == "reviewed"

    collection_name = {
        "table": "tables",
        "formula": "formulas",
        "mapping": "mappings",
        "decision": "decisions",
        "procedure": "procedures",
        "guidance": "guidance",
        "curve": "curves",
    }[rule_kind]
    collection = getattr(draft, collection_name)
    changed_rule = collection[0].model_copy(
        update={"source": collection[0].source.model_copy(update={"note": "Corrected synthetic."})}
    )
    changed = draft.model_copy(update={collection_name: (changed_rule,)})

    corrected = record_correction(
        draft,
        changed,
        actor="Synthetic Reviewer",
        notes="Correct one synthetic semantic rule.",
    )

    assert proposal_for(corrected, proposal.semantic_id).state == "proposed"
    assert all(
        item.state == "reviewed"
        for item in corrected.semantic_proposals
        if item.semantic_id != proposal.semantic_id
    )


@pytest.mark.parametrize(
    "rule_kind",
    ("table", "formula", "mapping", "decision", "procedure", "guidance", "curve"),
)
def test_mark_reviewed_rejects_stale_rule_source_and_member_hashes_for_every_kind(
    rule_kind: RuleKind,
) -> None:
    draft = _draft_with_every_rule_kind()
    proposal = next(item for item in draft.semantic_proposals if item.rule_kind == rule_kind)

    stale_rule = proposal.model_copy(update={"rule_sha256": "0" * 64})
    with pytest.raises(ApprovalError, match="stale rule"):
        mark_proposal_reviewed(
            _replace_proposal(draft, stale_rule),
            proposal.semantic_id,
            actor="Reviewer",
            notes="Review",
        )

    stale_source = proposal.model_copy(update={"source_artifact_sha256": "0" * 64})
    with pytest.raises(ApprovalError, match="stale source"):
        mark_proposal_reviewed(
            _replace_proposal(draft, stale_source),
            proposal.semantic_id,
            actor="Reviewer",
            notes="Review",
        )

    stale_member = proposal.model_copy(update={"review_item_sha256s": ("0" * 64,)})
    with pytest.raises(ApprovalError, match="review item"):
        mark_proposal_reviewed(
            _replace_proposal(draft, stale_member),
            proposal.semantic_id,
            actor="Reviewer",
            notes="Review",
        )


@pytest.mark.parametrize(
    "rule_kind",
    ("table", "formula", "mapping", "decision", "procedure", "guidance", "curve"),
)
def test_approval_refuses_proposed_and_stale_proposals_for_every_kind(
    rule_kind: RuleKind,
) -> None:
    reviewed = _review_all_proposals(_draft_with_every_rule_kind())
    proposal = next(item for item in reviewed.semantic_proposals if item.rule_kind == rule_kind)

    proposed = proposal.model_copy(update={"state": "proposed"})
    with pytest.raises(ApprovalError, match="proposed"):
        approve_draft(
            _replace_proposal(reviewed, proposed),
            "Synthetic Reviewer",
            "Cannot approve proposed semantics.",
        )

    stale = proposal.model_copy(update={"rule_sha256": "0" * 64})
    with pytest.raises(ApprovalError, match="stale"):
        approve_draft(
            _replace_proposal(reviewed, stale),
            "Synthetic Reviewer",
            "Cannot approve stale semantics.",
        )


def test_rule_metadata_is_not_accepted_as_a_source_artifact() -> None:
    draft = _draft_with_every_rule_kind()
    proposal = next(item for item in draft.semantic_proposals if item.rule_kind == "decision")
    member_sha256 = proposal.review_item_sha256s[0]
    member = next(item for item in draft.review_items if item.sha256 == member_sha256)
    no_artifact = member.model_copy(
        update={"source": member.source.model_copy(update={"geometry": None})}
    )
    resolution = next(
        item for item in draft.review_resolutions if item.review_item_sha256 == member_sha256
    ).model_copy(update={"review_item_sha256": no_artifact.sha256})
    rule = next(rule for rule in draft.decisions if rule.id == proposal.semantic_id)
    ungrounded = proposal.model_copy(
        update={
            "source_artifact_sha256": canonical_model_sha256(rule.source),
            "review_item_sha256s": (no_artifact.sha256,),
        }
    )
    draft = draft.model_copy(
        update={
            "review_items": tuple(
                no_artifact if item.sha256 == member_sha256 else item
                for item in draft.review_items
            ),
            "review_resolutions": tuple(
                resolution if item.review_item_sha256 == member_sha256 else item
                for item in draft.review_resolutions
            ),
            "semantic_proposals": tuple(
                ungrounded if item.semantic_id == proposal.semantic_id else item
                for item in draft.semantic_proposals
            ),
        }
    )

    with pytest.raises(ApprovalError, match="source artifact"):
        mark_proposal_reviewed(
            draft,
            proposal.semantic_id,
            actor="Reviewer",
            notes="Metadata is not evidence.",
        )


def test_proposal_cannot_omit_importer_required_review_members() -> None:
    draft = _draft_with_every_rule_kind()
    proposal = next(item for item in draft.semantic_proposals if item.rule_kind == "guidance")
    rule = next(rule for rule in draft.guidance if rule.id == proposal.semantic_id)
    omitted = proposal.model_copy(
        update={
            "source_artifact_sha256": canonical_model_sha256(rule.source),
            "review_item_sha256s": (),
        }
    )

    with pytest.raises(ApprovalError, match="required review item"):
        mark_proposal_reviewed(
            _replace_proposal(draft, omitted),
            proposal.semantic_id,
            actor="Reviewer",
            notes="Cannot omit required evidence.",
        )


def test_multiple_artifacts_use_canonical_ordered_pairs() -> None:
    draft = _draft_with_every_rule_kind()
    proposal = draft.semantic_proposals[0]
    first = draft.review_items[0]
    second = first.model_copy(
        update={
            "code": "ZZZ_SYNTHETIC_SECOND_ARTIFACT",
            "source": first.source.model_copy(
                update={"geometry": SourceGeometryReference(artifact_sha256="f" * 64)}
            ),
        }
    )
    second_resolution = draft.review_resolutions[0].model_copy(
        update={"review_item_sha256": second.sha256}
    )
    pairs = [
        (f"{first.semantic_id}:{first.code}", "1" * 64),
        (f"{second.semantic_id}:{second.code}", "f" * 64),
    ]
    aggregate = hashlib.sha256(_canonical_json(pairs)).hexdigest()
    multi = proposal.model_copy(
        update={
            "source_artifact_sha256": aggregate,
            "review_item_sha256s": (first.sha256, second.sha256),
        }
    )
    draft = draft.model_copy(
        update={
            "review_items": (*draft.review_items, second),
            "review_resolutions": (*draft.review_resolutions, second_resolution),
            "semantic_proposals": (multi, *draft.semantic_proposals[1:]),
        }
    )

    reviewed = mark_proposal_reviewed(
        draft,
        proposal.semantic_id,
        actor="Reviewer",
        notes="Reviewed both synthetic artifacts.",
    )
    assert proposal_for(reviewed, proposal.semantic_id).state == "reviewed"

    reversed_aggregate = hashlib.sha256(_canonical_json(tuple(reversed(pairs)))).hexdigest()
    stale = multi.model_copy(
        update={
            "source_artifact_sha256": reversed_aggregate,
            "review_item_sha256s": tuple(reversed(multi.review_item_sha256s)),
        }
    )
    with pytest.raises(ApprovalError, match="required review item|stale source"):
        mark_proposal_reviewed(
            draft.model_copy(update={"semantic_proposals": (stale, *draft.semantic_proposals[1:])}),
            proposal.semantic_id,
            actor="Reviewer",
            notes="Wrong order.",
        )


def test_approval_blockers_are_the_single_manual_and_semantic_gate() -> None:
    draft = _draft_with_every_rule_kind()
    assert {item.code for item in approval_blockers(draft)} == {"SEMANTIC_PROPOSAL_PROPOSED"}

    reviewed = _review_all_proposals(draft)
    assert approval_blockers(reviewed) == ()

    stale = reviewed.semantic_proposals[0].model_copy(update={"rule_sha256": "0" * 64})
    stale_draft = reviewed.model_copy(
        update={"semantic_proposals": (stale, *reviewed.semantic_proposals[1:])}
    )
    assert "stale" in approval_blockers(stale_draft)[0].expected_contract

    missing = reviewed.model_copy(update={"semantic_proposals": reviewed.semantic_proposals[:-1]})
    assert approval_blockers(missing)[0].code == "SEMANTIC_PROPOSAL_MISSING"

    duplicate_resolution = reviewed.model_copy(
        update={
            "review_resolutions": (
                *reviewed.review_resolutions,
                reviewed.review_resolutions[0],
            )
        }
    )
    assert approval_blockers(duplicate_resolution)[0].code == "REVIEW_RESOLUTION_INVALID"
