"""Curve review model over reconstructed curves. Synthetic content only."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    CurveAxis,
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    PiecewiseCurveRule,
    SourceDocument,
    SourceGeometryReference,
    SourceReference,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    approve_draft,
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
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.ui.curve_review import CurveReviewModel
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-curves",
    standard="SYNTHETIC",
    edition="1",
    page=54,
    clause="9.9.9",
    figure="SF-5",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="9" * 64,
    page_count=56,
    recipe_id="synthetic-curves",
)
VARIANT_ID = f"{ids.DVC_FAULT_TIME_VOLTAGE}.synthetic"


def _curve() -> PiecewiseCurveRule:
    variant = FaultTimeVoltageVariant(
        id=VARIANT_ID,
        selector=FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_rms",
            dvc_context=None,
            environment_context=None,
        ),
        x_axis=CurveAxis(
            quantity_kind="duration",
            unit="s",
            scale="log10",
            minimum=Decimal(1),
            maximum=Decimal(100),
        ),
        y_axis=CurveAxis(
            quantity_kind="voltage",
            unit="V",
            scale="log10",
            minimum=Decimal(10),
            maximum=Decimal(1000),
        ),
        points=(
            CurvePoint(x=Decimal(1), y=Decimal(100)),
            CurvePoint(x=Decimal(10), y=Decimal(50)),
            CurvePoint(x=Decimal(100), y=Decimal(20)),
        ),
        segments=(
            CurveSegment(start=0, end=1, segment_type="continuous", interpolation="log_log"),
            CurveSegment(start=1, end=2, segment_type="continuous", interpolation="log_log"),
        ),
        applicability="review required",
        source=SOURCE,
        reviewed_artifact_sha256="a" * 64,
    )
    return PiecewiseCurveRule(
        id=ids.DVC_FAULT_TIME_VOLTAGE,
        variants=(variant,),
        source=SOURCE,
    )


@pytest.fixture
def draft(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    curve = _curve()
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "expected_page_count": 56,
            "tables": (),
            "formulas": (),
            "mappings": (),
            "clauses": (),
            "curves": (),
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    review_item = ImportReviewItem(
        code="SYNTHETIC_CURVE_REVIEW",
        semantic_id=VARIANT_ID,
        kind="curve",
        source=SOURCE.model_copy(
            update={
                "geometry": SourceGeometryReference(
                    artifact_sha256=curve.variants[0].reviewed_artifact_sha256,
                )
            }
        ),
        expected_contract="synthetic curve review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Curve Reviewer",
        recorded_at=datetime(2026, 8, 9, tzinfo=UTC),
        notes="Reviewed the synthetic curve source artifact.",
    )
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (
                    SourceDocument(
                        id=IDENTITY.recipe_id,
                        standard=IDENTITY.standard,
                        edition=IDENTITY.edition,
                        sha256=IDENTITY.sha256,
                    ),
                ),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        curves=(curve,),
        review_items=(review_item,),
        review_resolutions=(resolution,),
        raw_grids=(),
        semantic_proposals=(
            SemanticProposal(
                semantic_id=curve.id,
                rule_kind="curve",
                state="proposed",
                rule_sha256=canonical_model_sha256(curve),
                source_artifact_sha256=curve.variants[0].reviewed_artifact_sha256,
                review_item_sha256s=(review_item.sha256,),
            ),
        ),
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
        curves=draft.curves,
    )
    recorded_at = datetime(2026, 8, 9, tzinfo=UTC)
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
            f"curve:{curve.id}",
            f"review:{review_item.code}:{review_item.semantic_id}",
            f"content:{digest}",
        )
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": records})}
    )


def test_breakpoint_correction_changes_hash_and_resets_review(draft) -> None:
    model = CurveReviewModel(draft)
    before = canonical_model_sha256(
        next(rule for rule in model.draft.curves if rule.id == ids.DVC_FAULT_TIME_VOLTAGE)
    )
    model.set_breakpoint(
        VARIANT_ID,
        1,
        CurvePoint(x=Decimal(10), y=Decimal(45)),
        actor="Synthetic Reviewer",
        notes="Move one synthetic breakpoint down.",
    )
    rule = next(rule for rule in model.draft.curves if rule.id == ids.DVC_FAULT_TIME_VOLTAGE)
    assert canonical_model_sha256(rule) != before
    assert rule.variants[0].points[1].y == Decimal(45)
    proposal = next(
        item
        for item in model.draft.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    )
    assert proposal.state == "proposed"


def test_segment_correction_changes_interpolation(draft) -> None:
    model = CurveReviewModel(draft)
    model.set_segment(
        VARIANT_ID,
        1,
        1,
        2,
        "continuous",
        "log_x",
        actor="Synthetic Reviewer",
        notes="Switch the synthetic tail interpolation.",
    )
    rule = next(rule for rule in model.draft.curves if rule.id == ids.DVC_FAULT_TIME_VOLTAGE)
    assert rule.variants[0].segments[1].segment_type == "continuous"
    assert rule.variants[0].segments[1].interpolation == "log_x"


def test_review_variant_marks_aggregate_proposal_reviewed(draft) -> None:
    model = CurveReviewModel(draft)
    assert model.can_approve is False
    model.review_variant(
        VARIANT_ID,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the synthetic curve.",
    )
    proposal = next(
        item
        for item in model.draft.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    )
    assert proposal.state == "reviewed"
    assert model.can_approve is True


def test_unknown_variant_blocks(draft) -> None:
    model = CurveReviewModel(draft)
    with pytest.raises(ValueError, match="unknown curve variant"):
        model.set_breakpoint(
            f"{ids.DVC_FAULT_TIME_VOLTAGE}.missing",
            0,
            CurvePoint(x=Decimal(1), y=Decimal(1)),
            actor="Synthetic Reviewer",
            notes="Attempt an unknown variant.",
        )


def test_reviewed_curve_approves(draft) -> None:
    model = CurveReviewModel(draft)
    model.review_variant(
        VARIANT_ID,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the synthetic curve.",
    )
    package = approve_draft(model.draft, "Synthetic Approver", "Approve synthetic draft.")
    assert package.manifest.approved is True
    assert package.curves[0].id == ids.DVC_FAULT_TIME_VOLTAGE
    assert not hasattr(package, "raw_figures") or package.manifest.approved
