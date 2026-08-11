"""Curve review model tests with synthetic recipe data only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton

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
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_peak",
            dvc_context="as",
            environment_context="wet",
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
        for index in (1, 2, 3)
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


def _submit_calibration_dialog(
    qtbot,
    dialog: CurveReviewDialog,
    values: tuple[str, str, str, str],
) -> None:
    """Drive the real two-click and modal bounds-entry path."""

    dialog.notes_edit.setText("Reviewed synthetic plot.")
    dialog.begin_calibration()
    first = dialog._view.mapFromScene(QPointF(20, 10))
    qtbot.mouseClick(dialog._view.viewport(), Qt.MouseButton.LeftButton, pos=first)

    def fill_bounds() -> None:
        active = QApplication.activeModalWidget()
        assert isinstance(active, QDialog)
        fields = active.findChildren(QLineEdit)
        assert len(fields) == 4
        for field, value in zip(fields, values, strict=True):
            field.setText(value)
        active.accept()

    QTimer.singleShot(0, fill_bounds)
    second = dialog._view.mapFromScene(QPointF(320, 210))
    qtbot.mouseClick(dialog._view.viewport(), Qt.MouseButton.LeftButton, pos=second)


@pytest.fixture
def local_manual_draft(
    manual_draft: ImportedRuleDraft, tmp_path
) -> tuple[ImportedRuleDraft, Path]:
    path = tmp_path / "synthetic-curves.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=300)
    with path.open("wb") as target:
        writer.write(target)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    document = manual_draft.manifest.source_documents[0].model_copy(
        update={"sha256": digest}
    )
    draft = manual_draft.model_copy(
        update={
            "manifest": manual_draft.manifest.model_copy(
                update={"source_documents": (document,)}
            )
        }
    )
    content_digest = _content_digest(
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
    draft = draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={
                    "approval_records": (
                        *draft.manifest.approval_records[:2],
                        draft.manifest.approval_records[2].model_copy(
                            update={"notes": f"content:{content_digest}"}
                        ),
                    )
                }
            )
        }
    )
    model = CurveReviewModel(draft)
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
    return model.draft, path


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


def test_dialog_exposes_manual_controls_without_retired_reconstruction_actions(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Manual curve review"
    assert "Accessible circuit" in dialog.current_variant_label
    assert dialog.point_table.columnCount() == 2
    assert dialog.point_table.horizontalHeaderItem(0).text() == "X (ms)"
    assert dialog.calibration_button.text() == "Set plot and axes…"
    assert dialog.save_points_button.text() == "Save points"
    assert dialog.accept_variant_button.text() == "Accept variant"
    assert not hasattr(dialog, "_trace_button")
    assert not hasattr(dialog, "_breakpoint_button")
    assert not hasattr(dialog, "_segment_button")
    assert not hasattr(dialog, "_reject_button")


def _assert_source_failure_blocks_mutation(dialog: CurveReviewDialog) -> None:
    assert dialog.source_loaded is False
    assert "source unavailable" in dialog.status_text.lower()
    assert dialog.point_table.isEnabled() is False
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
    for label in (
        "Add point",
        "Remove point",
        "Set plot and axes…",
        "Save points",
        "Accept variant",
    ):
        assert buttons[label].isEnabled() is False


def test_missing_source_file_keeps_dialog_constructible_and_blocked(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    path.unlink()

    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    _assert_source_failure_blocks_mutation(dialog)
    assert "could not be read" in dialog.status_text.lower()


def test_source_hash_mismatch_keeps_dialog_constructible_and_blocked(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    document = draft.manifest.source_documents[0].model_copy(
        update={"sha256": "f" * 64}
    )
    draft = draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={"source_documents": (document,)}
            )
        }
    )

    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    _assert_source_failure_blocks_mutation(dialog)
    assert "sha-256 does not match" in dialog.status_text.lower()


def test_source_render_failure_keeps_dialog_constructible_and_blocked(
    qtbot,
    local_manual_draft: tuple[ImportedRuleDraft, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft, path = local_manual_draft

    def fail_render(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic renderer failure")

    monkeypatch.setattr("insulation_coordination.ui.curve_review.pdfplumber.open", fail_render)

    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    _assert_source_failure_blocks_mutation(dialog)
    assert "synthetic renderer failure" in dialog.status_text.lower()


def test_table_edit_redraws_the_source_aligned_overlay_without_saving(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    dialog.set_point_text(1, "10", "25")

    assert dialog.point_text(1) == ("10", "25")
    assert dialog.overlay_path.elementCount() == dialog.point_table.rowCount()
    assert dialog.draft == draft


def test_transformed_image_source_uses_the_same_scene_coordinates_as_vector_source(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    vector_dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(vector_dialog)
    figure = draft.raw_figures[0]
    raster_figure = RawFigure(
        source=figure.source,
        source_mode="image_xobject",
        source_bbox=figure.source_bbox,
        pixel_size=(800, 600),
        transform=(
            Decimal(2),
            Decimal("0.25"),
            Decimal("-0.5"),
            Decimal(-3),
            Decimal(40),
            Decimal(250),
        ),
        artifact_sha256=figure.artifact_sha256,
    )
    raster_dialog = CurveReviewDialog(
        draft.model_copy(update={"raw_figures": (raster_figure,)}),
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(raster_dialog)

    assert raster_dialog._plot_item is not None
    assert vector_dialog._plot_item is not None
    assert raster_dialog._plot_item.rect() == vector_dialog._plot_item.rect()
    assert raster_dialog.point_handle_positions == vector_dialog.point_handle_positions
    assert tuple(
        (raster_dialog.overlay_path.elementAt(index).x,
         raster_dialog.overlay_path.elementAt(index).y)
        for index in range(raster_dialog.overlay_path.elementCount())
    ) == tuple(
        (vector_dialog.overlay_path.elementAt(index).x,
         vector_dialog.overlay_path.elementAt(index).y)
        for index in range(vector_dialog.overlay_path.elementCount())
    )


def _review_variants(
    draft: ImportedRuleDraft,
    variants: tuple[tuple[str, Decimal, Decimal], ...],
) -> ImportedRuleDraft:
    model = CurveReviewModel(draft)
    for variant_id, start_y, end_y in variants:
        if not any(
            variant.id == variant_id
            for rule in model.draft.curves
            for variant in rule.variants
        ):
            model.replace_points(
                variant_id,
                (
                    CurvePoint(x=Decimal(1), y=start_y),
                    CurvePoint(x=Decimal(1000), y=end_y),
                ),
                actor="Reviewer",
                notes="Entered synthetic points.",
            )
        model.review_variant(
            variant_id,
            actor="Reviewer",
            notes="Reviewed synthetic points.",
        )
    return model.draft


def test_overlay_has_no_sibling_path_without_a_current_sibling_review(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert dialog._sibling_items == []
    assert dialog.point_handle_count == 2


def test_overlay_renders_one_current_sibling_in_a_secondary_style(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    draft = _review_variants(
        draft,
        (("synthetic.curve.5.2", Decimal(80), Decimal(10)),),
    )
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert len(dialog._sibling_items) == 1
    assert dialog._sibling_items[0].pen().color().name() != "#e53935"
    assert dialog.overlay_item.pen().color().name() == "#e53935"
    assert dialog.point_handle_count == 2


def test_overlay_renders_multiple_current_siblings(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    draft = _review_variants(
        draft,
        (
            ("synthetic.curve.5.2", Decimal(80), Decimal(10)),
            ("synthetic.curve.5.3", Decimal(60), Decimal(5)),
        ),
    )
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert len(dialog._sibling_items) == 2
    assert dialog.point_handle_count == 2


def test_selector_switch_moves_handles_to_selected_curve_and_keeps_sibling_secondary(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    draft = _review_variants(
        draft,
        (
            ("synthetic.curve.5.1", Decimal(100), Decimal(20)),
            ("synthetic.curve.5.2", Decimal(80), Decimal(10)),
        ),
    )
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    first_selected = dialog.overlay_path.elementAt(0).y
    first_sibling = dialog._sibling_items[0].path().elementAt(0).y

    dialog._variant_selector.setCurrentIndex(1)

    assert dialog.overlay_path.elementAt(0).y == pytest.approx(first_sibling)
    assert dialog._sibling_items[0].path().elementAt(0).y == pytest.approx(
        first_selected
    )
    assert dialog.point_handle_count == 2


def test_handle_move_updates_table_with_source_axis_values(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    dialog.move_handle(1, Decimal(320), Decimal(210))

    assert dialog.point_text(1) == ("1000", "1")
    assert dialog.overlay_path.elementCount() == dialog.point_table.rowCount()


def test_invalid_table_input_does_not_mutate_the_draft(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Correct synthetic points.")
    before = dialog.draft

    dialog.set_point_text(0, "not-a-number", "10")
    dialog.save_points()

    assert dialog.draft == before
    assert "valid decimal" in dialog.status_text.lower()


def test_save_rejects_points_that_do_not_cover_the_reviewed_x_domain(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Correct synthetic points.")
    dialog.set_point_text(0, "10", "100")
    before = dialog.draft

    dialog.save_points()

    assert dialog.draft == before
    assert "full reviewed x-axis domain" in dialog.status_text.lower()


def test_accept_rejects_unsaved_visible_table_changes(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Reviewed synthetic curve.")
    dialog.set_point_text(1, "10", "25")
    before = dialog.draft

    dialog.accept_variant()

    assert dialog.draft == before
    assert not dialog.draft.curve_variant_reviews
    assert "save points" in dialog.status_text.lower()


def test_accept_requires_a_current_manual_calibration(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft.model_copy(update={"curve_calibrations": ()}),
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Reviewed synthetic curve.")
    before = dialog.draft

    dialog.accept_variant()

    assert dialog.draft == before
    assert not dialog.draft.curve_variant_reviews
    assert "current manual calibration" in dialog.status_text.lower()


def test_one_valid_point_stays_visible_and_draggable_in_the_preview(
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
    dialog.add_point()
    dialog.set_point_text(0, "10", "25")

    assert dialog.point_handle_count == 1
    dialog.move_handle(0, Decimal(320), Decimal(210))
    assert dialog.point_text(0) == ("1000", "1")


@pytest.mark.parametrize(
    "rows",
    (
        (("1000", "25"), ("1", "25")),
        (("1000", "25"), ("1000", "25")),
    ),
)
def test_provisional_reversed_or_duplicate_x_keeps_every_handle_inside_plot(
    qtbot,
    local_manual_draft: tuple[ImportedRuleDraft, Path],
    rows: tuple[tuple[str, str], tuple[str, str]],
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.set_point_text(0, *rows[0])
    dialog.set_point_text(1, *rows[1])

    dialog.move_handle(1, Decimal(320), Decimal(110))

    assert dialog.point_handle_count == 2
    for x, y in dialog.point_handle_positions:
        assert Decimal(20) <= x <= Decimal(320)
        assert Decimal(10) <= y <= Decimal(210)
    before = dialog.draft
    dialog.notes_edit.setText("Provisional synthetic points.")
    dialog.save_points()
    assert dialog.draft == before
    assert "strictly increasing" in dialog.status_text.lower()


def test_two_click_calibration_dialog_parses_and_saves_decimal_bounds(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    _submit_calibration_dialog(qtbot, dialog, ("1", "1000", "1", "100"))

    assert dialog.status_text == "Plot calibration saved."
    calibration = dialog.draft.curve_calibrations[0].calibration
    assert (calibration.x_min, calibration.x_max) == (Decimal(1), Decimal(1000))
    assert (calibration.y_min, calibration.y_max) == (Decimal(1), Decimal(100))


@pytest.mark.parametrize(
    "values",
    (
        ("not-a-number", "1000", "1", "100"),
        ("1000", "1", "1", "100"),
    ),
)
def test_invalid_two_click_calibration_leaves_the_draft_unchanged(
    qtbot,
    local_manual_draft: tuple[ImportedRuleDraft, Path],
    values: tuple[str, str, str, str],
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    before = dialog.draft

    _submit_calibration_dialog(qtbot, dialog, values)

    assert dialog.draft == before
    assert "valid decimal axis bounds" in dialog.status_text.lower()


def test_scene_calibration_uses_two_click_positions_and_decimal_bounds(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Checked synthetic plot axes.")

    dialog.set_plot_and_axes(
        QPointF(20, 10),
        QPointF(320, 210),
        Decimal(1),
        Decimal(1000),
        Decimal(1),
        Decimal(100),
    )

    calibration = dialog.draft.curve_calibrations[0].calibration
    assert (calibration.left, calibration.top) == (Decimal(20), Decimal(10))
    assert (calibration.right, calibration.bottom) == (Decimal(320), Decimal(210))
    assert (calibration.x_min, calibration.y_max) == (Decimal(1), Decimal(100))


def test_save_and_accept_require_notes_before_mutating_the_draft(
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

    dialog.save_points()
    assert dialog.draft == before
    assert "notes are required" in dialog.status_text.lower()

    dialog.notes_edit.setText("Reviewed synthetic curve.")
    dialog.save_points()
    dialog.accept_variant()

    assert dialog.status_text == "Variant manually reviewed."
    assert dialog.draft.curve_variant_reviews[0].variant_id == "synthetic.curve.5.1"


def test_dialog_keeps_unfilled_semantic_slot_editable(
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
    assert dialog.point_table.rowCount() == 0
    dialog.add_point()
    assert dialog.point_table.rowCount() == 1
    dialog.remove_point()
    assert dialog.point_table.rowCount() == 0
    assert "No points entered" in dialog._status.text()


def test_empty_manual_draft_lists_every_recipe_slot(manual_draft: ImportedRuleDraft) -> None:
    entries = CurveReviewModel(manual_draft).variant_entries

    assert tuple(identifier for _label, identifier in entries) == (
        "synthetic.curve.5.1",
        "synthetic.curve.5.2",
        "synthetic.curve.5.3",
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
