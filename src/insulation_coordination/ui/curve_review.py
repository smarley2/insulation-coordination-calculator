"""Curve review model: local-only maintainer corrections over reviewed curves.

Every mutation delegates to the importer's correction functions, so each change
records an audited correction and resets the aggregate proposal. No source pixels
are stored; the overlay decodes the current local PDF crop in memory only.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from decimal import Decimal
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
    QInputDialog,
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
    recover_blocked_curve_figures,
    reject_curve_variant,
    replace_curve_breakpoint,
    replace_curve_points,
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

    def set_manual_points(
        self,
        variant_id: str,
        points: tuple[CurvePoint, ...],
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = replace_curve_points(
            self._draft,
            variant_id=variant_id,
            points=points,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def recover_blocked(
        self,
        replacements: tuple[
            tuple[int, str, PlotCalibration, tuple[CurvePoint, ...]], ...
        ],
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = recover_blocked_curve_figures(
            self._draft,
            replacements=replacements,
            actor=actor,
            notes=notes,
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
        if not draft.curves and draft.curve_digitizations:
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
        self._manual_button.setEnabled(self._model.manual_entry_enabled)
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

        has_variants = any(rule.variants for rule in draft.curves)
        for button in (
            self._calibration_button,
            self._trace_button,
            self._breakpoint_button,
            self._segment_button,
            self._reject_button,
            self._review_button,
        ):
            button.setEnabled(has_variants)
        if has_variants:
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
        source_width, source_height = figure.pixel_size or (
            max(1, image.width()),
            max(1, image.height()),
        )
        scale_x = image.width() / source_width
        scale_y = image.height() / source_height
        overlay = QPainterPath()
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

    def _required_notes(self) -> str | None:
        notes = self._notes.text().strip()
        return notes or None

    def _correct_calibration(self) -> None:
        notes = self._required_notes()
        if notes is None:
            return
        variant = self._current_variant()
        _figure, current = self._figure_and_calibration(variant)
        assert current is not None and variant.source.page is not None
        axis, accepted = QInputDialog.getItem(
            self, "Correct calibration", "Axis", ("x", "y"), editable=False
        )
        if not accepted:
            return
        existing = current.x if axis == "x" else current.y
        value, accepted = QInputDialog.getText(
            self,
            "Correct calibration",
            "slope, intercept, residual pixels, minor-grid pixels",
            text=(
                f"{existing.slope},{existing.intercept},"
                f"{existing.residual_pixels},{existing.minor_grid_spacing_pixels}"
            ),
        )
        if not accepted:
            return
        slope, intercept, residual, spacing = (
            Decimal(part.strip()) for part in value.split(",")
        )
        self._model.set_calibration(
            variant.source.page,
            axis,  # type: ignore[arg-type]
            AxisCalibration(
                scale="log10",
                slope=slope,
                intercept=intercept,
                residual_pixels=residual,
                minor_grid_spacing_pixels=spacing,
            ),
            actor=self._actor,
            notes=notes,
        )
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())

    def _associate_trace(self) -> None:
        notes = self._required_notes()
        if notes is None:
            return
        variant = self._current_variant()
        figure, _calibration = self._figure_and_calibration(variant)
        trace_id, accepted = QInputDialog.getItem(
            self,
            "Associate trace",
            "Source trace",
            tuple(trace.id for trace in figure.traces),
            editable=False,
        )
        if not accepted:
            return
        self._model.associate_trace(
            trace_id, variant.id, actor=self._actor, notes=notes
        )
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())

    def _correct_breakpoint(self) -> None:
        notes = self._required_notes()
        if notes is None:
            return
        variant = self._current_variant()
        index, accepted = QInputDialog.getInt(
            self,
            "Correct breakpoint",
            "Point index",
            0,
            0,
            len(variant.points) - 1,
        )
        if not accepted:
            return
        point = variant.points[index]
        value, accepted = QInputDialog.getText(
            self,
            "Correct breakpoint",
            "x, y engineering values",
            text=f"{point.x},{point.y}",
        )
        if not accepted:
            return
        x, y = (Decimal(part.strip()) for part in value.split(","))
        self._model.set_breakpoint(
            variant.id,
            index,
            CurvePoint(x=x, y=y),
            actor=self._actor,
            notes=notes,
        )
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())

    def _correct_segment(self) -> None:
        notes = self._required_notes()
        if notes is None:
            return
        variant = self._current_variant()
        index, accepted = QInputDialog.getInt(
            self,
            "Correct segment",
            "Segment index",
            0,
            0,
            len(variant.segments) - 1,
        )
        if not accepted:
            return
        interpolation, accepted = QInputDialog.getItem(
            self,
            "Correct segment",
            "Interpolation",
            ("log_log", "constant"),
            editable=False,
        )
        if not accepted:
            return
        segment = variant.segments[index]
        segment_type = "plateau" if interpolation == "constant" else "continuous"
        self._model.set_segment(
            variant.id,
            index,
            segment.start,
            segment.end,
            segment_type,  # type: ignore[arg-type]
            interpolation,  # type: ignore[arg-type]
            actor=self._actor,
            notes=notes,
        )
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())

    def _enter_manual_points(self) -> None:
        notes = self._required_notes()
        if notes is None or not self._model.manual_entry_enabled:
            return
        if not self._model.draft.curves:
            self._recover_blocked_figures(notes)
            return
        variant = self._current_variant()
        value, accepted = QInputDialog.getText(
            self,
            "Enter points manually",
            "Semicolon-separated x,y engineering points",
            text=";".join(f"{point.x},{point.y}" for point in variant.points),
        )
        if not accepted:
            return
        points = tuple(
            CurvePoint(
                x=Decimal(pair.split(",", 1)[0].strip()),
                y=Decimal(pair.split(",", 1)[1].strip()),
            )
            for pair in value.split(";")
            if pair.strip()
        )
        self._model.set_manual_points(
            variant.id,
            points,
            actor=self._actor,
            notes=notes,
        )
        self._manual_button.setEnabled(self._model.manual_entry_enabled)
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())

    def _recover_blocked_figures(self, notes: str) -> None:
        replacements: list[
            tuple[int, str, PlotCalibration, tuple[CurvePoint, ...]]
        ] = []
        for index, (figure, result) in enumerate(
            zip(
                self._model.draft.raw_figures,
                self._model.draft.curve_digitizations,
            )
        ):
            if result.proposed_rule is not None:
                continue
            if not figure.traces:
                self._status.setText(
                    f"Figure {figure.source.figure} has no recoverable source trace."
                )
                return
            trace_id, accepted = QInputDialog.getItem(
                self,
                f"Recover Figure {figure.source.figure}",
                "Source trace",
                tuple(trace.id for trace in figure.traces),
                editable=False,
            )
            if not accepted:
                return
            axes: list[AxisCalibration] = []
            for axis in ("x", "y"):
                value, accepted = QInputDialog.getText(
                    self,
                    f"Recover Figure {figure.source.figure}",
                    f"{axis}-axis: slope, intercept, residual pixels, minor-grid pixels",
                    text="0.01,0,0,10",
                )
                if not accepted:
                    return
                slope, intercept, residual, spacing = (
                    Decimal(part.strip()) for part in value.split(",")
                )
                axes.append(
                    AxisCalibration(
                        scale="log10",
                        slope=slope,
                        intercept=intercept,
                        residual_pixels=residual,
                        minor_grid_spacing_pixels=spacing,
                    )
                )
            value, accepted = QInputDialog.getText(
                self,
                f"Recover Figure {figure.source.figure}",
                "Semicolon-separated x,y engineering points",
            )
            if not accepted:
                return
            points = tuple(
                CurvePoint(
                    x=Decimal(pair.split(",", 1)[0].strip()),
                    y=Decimal(pair.split(",", 1)[1].strip()),
                )
                for pair in value.split(";")
                if pair.strip()
            )
            replacements.append(
                (
                    index,
                    trace_id,
                    PlotCalibration(x=axes[0], y=axes[1]),
                    points,
                )
            )
        self._model.recover_blocked(
            tuple(replacements), actor=self._actor, notes=notes
        )
        self._manual_button.setEnabled(False)
        self.draft_changed.emit(self._model.draft)
        self._variant_selector.clear()
        for rule in self._model.draft.curves:
            for variant in rule.variants:
                self._variant_selector.addItem(variant.id, variant.id)
        self._load_current_variant(0)

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
