"""Semantic proposal review model. Synthetic content only."""

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
    ApprovalError,
    approval_blockers,
    approve_draft,
)
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
from insulation_coordination.rules.importer.curves import ManualPlotCalibration, RawFigure
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    CurveCalibrationReview,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    ManualCurveVariantInput,
    _content_digest,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    CurveAuditSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.review import (
    _manual_reviewed_artifact_sha256,
    build_reviewed_draft,
    proposal_for,
)
from insulation_coordination.ui.curve_review import CurveReviewModel
from insulation_coordination.ui.semantic_review import SemanticReviewModel
from tests.fixtures.synthetic_rules import synthetic_rule_package

SOURCE = SourceReference(
    document_id="synthetic-clause",
    standard="SYNTHETIC",
    edition="1",
    page=44,
    clause="9.9.9",
    table="SC-1",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="5" * 64,
    page_count=3,
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
CURVE_VARIANT_ID = f"{ids.DVC_FAULT_TIME_VOLTAGE}.SF-1.1"


def _node(order: int, text: str) -> ClauseNode:
    return ClauseNode(
        order=order,
        kind="paragraph",
        raw_text=text,
        source=SOURCE.model_copy(update={"row": f"bullet {order + 1}"}),
    )


def _token(kind: str, raw: str, normalized: str | Decimal, order: int) -> ClauseToken:
    return ClauseToken(
        kind=kind,
        raw_text=raw,
        normalized=normalized,
        source=SOURCE.model_copy(update={"row": f"bullet {order + 1}"}),
    )


def _fragment() -> RawClauseFragment:
    nodes = (_node(0, "neutral paragraph with three reviewed figure references"),)
    tokens = (
        _token("reference", "Figure 5", "figure-5", 0),
        _token("reference", "Figure 6", "figure-6", 0),
        _token("reference", "Figure 7", "figure-7", 0),
    )
    fragment = RawClauseFragment(
        id=f"raw-{ids.DVC_FAULT_APPLICABILITY}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=tokens,
        source=SOURCE,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})



def _synthetic_curve() -> PiecewiseCurveRule:
    source = SOURCE.model_copy(update={"figure": "SF-1"})
    axis_x = CurveAxis(
        quantity_kind="duration",
        unit="s",
        scale="log10",
        minimum=Decimal(1),
        maximum=Decimal(100),
    )
    axis_y = CurveAxis(
        quantity_kind="voltage",
        unit="V",
        scale="log10",
        minimum=Decimal(1),
        maximum=Decimal(100),
    )
    variant = FaultTimeVoltageVariant(
        id=CURVE_VARIANT_ID,
        selector=FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_rms",
            dvc_context=None,
            environment_context=None,
        ),
        x_axis=axis_x,
        y_axis=axis_y,
        points=(
            CurvePoint(x=Decimal(1), y=Decimal(10)),
            CurvePoint(x=Decimal(10), y=Decimal(20)),
        ),
        segments=(
            CurveSegment(start=0, end=1, segment_type="continuous", interpolation="log_log"),
        ),
        applicability="synthetic placeholder; not an IEC curve",
        source=source,
        reviewed_artifact_sha256="6" * 64,
    )
    return PiecewiseCurveRule(
        id=ids.DVC_FAULT_TIME_VOLTAGE,
        variants=(variant,),
        source=source,
    )


