"""Curve review model tests with synthetic recipe data only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter
from PySide6.QtWidgets import QAbstractItemView, QPushButton

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
        x_min=Decimal(1),
        x_max=Decimal(1000),
        y_min=Decimal(1),
        y_max=Decimal(100),
    )


def _set_bounds_fields(
    dialog: CurveReviewDialog, values: tuple[str, str, str, str]
) -> None:
    for field, value in zip(
        (dialog.x_min_edit, dialog.x_max_edit, dialog.y_min_edit, dialog.y_max_edit),
        values,
        strict=True,
    ):
        field.setText(value)


def _apply_bounds(dialog: CurveReviewDialog, values: tuple[str, str, str, str]) -> None:
    dialog.notes_edit.setText("Read the synthetic axis bounds.")
    _set_bounds_fields(dialog, values)
    dialog.apply_axis_bounds()


def _sized_plot(dialog: CurveReviewDialog):
    """Give the plot a deterministic size before reading its vertices."""

    dialog.point_plot.resize(300, 200)
    return dialog.point_plot


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
    assert dialog.apply_bounds_button.text() == "Apply axis bounds"
    assert dialog.accept_variant_button.text() == "Accept variant"
    assert not hasattr(dialog, "save_points_button")
    assert not hasattr(dialog, "calibration_button")
    assert not hasattr(dialog, "mark_rectangle_button")
    assert not hasattr(dialog, "move_handle")
    assert not hasattr(dialog, "overlay_path")
    assert not hasattr(dialog, "_trace_button")
    assert not hasattr(dialog, "_breakpoint_button")
    assert not hasattr(dialog, "_segment_button")
    assert not hasattr(dialog, "_reject_button")


def _assert_source_failure_blocks_mutation(dialog: CurveReviewDialog) -> None:
    assert dialog.source_loaded is False
    assert "source unavailable" in dialog.status_text.lower()
    assert dialog.point_table.isEnabled() is False
    assert dialog._bounds_box.isEnabled() is False
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
    for label in (
        "Add point",
        "Remove point",
        "Apply axis bounds",
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


def test_source_block_prevents_late_axis_bound_mutation(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Attempted synthetic rebound.")
    before = dialog.draft
    path.unlink()

    dialog._load_current_variant(dialog._variant_selector.currentIndex())

    dialog.apply_axis_bounds()
    assert "must be loaded" in dialog.status_text.lower()
    dialog.set_axis_bounds(Decimal(1), Decimal(1000), Decimal(1), Decimal(100))

    assert dialog.draft == before
    assert dialog.point_plot.vertices == ()


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
    assert len(_sized_plot(dialog).vertices) == dialog.point_table.rowCount()
    assert dialog.draft == draft


def test_transformed_image_source_plots_the_same_points_as_a_vector_source(
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

    assert raster_dialog.source_loaded is True
    assert _sized_plot(raster_dialog).vertices == _sized_plot(vector_dialog).vertices
    assert tuple(
        raster_dialog.point_text(row)
        for row in range(raster_dialog.point_table.rowCount())
    ) == tuple(
        vector_dialog.point_text(row)
        for row in range(vector_dialog.point_table.rowCount())
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


def test_plot_has_no_sibling_curve_without_a_current_sibling_review(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    plot = _sized_plot(dialog)
    assert plot.sibling_vertices == ()
    assert len(plot.vertices) == 2


def test_plot_renders_one_current_sibling_alongside_the_selected_curve(
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

    plot = _sized_plot(dialog)
    assert len(plot.sibling_vertices) == 1
    assert plot.sibling_vertices[0] != plot.vertices
    assert len(plot.vertices) == 2


def test_sibling_toggle_hides_reviewed_sibling_curves(
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

    dialog.set_siblings_visible(False)

    plot = _sized_plot(dialog)
    assert plot.sibling_vertices == ()
    assert len(plot.vertices) == 2


def test_unfilled_selected_slot_still_plots_a_current_same_figure_sibling(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    draft = _review_variants(
        draft,
        (("synthetic.curve.5.1", Decimal(100), Decimal(20)),),
    )
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    dialog._variant_selector.setCurrentIndex(2)

    assert dialog.point_table.rowCount() == 0
    assert len(_sized_plot(dialog).sibling_vertices) == 1


def test_plot_renders_multiple_current_siblings(
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

    plot = _sized_plot(dialog)
    assert len(plot.sibling_vertices) == 2
    assert len(plot.vertices) == 2


def test_selector_switch_swaps_the_selected_curve_and_its_sibling(
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
    plot = _sized_plot(dialog)
    first_selected = plot.vertices
    first_sibling = plot.sibling_vertices[0]

    dialog._variant_selector.setCurrentIndex(1)

    plot = _sized_plot(dialog)
    assert plot.vertices == first_sibling
    assert plot.sibling_vertices[0] == first_selected


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


def test_accept_stores_the_visible_table_before_recording_the_review(
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
    dialog.set_point_text(1, "1000", "25")

    dialog.accept_variant()

    assert dialog.status_text == "Variant manually reviewed."
    variant = dialog.draft.curves[0].variants[0]
    assert variant.points[-1] == CurvePoint(x=Decimal(1), y=Decimal(25))
    assert dialog.draft.curve_variant_reviews[0].variant_id == "synthetic.curve.5.1"


def test_accept_reports_table_errors_without_recording_a_review(
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
    assert "full reviewed x-axis domain" in dialog.status_text.lower()


def test_accept_requires_applied_axis_bounds(
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
    assert dialog.point_table.rowCount() == 2
    assert "apply this figure's axis bounds" in dialog.status_text.lower()


def test_add_point_opens_the_new_row_for_typing(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    dialog.add_point()

    row = dialog.point_table.rowCount() - 1
    assert (dialog.point_table.currentRow(), dialog.point_table.currentColumn()) == (
        row,
        0,
    )
    assert dialog.point_table.state() == QAbstractItemView.State.EditingState


def test_one_valid_row_plots_one_point(
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

    assert len(_sized_plot(dialog).vertices) == 1


@pytest.mark.parametrize(
    "rows",
    (
        (("1000", "25"), ("1", "25")),
        (("1000", "25"), ("1000", "25")),
    ),
)
def test_provisional_reversed_or_duplicate_x_plots_but_never_saves(
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

    assert len(_sized_plot(dialog).vertices) == 2
    before = dialog.draft
    dialog.notes_edit.setText("Provisional synthetic points.")
    dialog.save_points()
    assert dialog.draft == before
    assert "strictly increasing" in dialog.status_text.lower()


@pytest.mark.parametrize(
    "values",
    (
        ("not-a-number", "1000", "1", "100"),
        ("1000", "1", "1", "100"),
    ),
)
def test_invalid_applied_axis_bounds_leave_the_draft_unchanged(
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

    _apply_bounds(dialog, values)

    assert dialog.draft == before
    assert "valid decimal axis bounds" in dialog.status_text.lower()


def test_axis_bound_fields_prefill_from_the_saved_calibration(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert (dialog.x_min_edit.text(), dialog.x_max_edit.text()) == ("1", "1000")
    assert (dialog.y_min_edit.text(), dialog.y_max_edit.text()) == ("1", "100")


def test_editing_one_bound_field_replaces_the_saved_calibration(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.notes_edit.setText("Corrected synthetic axis bounds.")
    dialog.y_max_edit.setText("200")

    dialog.apply_axis_bounds()

    assert dialog.status_text == "Axis bounds saved."
    assert len(dialog.draft.curve_calibrations) == 1
    calibration = dialog.draft.curve_calibrations[0].calibration
    assert calibration.y_max == Decimal(200)
    assert (calibration.x_min, calibration.x_max) == (Decimal(1), Decimal(1000))


def test_point_plot_previews_visible_points_inside_the_axis_bounds(
    qtbot, local_manual_draft: tuple[ImportedRuleDraft, Path]
) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)
    dialog.point_plot.resize(300, 200)

    assert len(dialog.point_plot.vertices) == 2

    dialog.add_point()
    dialog.set_point_text(2, "100", "50")
    assert len(dialog.point_plot.vertices) == 3

    dialog.set_point_text(2, "100", "500")
    assert len(dialog.point_plot.vertices) == 2


def test_programmatic_axis_bounds_save_the_same_decimal_values(
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

    dialog.set_axis_bounds(Decimal(1), Decimal(1000), Decimal(1), Decimal(200))

    calibration = dialog.draft.curve_calibrations[0].calibration
    assert (calibration.x_min, calibration.x_max) == (Decimal(1), Decimal(1000))
    assert (calibration.y_min, calibration.y_max) == (Decimal(1), Decimal(200))
    assert not hasattr(calibration, "left")


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
