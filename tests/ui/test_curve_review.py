"""Curve review model tests with synthetic recipe data only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    CurvePoint,
    FaultTimeVoltageSelector,
    SourceDocument,
    SourceGeometryReference,
    SourceReference,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.curves import ManualPlotCalibration, RawFigure
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    _content_digest,
)
from insulation_coordination.rules.importer.identify import (
    CurveAuditSpec,
    StandardIdentity,
    StandardRecipe,
)
from insulation_coordination.ui.curve_review import (
    CurveReviewDialog,
    CurveReviewModel,
    curve_variant_label,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package


def test_variant_label_uses_selector_meaning_and_keeps_id_secondary() -> None:
    label = curve_variant_label(
        figure="5",
        variant_id="synthetic.curve.5.1",
        selector=FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="b",
            environment_context="dry",
        ),
    )

    assert label == (
        "Figure 5 — Accessible circuit · DC · DVC B · Dry "
        "(synthetic.curve.5.1)"
    )


@pytest.fixture
def manual_draft(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    identity = StandardIdentity(
        standard="SYNTHETIC",
        edition="1",
        sha256="1" * 64,
        page_count=1,
        recipe_id="synthetic-curves",
    )
    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=1,
        figure="5",
    )
    slots = (
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="b",
            environment_context="dry",
        ),
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="as",
            environment_context="dry",
        ),
    )
    recipe = StandardRecipe(
        id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        identity_claim_pattern="",
        expected_page_count=1,
        metadata_identity_fields=(),
        metadata_identity_anchors=(),
        identity_anchors=(),
        tables=(),
        formulas=(),
        mappings=(),
        curves=(
            CurveAuditSpec(
                semantic_id="synthetic.curve",
                figure="5",
                page_number=1,
                expected_bbox=(0.0, 0.0, 400.0, 300.0),
                x_quantity_kind="duration",
                x_unit="s",
                x_source_unit="ms",
                y_quantity_kind="voltage",
                y_unit="V",
                x_scale="log10",
                y_scale="log10",
                variant_slots=slots,
                permitted_segment_types=("continuous", "plateau"),
                permitted_interpolations=("log_log", "constant"),
            ),
        ),
        required_curves=("synthetic.curve",),
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    figure = RawFigure(
        source=source,
        source_mode="vector_path",
        source_bbox=(Decimal(0), Decimal(0), Decimal(400), Decimal(300)),
        pixel_size=None,
        transform=(
            Decimal(1),
            Decimal(0),
            Decimal(0),
            Decimal(1),
            Decimal(0),
            Decimal(0),
        ),
        ocr_tokens=(),
        traces=(),
        artifact_sha256="0" * 64,
    )
    items = tuple(
        ImportReviewItem(
            code=f"SYNTHETIC_CURVE_REVIEW_{index}",
            semantic_id=f"synthetic.curve.5.{index}",
            kind="curve",
            source=source.model_copy(
                update={"geometry": SourceGeometryReference(artifact_sha256="0" * 64)}
            ),
            expected_contract="Synthetic curve review.",
        )
        for index in (1, 2)
    )
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (
                    SourceDocument(
                        id=identity.recipe_id,
                        standard=identity.standard,
                        edition=identity.edition,
                        sha256=identity.sha256,
                    ),
                ),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        review_items=items,
        raw_grids=(),
        raw_figures=(figure,),
        source_identities=(identity,),
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
        raw_figures=draft.raw_figures,
    )
    recorded_at = datetime(2026, 8, 11, tzinfo=UTC)
    return draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={
                    "approval_records": (
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"identity:{identity.recipe_id}",
                        ),
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"layout:{identity.recipe_id}",
                        ),
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"content:{digest}",
                        ),
                    )
                }
            )
        }
    )


def _calibration() -> ManualPlotCalibration:
    return ManualPlotCalibration(
        figure_artifact_sha256="0" * 64,
        left=Decimal(20),
        top=Decimal(10),
        right=Decimal(320),
        bottom=Decimal(210),
        x_min=Decimal(1),
        x_max=Decimal(1000),
        y_min=Decimal(1),
        y_max=Decimal(100),
    )


@pytest.fixture
def local_manual_draft(
    manual_draft: ImportedRuleDraft, tmp_path
) -> tuple[ImportedRuleDraft, Path]:
    model = CurveReviewModel(manual_draft)
    model.set_calibration("5", _calibration(), actor="Reviewer", notes="Calibrated.")
    model.replace_points(
        "synthetic.curve.5.1",
        (
            CurvePoint(x=Decimal(1), y=Decimal(100)),
            CurvePoint(x=Decimal(1000), y=Decimal(20)),
        ),
        actor="Reviewer",
        notes="Entered synthetic points.",
    )
    path = tmp_path / "synthetic-curves.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=300)
    with path.open("wb") as target:
        writer.write(target)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    document = model.draft.manifest.source_documents[0].model_copy(
        update={"sha256": digest}
    )
    return (
        model.draft.model_copy(
            update={
                "manifest": model.draft.manifest.model_copy(
                    update={"source_documents": (document,)}
                )
            }
        ),
        path,
    )


def test_dialog_shows_semantic_selector_text_and_stable_variant_id(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert dialog.source_loaded is True
    assert dialog._variant_selector.currentText() == (
        "Figure 5 — Accessible circuit · DC · DVC B · Dry "
        "(synthetic.curve.5.1)"
    )
    assert dialog._variant_selector.currentData() == "synthetic.curve.5.1"


def test_transitional_dialog_disables_retired_controls_without_model_calls(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    before = dialog.draft

    assert all(
        not button.isEnabled()
        for button in (
            dialog._calibration_button,
            dialog._trace_button,
            dialog._breakpoint_button,
            dialog._segment_button,
            dialog._manual_button,
            dialog._reject_button,
        )
    )
    for callback in (
        dialog._correct_calibration,
        dialog._associate_trace,
        dialog._correct_breakpoint,
        dialog._correct_segment,
        dialog._enter_manual_points,
        dialog._reject_current,
    ):
        callback()

    assert dialog.draft == before
    assert not hasattr(CurveReviewModel, "associate_trace")


def test_dialog_keeps_unfilled_semantic_slot_empty_and_unreviewable(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    dialog._variant_selector.setCurrentIndex(1)

    assert dialog._variant_selector.currentData() == "synthetic.curve.5.2"
    assert dialog.source_loaded is True
    assert dialog.overlay_item.path().elementCount() == 0
    assert dialog._review_button.isEnabled() is False
    assert "No points entered" in dialog._status.text()


def test_empty_manual_draft_lists_every_recipe_slot(manual_draft: ImportedRuleDraft) -> None:
    entries = CurveReviewModel(manual_draft).variant_entries

    assert tuple(identifier for _label, identifier in entries) == (
        "synthetic.curve.5.1",
        "synthetic.curve.5.2",
    )
    assert entries[0][0].startswith("Figure 5 — Accessible circuit · DC · DVC B · Dry")


def test_point_replacement_is_available_without_rejection(
    manual_draft: ImportedRuleDraft,
) -> None:
    model = CurveReviewModel(manual_draft)
    model.set_calibration("5", _calibration(), actor="Reviewer", notes="Calibrated.")
    model.replace_points(
        "synthetic.curve.5.1",
        (
            CurvePoint(x=Decimal(1), y=Decimal(100)),
            CurvePoint(x=Decimal(1000), y=Decimal(20)),
        ),
        actor="Reviewer",
        notes="Entered synthetic points.",
    )

    assert model.draft.curves[0].variants[0].points


def test_review_variant_records_manual_review(manual_draft: ImportedRuleDraft) -> None:
    model = CurveReviewModel(manual_draft)
    model.set_calibration("5", _calibration(), actor="Reviewer", notes="Calibrated.")
    model.replace_points(
        "synthetic.curve.5.1",
        (
            CurvePoint(x=Decimal(1), y=Decimal(100)),
            CurvePoint(x=Decimal(1000), y=Decimal(20)),
        ),
        actor="Reviewer",
        notes="Entered synthetic points.",
    )
    model.review_variant(
        "synthetic.curve.5.1", actor="Reviewer", notes="Reviewed points."
    )

    assert model.draft.curve_variant_reviews[0].variant_id == "synthetic.curve.5.1"