@pytest.fixture
def built_draft(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    fragment = _fragment()
    review_item = ImportReviewItem(
        code="SYNTHETIC_CLAUSE_REVIEW",
        semantic_id=ids.DVC_FAULT_APPLICABILITY,
        kind="clause",
        source=SOURCE,
        expected_contract="synthetic clause review",
    )
    curve = _synthetic_curve()
    curve_item = ImportReviewItem(
        code="SYNTHETIC_CURVE_REVIEW",
        semantic_id=CURVE_VARIANT_ID,
        kind="curve",
        source=curve.source.model_copy(
            update={
                "geometry": SourceGeometryReference(
                    artifact_sha256="6" * 64,
                )
            }
        ),
        expected_contract="synthetic curve review",
    )
    resolution = ImportReviewResolution(
        review_item_sha256=review_item.sha256,
        actor="Synthetic Source Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed the synthetic clause source artifact.",
    )
    selector = curve.variants[0].selector
    curve_spec = CurveAuditSpec(
        semantic_id=ids.DVC_FAULT_TIME_VOLTAGE,
        figure="SF-1",
        page_number=44,
        expected_bbox=(0.0, 0.0, 100.0, 140.0),
        expected_pixel_size=None,
        x_quantity_kind="duration",
        x_unit="s",
        y_quantity_kind="voltage",
        y_unit="V",
        x_scale="log10",
        y_scale="log10",
        variant_slots=(selector,),
        permitted_segment_types=("continuous", "plateau"),
        permitted_interpolations=("log_log", "constant"),
    )
    recipe = IEC_RECIPE.model_copy(
        update={
            "id": IDENTITY.recipe_id,
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "expected_page_count": 3,
            "tables": (),
            "formulas": (),
            "mappings": (),
            "clauses": (SPEC,),
            "curves": (curve_spec,),
            "required_curves": (ids.DVC_FAULT_TIME_VOLTAGE,),
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    figure = RawFigure(
        source=curve.source,
        source_mode="vector_path",
        source_bbox=(Decimal(0), Decimal(0), Decimal(100), Decimal(140)),
        pixel_size=(100, 140),
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        artifact_sha256="6" * 64,
    )
    calibration = ManualPlotCalibration(
        figure_artifact_sha256=figure.artifact_sha256,
        left=Decimal(0),
        top=Decimal(0),
        right=Decimal(100),
        bottom=Decimal(140),
        x_min=Decimal(1),
        x_max=Decimal(100),
        y_min=Decimal(1),
        y_max=Decimal(100),
    )
    calibration_sha256 = canonical_model_sha256(calibration)
    reviewed_artifact_sha256 = _manual_reviewed_artifact_sha256(
        figure, calibration_sha256
    )
    variant = curve.variants[0].model_copy(
        update={"reviewed_artifact_sha256": reviewed_artifact_sha256}
    )
    curve = curve.model_copy(update={"variants": (variant,)})
    calibration_review = CurveCalibrationReview(
        figure_artifact_sha256=figure.artifact_sha256,
        calibration=calibration,
        calibration_sha256=calibration_sha256,
        actor="Synthetic Curve Reviewer",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
        notes="Reviewed synthetic calibration.",
    )
    manual_input = ManualCurveVariantInput(
        variant_id=variant.id,
        variant_sha256=canonical_model_sha256(variant),
        source_artifact_sha256=reviewed_artifact_sha256,
        calibration_sha256=calibration_sha256,
        input_origin="empty",
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
        review_items=(review_item, curve_item),
        review_resolutions=(resolution,),
        raw_grids=(),
        raw_clause_fragments=(fragment,),
        raw_figures=(figure,),
        curve_calibrations=(calibration_review,),
        manual_curve_variant_inputs=(manual_input,),
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
        raw_figures=draft.raw_figures,
        curve_calibrations=draft.curve_calibrations,
        manual_curve_variant_inputs=draft.manual_curve_variant_inputs,
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
            f"curve:{curve.id}",
            f"review:{review_item.code}:{review_item.semantic_id}",
            f"review:{curve_item.code}:{curve_item.semantic_id}",
            f"content:{digest}",
        )
    )
    draft = draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": records})}
    )
    return build_reviewed_draft(draft, actor="Synthetic Rule Builder", notes="Build.")


def test_model_lists_proposals_with_kind_state_and_hash(built_draft) -> None:
    model = SemanticReviewModel(built_draft)
    summaries = model.proposals
    by_id = {item.semantic_id: item for item in summaries}
    assert set(by_id) == {ids.DVC_FAULT_APPLICABILITY, ids.DVC_FAULT_TIME_VOLTAGE}
    summary = by_id[ids.DVC_FAULT_APPLICABILITY]
    assert summary.rule_kind == "decision"
    assert summary.state == "proposed"
    assert len(summary.rule_sha256) == 64
    assert summary.source.page == 44
    assert summary.source.clause == "9.9.9"
    curve_summary = by_id[ids.DVC_FAULT_TIME_VOLTAGE]
    assert curve_summary.rule_kind == "curve"


def test_review_marks_proposal_reviewed(built_draft) -> None:
    model = SemanticReviewModel(built_draft)
    assert model.can_approve is False
    model.review(
        ids.DVC_FAULT_APPLICABILITY,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed the generated clause decision.",
    )
    assert model.proposal(ids.DVC_FAULT_APPLICABILITY).state == "reviewed"
    assert model.can_approve is False


def test_correction_changes_hash_and_resets_review(built_draft) -> None:
    model = SemanticReviewModel(built_draft)
    model.review(
        ids.DVC_FAULT_APPLICABILITY,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed.",
    )
    curve_model = CurveReviewModel(model.draft)
    curve_model.review_variant(
        CURVE_VARIANT_ID,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the synthetic curve.",
    )
    model = SemanticReviewModel(curve_model.draft)
    before_artifact = model.proposal(ids.DVC_FAULT_APPLICABILITY).source_artifact_sha256
    assert model.can_approve is True

    fragment = model.draft.raw_clause_fragments[0]
    changed = fragment.model_copy(
        update={
            "tokens": tuple(
                token.model_copy(update={"raw_text": "corrected Figure 5 source"})
                if token.normalized == "figure-5"
                else token
                for token in fragment.tokens
            ),
            "nodes": (
                fragment.nodes[0].model_copy(
                    update={"raw_text": "corrected neutral paragraph with three references"}
                ),
            ),
        }
    )
    model.correct(
        model.draft.model_copy(update={"raw_clause_fragments": (changed,)}),
        actor="Synthetic Source Reviewer",
        notes="Correct one reviewed synthetic clause reference.",
    )
    assert model.proposal(ids.DVC_FAULT_APPLICABILITY).state == "proposed"
    assert model.proposal(ids.DVC_FAULT_TIME_VOLTAGE).state == "reviewed"
    assert model.can_approve is False
    # The rule itself is rebuilt only at projection time; the correction changes the
    # source artifact hash, and that drift is what resets the proposal to proposed.
    assert (
        model.proposal(ids.DVC_FAULT_APPLICABILITY).source_artifact_sha256
        != before_artifact
    )


def test_complete_review_enables_approval(built_draft) -> None:
    model = SemanticReviewModel(built_draft)
    with pytest.raises(ApprovalError):
        approve_draft(model.draft, "Synthetic Approver", "Approve too early.")
    model.review(
        ids.DVC_FAULT_APPLICABILITY,
        actor="Synthetic Semantic Reviewer",
        notes="Reviewed.",
    )
    curve_model = CurveReviewModel(model.draft)
    curve_model.review_variant(
        CURVE_VARIANT_ID,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the synthetic curve.",
    )
    model = SemanticReviewModel(curve_model.draft)
    proposal = proposal_for(model.draft, ids.DVC_FAULT_TIME_VOLTAGE)
    assert proposal.state == "reviewed"
    package = approve_draft(model.draft, "Synthetic Approver", "Approve synthetic draft.")
    assert package.manifest.approved is True
    assert ids.DVC_FAULT_APPLICABILITY in {rule.id for rule in package.decisions}
    assert package.curves[0].id == ids.DVC_FAULT_TIME_VOLTAGE


def test_source_jump_uses_typed_page_and_bbox(built_draft) -> None:
    model = SemanticReviewModel(built_draft)
    target = model.source_target(ids.DVC_FAULT_APPLICABILITY)
    assert target.page == 44
    assert target.bbox == SPEC.expected_bbox
    assert target.clause == "9.9.9"
    assert target.document_id == "synthetic-clause"


def test_missing_required_curve_blocks_approval_with_named_id(built_draft) -> None:
    """A draft without the recipe-declared curve is blocked and names the curve."""
    without_curve = built_draft.model_copy(
        update={
            "curves": (),
            "semantic_proposals": tuple(
                proposal
                for proposal in built_draft.semantic_proposals
                if proposal.semantic_id != ids.DVC_FAULT_TIME_VOLTAGE
            ),
        }
    )
    blockers = approval_blockers(without_curve)
    curve_blockers = [item for item in blockers if item.code == "CURVE_REQUIRED"]
    assert [item.semantic_id for item in curve_blockers] == [ids.DVC_FAULT_TIME_VOLTAGE]
    with pytest.raises(ApprovalError, match="fault_time_voltage"):
        approve_draft(without_curve, "Synthetic Approver", "Approve without curve.")
