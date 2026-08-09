"""Curve review model over reconstructed curves. Synthetic content only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pypdf import PdfWriter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsPathItem

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
from insulation_coordination.rules.importer.curves import (
    AxisCalibration,
    ConservatismReport,
    CurveDigitizationResult,
    PlotCalibration,
    RawCurvePoint,
    RawCurveTrace,
    RawFigure,
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
from insulation_coordination.rules.importer.review import _aggregate_artifact_pairs
from insulation_coordination.ui.curve_review import CurveReviewDialog, CurveReviewModel
from insulation_coordination.ui.rules_manager import RulesManagerWindow
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
    calibration = PlotCalibration(
        x=AxisCalibration(
            scale="log10",
            slope=Decimal("0.01"),
            intercept=Decimal(0),
            residual_pixels=Decimal(0),
            minor_grid_spacing_pixels=Decimal(10),
        ),
        y=AxisCalibration(
            scale="log10",
            slope=Decimal("0.01"),
            intercept=Decimal(0),
            residual_pixels=Decimal(0),
            minor_grid_spacing_pixels=Decimal(10),
        ),
    )
    trace = RawCurveTrace(
        id="synthetic-trace",
        points=(
            RawCurvePoint(x=Decimal(0), y=Decimal("-201.1"), space="pixel", primitive_ref="p0"),
            RawCurvePoint(x=Decimal(100), y=Decimal("-170.9970004336"), space="pixel", primitive_ref="p1"),
            RawCurvePoint(x=Decimal(200), y=Decimal("-131.2029995664"), space="pixel", primitive_ref="p2"),
        ),
        stroke_width=Decimal(2),
    )
    figure = RawFigure(
        source=SOURCE,
        source_mode="vector_path",
        source_bbox=(Decimal(0), Decimal(0), Decimal(200), Decimal(220)),
        pixel_size=(200, 220),
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        ocr_tokens=(),
        traces=(trace,),
        artifact_sha256="a" * 64,
    )
    digitization = CurveDigitizationResult(
        proposed_rule=curve,
        calibration=calibration,
        conservatism=ConservatismReport(
            maximum_positive_voltage_error=Decimal(0),
            maximum_fidelity_error_pixels=Decimal(1),
            proven=True,
        ),
        blocking_review_items=(),
    )
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
        raw_figures=(figure,),
        curve_digitizations=(digitization,),
        semantic_proposals=(
            SemanticProposal(
                semantic_id=curve.id,
                rule_kind="curve",
                state="proposed",
                rule_sha256=canonical_model_sha256(curve),
                source_artifact_sha256=_aggregate_artifact_pairs(
                    ((curve.variants[0].id, curve.variants[0].reviewed_artifact_sha256),)
                ),
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
        raw_figures=draft.raw_figures,
        curve_digitizations=draft.curve_digitizations,
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
    assert model.draft.raw_figures == draft.raw_figures
    assert len(model.draft.curve_digitizations) == 1
    assert model.draft.curve_digitizations[0].conservatism is not None
    assert model.draft.curve_digitizations[0].conservatism.proven is True


def test_unsafe_breakpoint_correction_is_rejected(draft) -> None:
    model = CurveReviewModel(draft)
    with pytest.raises(ApprovalError, match="conservative"):
        model.set_breakpoint(
            VARIANT_ID,
            1,
            CurvePoint(x=Decimal(10), y=Decimal(80)),
            actor="Synthetic Reviewer",
            notes="Attempt an unsafe upward edit.",
        )


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


def test_each_variant_requires_an_exact_review(draft) -> None:
    first = draft.curves[0].variants[0]
    second = first.model_copy(
        update={
            "id": f"{ids.DVC_FAULT_TIME_VOLTAGE}.second",
            "selector": first.selector.model_copy(update={"voltage_basis": "dc"}),
        }
    )
    rule = draft.curves[0].model_copy(update={"variants": (first, second)})
    proposal = draft.semantic_proposals[0].model_copy(
        update={
            "rule_sha256": canonical_model_sha256(rule),
            "source_artifact_sha256": _aggregate_artifact_pairs(
                tuple(
                    (variant.id, variant.reviewed_artifact_sha256)
                    for variant in rule.variants
                )
            ),
            "state": "proposed",
        }
    )
    model = CurveReviewModel(
        draft.model_copy(
            update={
                "curves": (rule,),
                "curve_digitizations": (
                    draft.curve_digitizations[0].model_copy(
                        update={
                            "proposed_rule": draft.curve_digitizations[0]
                            .proposed_rule.model_copy(update={"variants": (first, second)})
                        }
                    ),
                ),
                "semantic_proposals": (proposal,),
            }
        )
    )

    model.review_variant(
        first.id,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the first variant.",
    )
    assert model.draft.semantic_proposals[0].state == "proposed"
    assert model.can_approve is False

    model.review_variant(
        second.id,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the second variant.",
    )
    assert model.draft.semantic_proposals[0].state == "reviewed"
    assert model.can_approve is True


def test_calibration_correction_targets_one_figure_and_reproves(draft) -> None:
    model = CurveReviewModel(draft)
    before = model.draft.curve_digitizations[0].calibration
    assert before is not None
    changed_axis = before.x.model_copy(update={"residual_pixels": Decimal("0.1")})
    model.set_calibration(
        54,
        "x",
        changed_axis,
        actor="Synthetic Reviewer",
        notes="Nudge the synthetic x calibration.",
    )
    after = model.draft.curve_digitizations[0]
    assert after.calibration is not None
    assert after.calibration.x == changed_axis
    assert after.calibration.y == before.y
    assert after.conservatism is not None and after.conservatism.proven
    assert model.draft.raw_figures == draft.raw_figures


def test_trace_association_is_source_scoped_and_reproved(draft) -> None:
    original = draft.raw_figures[0].traces[0]
    alternate = original.model_copy(update={"id": "alternate-trace"})
    figure = draft.raw_figures[0].model_copy(update={"traces": (original, alternate)})
    changed = draft.model_copy(update={"raw_figures": (figure,)})
    digest = _content_digest(
        changed.tables,
        changed.formulas,
        changed.mappings,
        changed.review_items,
        changed.raw_grids,
        changed.raw_clause_fragments,
        changed.manifest.source_documents,
        changed.source_identities,
        changed.review_resolutions,
        changed.extracted_equations,
        curves=changed.curves,
        raw_figures=changed.raw_figures,
        curve_digitizations=changed.curve_digitizations,
    )
    changed = changed.model_copy(
        update={
            "manifest": changed.manifest.model_copy(
                update={
                    "approval_records": tuple(
                        record.model_copy(update={"notes": f"content:{digest}"})
                        if record.action == "extraction" and record.notes.startswith("content:")
                        else record
                        for record in changed.manifest.approval_records
                    )
                }
            )
        }
    )
    model = CurveReviewModel(changed)

    model.associate_trace(
        alternate.id,
        VARIANT_ID,
        actor="Synthetic Reviewer",
        notes="Associate the alternate synthetic trace.",
    )

    assert model.draft.curve_trace_associations[0].trace_id == alternate.id
    assert model.draft.curve_digitizations[0].conservatism is not None
    assert model.draft.curve_digitizations[0].conservatism.proven


def test_cross_figure_trace_association_is_rejected(draft) -> None:
    other = draft.raw_figures[0].model_copy(
        update={
            "source": SOURCE.model_copy(update={"page": 55, "figure": "SF-6"}),
            "traces": (
                draft.raw_figures[0].traces[0].model_copy(update={"id": "other-trace"}),
            ),
            "artifact_sha256": "b" * 64,
        }
    )
    model = CurveReviewModel(
        draft.model_copy(update={"raw_figures": (*draft.raw_figures, other)})
    )
    with pytest.raises(ApprovalError, match="source figure"):
        model.associate_trace(
            "other-trace",
            VARIANT_ID,
            actor="Synthetic Reviewer",
            notes="Attempt a cross-figure association.",
        )


def test_manual_entry_is_gated_by_blocking_failure_or_rejection(draft) -> None:
    model = CurveReviewModel(draft)
    assert model.manual_entry_enabled is False

    model.reject_variant(
        VARIANT_ID,
        actor="Synthetic Reviewer",
        notes="Automatic reconstruction needs manual replacement.",
    )
    assert model.manual_entry_enabled is True

    blocked_digitization = draft.curve_digitizations[0].model_copy(
        update={
            "proposed_rule": None,
            "conservatism": None,
            "blocking_review_items": (draft.review_items[0],),
        }
    )
    blocked = CurveReviewModel(
        draft.model_copy(update={"curve_digitizations": (blocked_digitization,)})
    )
    assert blocked.manual_entry_enabled is True


def _local_pdf_draft(draft: ImportedRuleDraft, path) -> ImportedRuleDraft:
    writer = PdfWriter()
    for _ in range(54):
        writer.add_blank_page(width=300, height=300)
    with path.open("wb") as target:
        writer.write(target)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    source_document = draft.manifest.source_documents[0].model_copy(update={"sha256": digest})
    identity = draft.source_identities[0].model_copy(update={"sha256": digest})
    return draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={"source_documents": (source_document,)}
            ),
            "source_identities": (identity,),
        }
    )


def test_dialog_loads_verified_local_pdf_and_curve_overlay(qtbot, draft, tmp_path) -> None:
    path = tmp_path / "synthetic-curves.pdf"
    local = _local_pdf_draft(draft, path)
    dialog = CurveReviewDialog(
        local,
        actor="Synthetic Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert dialog.source_loaded is True
    assert isinstance(dialog.overlay_item, QGraphicsPathItem)
    assert dialog.overlay_item.path().elementCount() == 3
    dialog.set_overlay_visible(False)
    assert dialog.overlay_item.isVisible() is False


def test_dialog_rejects_local_pdf_sha_mismatch(qtbot, draft, tmp_path) -> None:
    path = tmp_path / "wrong.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as target:
        writer.write(target)

    with pytest.raises(ApprovalError, match="SHA-256"):
        CurveReviewDialog(
            draft,
            actor="Synthetic Reviewer",
            pdf_paths={"SYNTHETIC": path},
        )


def test_rules_manager_opens_curve_review_for_current_draft(
    qtbot, draft, tmp_path, monkeypatch
) -> None:
    path = tmp_path / "synthetic-curves.pdf"
    local = _local_pdf_draft(draft, path)
    window = RulesManagerWindow()
    qtbot.addWidget(window)
    window.set_draft(local)
    window._draft_pdfs = {"SYNTHETIC": path}
    opened: list[ImportedRuleDraft] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.CurveReviewDialog.exec",
        lambda dialog: opened.append(dialog.draft) or 0,
    )

    assert window.curve_review_enabled is True
    qtbot.mouseClick(window._review_curves_button, Qt.MouseButton.LeftButton)
    assert opened == [local]


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


def test_stale_digitization_proof_blocks_approval(draft) -> None:
    model = CurveReviewModel(draft)
    model.review_variant(
        VARIANT_ID,
        actor="Synthetic Curve Reviewer",
        notes="Reviewed the synthetic curve.",
    )
    digitization = model.draft.curve_digitizations[0]
    assert digitization.proposed_rule is not None
    stale_variant = digitization.proposed_rule.variants[0].model_copy(
        update={
            "points": (
                digitization.proposed_rule.variants[0].points[0],
                CurvePoint(x=Decimal(10), y=Decimal(30)),
                digitization.proposed_rule.variants[0].points[2],
            )
        }
    )
    stale = digitization.model_copy(
        update={
            "proposed_rule": digitization.proposed_rule.model_copy(
                update={"variants": (stale_variant,)}
            )
        }
    )
    tampered = model.draft.model_copy(update={"curve_digitizations": (stale,)})
    assert any(
        item.code == "CURVE_VARIANT_REVIEW_REQUIRED"
        for item in approval_blockers(tampered)
    )
