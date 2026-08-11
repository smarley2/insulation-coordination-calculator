"""Curve review model: local-only maintainer corrections over reviewed curves.

Every mutation delegates to the importer's correction functions, so each change
records an audited correction and resets the aggregate proposal. No source pixels
are stored; the overlay decodes the current local PDF crop in memory only.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pdfplumber
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from insulation_coordination.domain.rules import (
    CurvePoint,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    SourceReference,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import ApprovalError
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    PlotCalibration,
    RawFigure,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    replace_manual_curve_variant,
    review_curve_variant,
    set_manual_curve_calibration,
)

if TYPE_CHECKING:
    from insulation_coordination.ui.rules_manager import RulesManagerWindow


def curve_variant_label(
    *,
    figure: str,
    variant_id: str,
    selector: FaultTimeVoltageSelector,
) -> str:
    """Return neutral UI text from typed selector fields."""

    subject = {
        "accessible_circuit": "Accessible circuit",
        "conductive_accessible_part": "Conductive accessible part",
    }[selector.subject]
    voltage = {
        "ac_rms": "AC RMS",
        "ac_peak": "AC peak",
        "ac_unspecified": "AC",
        "dc": "DC",
    }[selector.voltage_basis]
    fields = [subject, voltage]
    if selector.dvc_context is not None:
        fields.append(f"DVC {selector.dvc_context.upper()}")
    if selector.environment_context is not None:
        fields.append(selector.environment_context.replace("_", " ").title())
    return f"Figure {figure} — {' · '.join(fields)} ({variant_id})"


class CurveReviewModel:
    """Manual curve-review actions over one imported draft."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @classmethod
    def for_window(cls, window: RulesManagerWindow) -> CurveReviewModel | None:
        """Back the model with the draft currently selected in the Rules Manager."""

        draft = window.draft
        if draft is None:
            return None
        return cls(draft)

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    @property
    def variant_entries(self) -> tuple[tuple[str, str], ...]:
        """Recipe slots for available source figures, in recipe order."""

        entries: list[tuple[str, str]] = []
        for identity in self._draft.source_identities:
            for recipe in recipe_registry.RECIPES:
                if (
                    recipe.id != identity.recipe_id
                    or recipe.standard != identity.standard
                    or recipe.edition != identity.edition
                ):
                    continue
                for spec in recipe.curves:
                    if not any(
                        figure.source.standard == identity.standard
                        and figure.source.edition == identity.edition
                        and figure.source.page == spec.page_number
                        and figure.source.figure == spec.figure
                        for figure in self._draft.raw_figures
                    ):
                        continue
                    for index, selector in enumerate(spec.variant_slots, start=1):
                        variant_id = f"{spec.semantic_id}.{spec.figure}.{index}"
                        entries.append(
                            (
                                curve_variant_label(
                                    figure=spec.figure,
                                    variant_id=variant_id,
                                    selector=selector,
                                ),
                                variant_id,
                            )
                        )
        return tuple(entries)

    def set_calibration(
        self,
        figure: str,
        calibration: ManualPlotCalibration,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = set_manual_curve_calibration(
            self._draft,
            figure=figure,
            calibration=calibration,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def replace_points(
        self,
        variant_id: str,
        source_points: tuple[CurvePoint, ...],
        *,
        actor: str,
        notes: str,
        input_origin: Literal["empty", "automatic_suggestion"] = "empty",
    ) -> ImportedRuleDraft:
        self._draft = replace_manual_curve_variant(
            self._draft,
            variant_id=variant_id,
            source_points=source_points,
            actor=actor,
            notes=notes,
            input_origin=input_origin,
        )
        return self._draft

    def review_variant(
        self,
        variant_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        """Review the aggregate proposal after inspecting one variant."""

        rule = next(
            (rule for rule in self._draft.curves for v in rule.variants if v.id == variant_id),
            None,
        )
        if rule is None:
            raise ValueError(f"unknown curve variant: {variant_id}")
        self._draft = review_curve_variant(
            self._draft, variant_id, actor=actor, notes=notes
        )
        return self._draft

class _CurveGraphicsView(QGraphicsView):
    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class CurveReviewDialog(QDialog):
    """Render a verified local source crop with a separate semantic curve overlay."""

    # Transitional boundary: Task 5 replaces these automatic-correction controls with
    # the manual table/drag editor. Keep this dialog constructible, but do not recreate
    # removed CurveReviewModel methods merely to support the retired controls.

    draft_changed = Signal(object)

    def __init__(
        self,
        draft: ImportedRuleDraft,
        *,
        actor: str,
        pdf_paths: Mapping[str, Path],
        pdf_passwords: Mapping[Path, str] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Review reconstructed curves")
        self.resize(1000, 720)
        self._model = CurveReviewModel(draft)
        self._actor = actor
        self._pdf_paths = {key: Path(value) for key, value in pdf_paths.items()}
        self._pdf_passwords = dict(pdf_passwords or {})
        self._scene = QGraphicsScene(self)
        self._view = _CurveGraphicsView(self._scene)
        self._overlay_item: QGraphicsPathItem | None = None
        self._source_loaded = False

        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Curve variant:"))
        self._variant_selector = QComboBox()
        for label, variant_id in self._model.variant_entries:
            self._variant_selector.addItem(label, variant_id)
        if not self._model.variant_entries and draft.curve_digitizations:
            self._variant_selector.addItem("Blocked reconstruction — manual recovery", None)
        self._variant_selector.currentIndexChanged.connect(self._load_current_variant)
        selector_row.addWidget(self._variant_selector, 1)
        self._overlay_toggle = QCheckBox("Show semantic overlay")
        self._overlay_toggle.setChecked(True)
        self._overlay_toggle.toggled.connect(self.set_overlay_visible)
        selector_row.addWidget(self._overlay_toggle)
        layout.addLayout(selector_row)
        layout.addWidget(self._view, 1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Review or rejection notes (required)")
        layout.addWidget(self._notes)
        correction_actions = QHBoxLayout()
        self._calibration_button = QPushButton("Correct calibration…")
        self._calibration_button.clicked.connect(self._correct_calibration)
        correction_actions.addWidget(self._calibration_button)
        self._trace_button = QPushButton("Associate trace…")
        self._trace_button.clicked.connect(self._associate_trace)
        correction_actions.addWidget(self._trace_button)
        self._breakpoint_button = QPushButton("Correct breakpoint…")
        self._breakpoint_button.clicked.connect(self._correct_breakpoint)
        correction_actions.addWidget(self._breakpoint_button)
        self._segment_button = QPushButton("Correct segment…")
        self._segment_button.clicked.connect(self._correct_segment)
        correction_actions.addWidget(self._segment_button)
        layout.addLayout(correction_actions)
        actions = QHBoxLayout()
        self._manual_button = QPushButton("Enter points manually…")
        self._manual_button.setEnabled(False)
        self._manual_button.clicked.connect(self._enter_manual_points)
        actions.addWidget(self._manual_button)
        self._reject_button = QPushButton("Reject automatic reconstruction")
        self._reject_button.clicked.connect(self._reject_current)
        actions.addWidget(self._reject_button)
        self._review_button = QPushButton("Accept current variant")
        self._review_button.clicked.connect(self._review_current)
        actions.addWidget(self._review_button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

        has_current_variant = any(
            variant.id == self._variant_selector.currentData()
            for rule in draft.curves
            for variant in rule.variants
        )
        for button in (
            self._calibration_button,
            self._trace_button,
            self._breakpoint_button,
            self._segment_button,
            self._manual_button,
            self._reject_button,
        ):
            button.setEnabled(False)
        self._review_button.setEnabled(has_current_variant)
        if has_current_variant:
            self._load_current_variant(0)

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._model.draft

    @property
    def source_loaded(self) -> bool:
        return self._source_loaded

    @property
    def overlay_item(self) -> QGraphicsPathItem:
        if self._overlay_item is None:
            raise RuntimeError("No curve overlay loaded")
        return self._overlay_item

    def set_overlay_visible(self, visible: bool) -> None:
        if self._overlay_item is not None:
            self._overlay_item.setVisible(visible)

    def _current_variant(self) -> FaultTimeVoltageVariant | None:
        variant_id = self._variant_selector.currentData()
        return next(
            (
                variant
                for rule in self._model.draft.curves
                for variant in rule.variants
                if variant.id == variant_id
            ),
            None,
        )

    def _current_source(
        self, variant: FaultTimeVoltageVariant | None
    ) -> SourceReference:
        if variant is not None:
            return variant.source
        variant_id = self._variant_selector.currentData()
        sources = tuple(
            item.source
            for item in self._model.draft.review_items
            if item.kind == "curve" and item.semantic_id == variant_id
        )
        if len(sources) != 1:
            raise ApprovalError("curve selector lacks a unique source figure")
        return sources[0]

    def _verified_path(self, source: SourceReference) -> Path:
        path = self._pdf_paths.get(source.standard)
        if path is None:
            raise ApprovalError("local source PDF is unavailable")
        document = next(
            (
                item
                for item in self._model.draft.manifest.source_documents
                if item.id == source.document_id
            ),
            None,
        )
        if document is None:
            raise ApprovalError("curve source document is absent from the manifest")
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ApprovalError("local source PDF could not be read") from error
        if digest != document.sha256:
            raise ApprovalError("local source PDF SHA-256 does not match the manifest")
        return path

    def _figure_and_calibration(
        self,
        source: SourceReference,
        variant: FaultTimeVoltageVariant | None,
    ) -> tuple[RawFigure, PlotCalibration | None]:
        figures = tuple(
            figure
            for figure in self._model.draft.raw_figures
            if figure.source.document_id == source.document_id
            and figure.source.page == source.page
            and figure.source.figure == source.figure
        )
        digitizations = tuple(
            item
            for item in self._model.draft.curve_digitizations
            if variant is not None
            and item.proposed_rule is not None
            and any(member.id == variant.id for member in item.proposed_rule.variants)
            and item.calibration is not None
        )
        if len(figures) != 1:
            raise ApprovalError("curve overlay lacks a unique source figure")
        if len(digitizations) > 1:
            raise ApprovalError("curve overlay has ambiguous calibration evidence")
        return figures[0], digitizations[0].calibration if digitizations else None

    def _load_current_variant(self, _index: int) -> None:
        variant = self._current_variant()
        source = self._current_source(variant)
        self._review_button.setEnabled(variant is not None and bool(variant.points))
        path = self._verified_path(source)
        figure, calibration = self._figure_and_calibration(source, variant)
        assert source.page is not None
        x0, top, x1, bottom = figure.source_bbox
        bbox = (float(x0), float(top), float(x1), float(bottom))
        with pdfplumber.open(path, password=self._pdf_passwords.get(path, "")) as pdf:
            rendered = pdf.pages[source.page - 1].crop(bbox).to_image(resolution=110)
            buffer = io.BytesIO()
            rendered.save(buffer, format="PNG")
        image = QImage()
        if not image.loadFromData(buffer.getvalue()):
            raise ApprovalError("local source PDF crop could not be decoded")

        self._scene.clear()
        self._scene.addPixmap(QPixmap.fromImage(image))
        overlay = QPainterPath()
        if calibration is not None and variant is not None:
            source_width, source_height = figure.pixel_size or (
                max(1, image.width()),
                max(1, image.height()),
            )
            scale_x = image.width() / source_width
            scale_y = image.height() / source_height
            for index, point in enumerate(variant.points):
                x = (
                    float((point.x.log10() - calibration.x.intercept) / calibration.x.slope)
                    * scale_x
                )
                y = (
                    float(-((point.y.log10() - calibration.y.intercept) / calibration.y.slope))
                    * scale_y
                )
                if index == 0:
                    overlay.moveTo(x, y)
                else:
                    overlay.lineTo(x, y)
        self._overlay_item = self._scene.addPath(
            overlay, QPen(QColor("#e53935"), 2.0)
        )
        self._overlay_item.setVisible(self._overlay_toggle.isChecked())
        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._source_loaded = True
        status = (
            f"Verified {source.standard} page {source.page}; "
            "source pixels remain local and are not stored in the draft."
        )
        if variant is None:
            status += " No points entered for this variant."
        self._status.setText(status)

    def _review_current(self) -> None:
        notes = self._notes.text().strip()
        variant = self._current_variant()
        if not notes or variant is None:
            return
        self._model.review_variant(
            variant.id,
            actor=self._actor,
            notes=notes,
        )
        self.draft_changed.emit(self._model.draft)

    def _retired_correction(self) -> None:
        self._status.setText("Manual point editing is available in the updated review editor.")

    def _correct_calibration(self) -> None:
        self._retired_correction()

    def _associate_trace(self) -> None:
        self._retired_correction()

    def _correct_breakpoint(self) -> None:
        self._retired_correction()

    def _correct_segment(self) -> None:
        self._retired_correction()

    def _enter_manual_points(self) -> None:
        self._retired_correction()

    def _reject_current(self) -> None:
        self._retired_correction()


__all__ = ["CurveReviewDialog", "CurveReviewModel"]
