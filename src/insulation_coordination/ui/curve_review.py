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
    CurveInterpolation,
    CurvePoint,
    CurveSegment,
    CurveSegmentType,
    FaultTimeVoltageVariant,
)
from insulation_coordination.rules.importer.approval import ApprovalError, approval_blockers
from insulation_coordination.rules.importer.curves import (
    AxisCalibration,
    PlotCalibration,
    RawFigure,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    associate_curve_trace,
    correct_curve_calibration,
    reject_curve_variant,
    replace_curve_breakpoint,
    replace_curve_segment,
    review_curve_variant,
)

if TYPE_CHECKING:
    from insulation_coordination.ui.rules_manager import RulesManagerWindow


class CurveReviewModel:
    """Review actions over one draft's reconstructed curve rule."""

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

    def set_breakpoint(
        self,
        variant_id: str,
        index: int,
        point: CurvePoint,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = replace_curve_breakpoint(
            self._draft,
            variant_id=variant_id,
            index=index,
            point=point,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def set_calibration(
        self,
        figure_page: int,
        axis: Literal["x", "y"],
        calibration: AxisCalibration,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        """Replace one axis calibration for exactly one source figure."""

        if axis not in {"x", "y"}:
            raise ValueError("axis must be x or y with an AxisCalibration")
        digitization = next(
            (
                item
                for item in self._draft.curve_digitizations
                if item.proposed_rule is not None
                and item.proposed_rule.source.page == figure_page
                and item.calibration is not None
            ),
            None,
        )
        if digitization is None or digitization.calibration is None:
            raise ValueError(f"unknown calibrated figure on page {figure_page}")
        changed = digitization.calibration.model_copy(update={axis: calibration})
        self._draft = correct_curve_calibration(
            self._draft,
            figure_page=figure_page,
            calibration=changed,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def set_segment(
        self,
        variant_id: str,
        index: int,
        start: int,
        end: int,
        segment_type: CurveSegmentType,
        interpolation: CurveInterpolation,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = replace_curve_segment(
            self._draft,
            variant_id=variant_id,
            index=index,
            segment=CurveSegment(
                start=start,
                end=end,
                segment_type=segment_type,
                interpolation=interpolation,
            ),
            actor=actor,
            notes=notes,
        )
        return self._draft

    def associate_trace(
        self,
        trace_id: str,
        variant_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = associate_curve_trace(
            self._draft,
            trace_id=trace_id,
            variant_id=variant_id,
            actor=actor,
            notes=notes,
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

    def reject_variant(
        self,
        variant_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = reject_curve_variant(
            self._draft, variant_id, actor=actor, notes=notes
        )
        return self._draft

    @property
    def manual_entry_enabled(self) -> bool:
        return bool(self._draft.curve_variant_rejections) or any(
            item.blocking_review_items for item in self._draft.curve_digitizations
        )

    @property
    def can_approve(self) -> bool:
        return not approval_blockers(self._draft)


class _CurveGraphicsView(QGraphicsView):
    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class CurveReviewDialog(QDialog):
    """Render a verified local source crop with a separate semantic curve overlay."""

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
        for rule in draft.curves:
            for variant in rule.variants:
                self._variant_selector.addItem(variant.id, variant.id)
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
        actions = QHBoxLayout()
        self._manual_button = QPushButton("Enter points manually…")
        self._manual_button.setEnabled(self._model.manual_entry_enabled)
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

        if self._variant_selector.count():
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

    def _current_variant(self) -> FaultTimeVoltageVariant:
        variant_id = self._variant_selector.currentData()
        return next(
            variant
            for rule in self._model.draft.curves
            for variant in rule.variants
            if variant.id == variant_id
        )

    def _verified_path(self, variant: FaultTimeVoltageVariant) -> Path:
        path = self._pdf_paths.get(variant.source.standard)
        if path is None:
            raise ApprovalError("local source PDF is unavailable")
        document = next(
            (
                item
                for item in self._model.draft.manifest.source_documents
                if item.id == variant.source.document_id
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
        self, variant: FaultTimeVoltageVariant
    ) -> tuple[RawFigure, PlotCalibration | None]:
        figures = tuple(
            figure
            for figure in self._model.draft.raw_figures
            if figure.source.document_id == variant.source.document_id
            and figure.source.page == variant.source.page
            and figure.source.figure == variant.source.figure
        )
        digitizations = tuple(
            item
            for item in self._model.draft.curve_digitizations
            if item.proposed_rule is not None
            and any(member.id == variant.id for member in item.proposed_rule.variants)
            and item.calibration is not None
        )
        if len(figures) != 1 or len(digitizations) != 1:
            raise ApprovalError("curve overlay lacks unique figure calibration evidence")
        return figures[0], digitizations[0].calibration

    def _load_current_variant(self, _index: int) -> None:
        variant = self._current_variant()
        path = self._verified_path(variant)
        figure, calibration = self._figure_and_calibration(variant)
        assert calibration is not None and variant.source.page is not None
        x0, top, x1, bottom = figure.source_bbox
        bbox = (float(x0), float(top), float(x1), float(bottom))
        with pdfplumber.open(path, password=self._pdf_passwords.get(path, "")) as pdf:
            rendered = pdf.pages[variant.source.page - 1].crop(bbox).to_image(resolution=110)
            buffer = io.BytesIO()
            rendered.save(buffer, format="PNG")
        image = QImage()
        if not image.loadFromData(buffer.getvalue()):
            raise ApprovalError("local source PDF crop could not be decoded")

        self._scene.clear()
        self._scene.addPixmap(QPixmap.fromImage(image))
        overlay = QPainterPath()
        for index, point in enumerate(variant.points):
            x = float((point.x.log10() - calibration.x.intercept) / calibration.x.slope)
            y = float(-((point.y.log10() - calibration.y.intercept) / calibration.y.slope))
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
        self._status.setText(
            f"Verified {variant.source.standard} page {variant.source.page}; "
            "source pixels remain local and are not stored in the draft."
        )

    def _review_current(self) -> None:
        notes = self._notes.text().strip()
        if not notes:
            return
        self._model.review_variant(
            self._current_variant().id,
            actor=self._actor,
            notes=notes,
        )
        self.draft_changed.emit(self._model.draft)

    def _reject_current(self) -> None:
        notes = self._notes.text().strip()
        if not notes:
            return
        self._model.reject_variant(
            self._current_variant().id,
            actor=self._actor,
            notes=notes,
        )
        self._manual_button.setEnabled(True)
        self.draft_changed.emit(self._model.draft)


__all__ = ["CurveReviewDialog", "CurveReviewModel"]
