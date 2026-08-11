"""Curve review model: local-only maintainer corrections over reviewed curves.

Every mutation delegates to the importer's correction functions, so each change
records an audited correction and resets the aggregate proposal. No source pixels
are stored; the overlay decodes the current local PDF crop in memory only.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pdfplumber
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.domain.rules import (
    CurvePoint,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    SourceReference,
)
from insulation_coordination.rules.importer import canonical_model_sha256
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    _manual_curve_review_is_current,
    _source_matches,
)
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    RawFigure,
    pixel_to_source_point,
    source_point_to_pixel,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    _manual_reviewed_artifact_sha256,
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

    def source_x_scale(self, variant_id: str) -> Decimal:
        """Return the one conversion from a figure's source X unit to runtime X."""

        for recipe in recipe_registry.RECIPES:
            for spec in recipe.curves:
                for index, _selector in enumerate(spec.variant_slots, start=1):
                    if variant_id != f"{spec.semantic_id}.{spec.figure}.{index}":
                        continue
                    source_unit = spec.x_source_unit or spec.x_unit
                    if source_unit == spec.x_unit:
                        return Decimal(1)
                    if (source_unit, spec.x_unit) == ("ms", "s"):
                        return Decimal("0.001")
                    raise ValueError("unsupported source-axis unit conversion")
        raise ValueError(f"unknown curve variant: {variant_id}")

    def source_x_unit(self, variant_id: str) -> str:
        """Return the duration unit shown in the source figure's point table."""

        for recipe in recipe_registry.RECIPES:
            for spec in recipe.curves:
                for index, _selector in enumerate(spec.variant_slots, start=1):
                    if variant_id == f"{spec.semantic_id}.{spec.figure}.{index}":
                        return spec.x_source_unit or spec.x_unit
        raise ValueError(f"unknown curve variant: {variant_id}")

    def input_origin(self, variant_id: str) -> Literal["empty", "automatic_suggestion"]:
        """Preserve whether an edited table began as an automatic suggestion."""

        inputs = tuple(
            item
            for item in self._draft.manual_curve_variant_inputs
            if item.variant_id == variant_id
        )
        if len(inputs) == 1:
            return inputs[0].input_origin
        return (
            "automatic_suggestion"
            if any(
                variant.id == variant_id
                for rule in self._draft.curves
                for variant in rule.variants
            )
            else "empty"
        )

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
    """Zoomable source view that can capture the two calibration clicks."""

    scene_clicked = Signal(QPointF)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.capture_clicks = False

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.capture_clicks:
            self.scene_clicked.emit(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)


class _CurvePointHandle(QGraphicsEllipseItem):
    """Movable point with dialog-owned ordering and bounds checks."""

    def __init__(
        self,
        index: int,
        constrain: Callable[[int, QPointF], QPointF],
        moved: Callable[[int, QPointF], None],
    ) -> None:
        super().__init__(-5, -5, 10, 10)
        self._index = index
        self._constrain = constrain
        self._moved = moved
        self.setBrush(QColor("#e53935"))
        self.setPen(QPen(QColor("#ffffff"), 1.0))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):  # type: ignore[no-untyped-def]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return self._constrain(self._index, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._moved(self._index, value)
        return super().itemChange(change, value)


class _AxisBoundsDialog(QDialog):
    """The four exact axis values paired with two scene-space corner clicks."""

    def __init__(self, parent: QDialog) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set plot axes")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.x_min = QLineEdit()
        self.x_max = QLineEdit()
        self.y_min = QLineEdit()
        self.y_max = QLineEdit()
        form.addRow("X minimum", self.x_min)
        form.addRow("X maximum", self.x_max)
        form.addRow("Y minimum", self.y_min)
        form.addRow("Y maximum", self.y_max)
        layout.addLayout(form)
        actions = QHBoxLayout()
        apply = QPushButton("Apply")
        apply.clicked.connect(self.accept)
        actions.addWidget(apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)


class CurveReviewDialog(QDialog):
    """Manually calibrate a verified local crop and author one selected curve."""

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
        self.setWindowTitle("Manual curve review")
        self.resize(1000, 760)
        self._model = CurveReviewModel(draft)
        self._actor = actor
        self._pdf_paths = {key: Path(value) for key, value in pdf_paths.items()}
        self._pdf_passwords = dict(pdf_passwords or {})
        self._scene = QGraphicsScene(self)
        self._view = _CurveGraphicsView(self._scene)
        self._view.scene_clicked.connect(self._record_calibration_corner)
        self._overlay_item: QGraphicsPathItem | None = None
        self._sibling_items: list[QGraphicsPathItem] = []
        self._plot_item: QGraphicsRectItem | None = None
        self._handles: list[_CurvePointHandle] = []
        self._handle_rows: list[int] = []
        self._calibration_corners: list[QPointF] = []
        self._source_loaded = False
        self._syncing = False

        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Curve variant:"))
        self._variant_selector = QComboBox()
        for label, variant_id in self._model.variant_entries:
            self._variant_selector.addItem(label, variant_id)
        self._variant_selector.currentIndexChanged.connect(self._load_current_variant)
        selector_row.addWidget(self._variant_selector, 1)
        self._overlay_toggle = QCheckBox("Show semantic overlay")
        self._overlay_toggle.setChecked(True)
        self._overlay_toggle.toggled.connect(self.set_overlay_visible)
        selector_row.addWidget(self._overlay_toggle)
        layout.addLayout(selector_row)
        layout.addWidget(self._view, 1)

        self.point_table = QTableWidget(0, 2)
        self.point_table.setHorizontalHeaderLabels(("X (source unit)", "Y"))
        self.point_table.itemChanged.connect(self._table_changed)
        layout.addWidget(self.point_table)
        point_actions = QHBoxLayout()
        self.add_point_button = QPushButton("Add point")
        self.add_point_button.clicked.connect(self.add_point)
        point_actions.addWidget(self.add_point_button)
        self.remove_point_button = QPushButton("Remove point")
        self.remove_point_button.clicked.connect(self.remove_point)
        point_actions.addWidget(self.remove_point_button)
        self.calibration_button = QPushButton("Set plot and axes…")
        self.calibration_button.clicked.connect(self.begin_calibration)
        point_actions.addWidget(self.calibration_button)
        self.save_points_button = QPushButton("Save points")
        self.save_points_button.clicked.connect(self.save_points)
        point_actions.addWidget(self.save_points_button)
        layout.addLayout(point_actions)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Review notes (required for calibration, save, and acceptance)")
        layout.addWidget(self.notes_edit)
        actions = QHBoxLayout()
        self.accept_variant_button = QPushButton("Accept variant")
        self.accept_variant_button.clicked.connect(self.accept_variant)
        actions.addWidget(self.accept_variant_button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

        self._mutation_controls = (
            self.add_point_button,
            self.remove_point_button,
            self.calibration_button,
            self.save_points_button,
            self.accept_variant_button,
        )
        self._set_source_available(False)

        if self._variant_selector.count():
            self._load_current_variant(0)

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._model.draft

    @property
    def source_loaded(self) -> bool:
        return self._source_loaded

    @property
    def current_variant_label(self) -> str:
        return self._variant_selector.currentText()

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def overlay_item(self) -> QGraphicsPathItem:
        if self._overlay_item is None:
            raise RuntimeError("No curve overlay loaded")
        return self._overlay_item

    @property
    def overlay_path(self) -> QPainterPath:
        return self.overlay_item.path()

    @property
    def point_handle_count(self) -> int:
        """Number of individually valid table rows currently shown as handles."""

        return len(self._handles)

    @property
    def point_handle_positions(self) -> tuple[tuple[Decimal, Decimal], ...]:
        """Scene positions of the preview handles, in table-row order."""

        return tuple(
            (Decimal(str(handle.pos().x())), Decimal(str(handle.pos().y())))
            for handle in self._handles
        )

    def set_overlay_visible(self, visible: bool) -> None:
        for item in (
            self._overlay_item,
            self._plot_item,
            *self._sibling_items,
            *self._handles,
        ):
            if item is not None:
                item.setVisible(visible)

    def point_text(self, row: int) -> tuple[str, str]:
        return (
            self._table_text(row, 0),
            self._table_text(row, 1),
        )

    def set_point_text(self, row: int, x: str, y: str) -> None:
        self._set_table_text(row, 0, x)
        self._set_table_text(row, 1, y)
        if not self._syncing:
            self._redraw_from_table()

    def add_point(self) -> None:
        row = self.point_table.rowCount()
        self._syncing = True
        self.point_table.insertRow(row)
        self._set_table_text(row, 0, "")
        self._set_table_text(row, 1, "")
        self._syncing = False
        self.point_table.setCurrentCell(row, 0)

    def remove_point(self) -> None:
        row = self.point_table.currentRow()
        if row < 0:
            row = self.point_table.rowCount() - 1
        if row < 0:
            return
        self.point_table.removeRow(row)
        self._redraw_from_table()

    def begin_calibration(self) -> None:
        if not self._require_notes("calibration"):
            return
        self._calibration_corners.clear()
        self._view.capture_clicks = True
        self._status.setText("Click the plot's top-left corner, then its bottom-right corner.")

    def set_plot_and_axes(
        self,
        top_left: QPointF,
        bottom_right: QPointF,
        x_min: Decimal,
        x_max: Decimal,
        y_min: Decimal,
        y_max: Decimal,
    ) -> None:
        """Save the same calibration captured by the two-click interaction."""

        if not self._source_loaded:
            self._status.setText(
                "A verified local source must be loaded before calibration."
            )
            return
        if not self._require_notes("calibration"):
            return
        self._calibration_corners = [top_left, bottom_right]
        try:
            self._save_calibration(x_min, x_max, y_min, y_max)
        except (ApprovalError, ValueError) as error:
            self._status.setText(f"Enter valid decimal axis bounds: {error}")

    def save_points(self) -> None:
        if not self._require_notes("saving points"):
            return
        variant_id = self._variant_selector.currentData()
        if not isinstance(variant_id, str):
            self._status.setText("Choose a semantic curve variant first.")
            return
        try:
            points = self._table_points()
            self._model.replace_points(
                variant_id,
                points,
                actor=self._actor,
                notes=self.notes_edit.text().strip(),
                input_origin=self._model.input_origin(variant_id),
            )
        except (ApprovalError, InvalidOperation, ValueError) as error:
            self._status.setText(str(error))
            return
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())
        self._status.setText("Points saved; accept the variant after reviewing the overlay.")

    def accept_variant(self) -> None:
        if not self._require_notes("acceptance"):
            return
        variant = self._current_variant()
        error = self._acceptance_error(variant)
        if error is not None:
            self._status.setText(error)
            return
        assert variant is not None
        try:
            self._model.review_variant(
                variant.id,
                actor=self._actor,
                notes=self.notes_edit.text().strip(),
            )
        except (ApprovalError, ValueError) as error:
            self._status.setText(str(error))
            return
        self.draft_changed.emit(self._model.draft)
        self._status.setText("Variant manually reviewed.")

    def move_handle(self, row: int, x: Decimal, y: Decimal) -> None:
        """Move a selected handle in scene coordinates; used by deterministic UI tests."""

        try:
            index = self._handle_rows.index(row)
        except ValueError as error:
            raise IndexError("unknown curve point handle") from error
        if not 0 <= index < len(self._handles):
            raise IndexError("unknown curve point handle")
        self._handles[index].setPos(float(x), float(y))

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

    def _current_source(self, variant: FaultTimeVoltageVariant | None) -> SourceReference:
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
        self, source: SourceReference
    ) -> tuple[RawFigure, ManualPlotCalibration | None]:
        figures = tuple(
            figure
            for figure in self._model.draft.raw_figures
            if figure.source.document_id == source.document_id
            and figure.source.page == source.page
            and figure.source.figure == source.figure
        )
        if len(figures) != 1:
            raise ApprovalError("curve overlay lacks a unique source figure")
        calibrations = tuple(
            item.calibration
            for item in self._model.draft.curve_calibrations
            if item.figure_artifact_sha256 == figures[0].artifact_sha256
        )
        if len(calibrations) > 1:
            raise ApprovalError("curve overlay has ambiguous calibration evidence")
        return figures[0], calibrations[0] if calibrations else None

    def _load_current_variant(self, _index: int) -> None:
        variant = self._current_variant()
        self._set_source_available(False)
        try:
            source = self._current_source(variant)
            path = self._verified_path(source)
            figure, calibration = self._figure_and_calibration(source)
            if source.page is None:
                raise ApprovalError("curve source page is unavailable")
            x0, top, x1, bottom = figure.source_bbox
            bbox = (float(x0), float(top), float(x1), float(bottom))
            with pdfplumber.open(
                path, password=self._pdf_passwords.get(path, "")
            ) as pdf:
                if not 1 <= source.page <= len(pdf.pages):
                    raise ApprovalError("curve source page is unavailable")
                rendered = pdf.pages[source.page - 1].crop(bbox).to_image(resolution=110)
                buffer = io.BytesIO()
                rendered.save(buffer, format="PNG")
            image = QImage()
            if not image.loadFromData(buffer.getvalue()):
                raise ApprovalError("local source PDF crop could not be decoded")
        except Exception as error:  # noqa: BLE001 - block every PDF/render failure in the UI.
            self._block_source(error)
            return

        self._scene.clear()
        self._scene.addPixmap(QPixmap.fromImage(image))
        self._overlay_item = None
        self._sibling_items = []
        self._plot_item = None
        self._handles = []
        self._handle_rows = []
        self._populate_table(variant)
        self._redraw_from_table()
        self._scene.setSceneRect(0, 0, image.width(), image.height())
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._set_source_available(True)
        status = (
            f"Verified {source.standard} page {source.page}; "
            "source pixels remain local and are not stored in the draft."
        )
        if variant is None:
            status += " No points entered for this variant."
        if calibration is None:
            status += " Set the plot rectangle and log-axis bounds before saving points."
        self._status.setText(status)

    def _set_source_available(self, available: bool) -> None:
        self._source_loaded = available
        self.point_table.setEnabled(available)
        for control in self._mutation_controls:
            control.setEnabled(available)

    def _block_source(self, error: Exception) -> None:
        self._view.capture_clicks = False
        self._calibration_corners.clear()
        self._scene.clear()
        self._overlay_item = None
        self._sibling_items = []
        self._plot_item = None
        self._handles = []
        self._handle_rows = []
        self._syncing = True
        self.point_table.setRowCount(0)
        self._syncing = False
        detail = str(error).strip() or type(error).__name__
        self._status.setText(f"Source unavailable; manual editing is blocked: {detail}")

    def _populate_table(self, variant: FaultTimeVoltageVariant | None) -> None:
        self._syncing = True
        self.point_table.setRowCount(0)
        variant_id = self._variant_selector.currentData()
        if isinstance(variant_id, str):
            self.point_table.setHorizontalHeaderLabels(
                (f"X ({self._model.source_x_unit(variant_id)})", "Y")
            )
        if variant is not None:
            scale = self._model.source_x_scale(variant.id)
            for point in variant.points:
                row = self.point_table.rowCount()
                self.point_table.insertRow(row)
                self._set_table_text(row, 0, self._decimal_text(point.x / scale))
                self._set_table_text(row, 1, self._decimal_text(point.y))
        self._syncing = False

    def _record_calibration_corner(self, point: QPointF) -> None:
        if not self._view.capture_clicks:
            return
        self._calibration_corners.append(point)
        if len(self._calibration_corners) == 1:
            self._status.setText("Now click the plot's bottom-right corner.")
            return
        self._view.capture_clicks = False
        bounds = _AxisBoundsDialog(self)
        if bounds.exec() != QDialog.DialogCode.Accepted:
            self._status.setText("Calibration cancelled; draft was unchanged.")
            return
        try:
            self.set_plot_and_axes(
                self._calibration_corners[0],
                self._calibration_corners[1],
                Decimal(bounds.x_min.text().strip()),
                Decimal(bounds.x_max.text().strip()),
                Decimal(bounds.y_min.text().strip()),
                Decimal(bounds.y_max.text().strip()),
            )
        except InvalidOperation as error:
            self._status.setText(f"Enter valid decimal axis bounds: {error}")

    def _save_calibration(
        self, x_min: Decimal, x_max: Decimal, y_min: Decimal, y_max: Decimal
    ) -> None:
        if not self._source_loaded:
            raise ApprovalError(
                "a verified local source must be loaded before calibration"
            )
        source = self._current_source(self._current_variant())
        figure, _calibration = self._figure_and_calibration(source)
        if source.figure is None:
            raise ApprovalError("curve source lacks a figure identifier")
        first, second = self._calibration_corners
        calibration = ManualPlotCalibration(
            figure_artifact_sha256=figure.artifact_sha256,
            left=Decimal(str(first.x())),
            top=Decimal(str(first.y())),
            right=Decimal(str(second.x())),
            bottom=Decimal(str(second.y())),
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        self._model.set_calibration(
            source.figure,
            calibration,
            actor=self._actor,
            notes=self.notes_edit.text().strip(),
        )
        self.draft_changed.emit(self._model.draft)
        self._redraw_from_table()
        self._status.setText("Plot calibration saved.")

    def _table_changed(self, _item: QTableWidgetItem) -> None:
        if not self._syncing:
            self._redraw_from_table()

    def _table_points(self) -> tuple[CurvePoint, ...]:
        points: list[CurvePoint] = []
        for row in range(self.point_table.rowCount()):
            try:
                point = CurvePoint(
                    x=Decimal(self._table_text(row, 0).strip()),
                    y=Decimal(self._table_text(row, 1).strip()),
                )
            except (InvalidOperation, ValueError) as error:
                raise ValueError("every point needs valid decimal X and Y values") from error
            if not point.x.is_finite() or not point.y.is_finite():
                raise ValueError("every point needs finite decimal X and Y values")
            points.append(point)
        if len(points) < 2:
            raise ValueError("at least two points are required")
        if any(right.x <= left.x for left, right in pairwise(points)):
            raise ValueError("point X values must be strictly increasing")
        return tuple(points)

    def _preview_points(self) -> tuple[tuple[int, CurvePoint], ...]:
        """Return each independently valid table row without save-only constraints."""

        points: list[tuple[int, CurvePoint]] = []
        for row in range(self.point_table.rowCount()):
            try:
                point = CurvePoint(
                    x=Decimal(self._table_text(row, 0).strip()),
                    y=Decimal(self._table_text(row, 1).strip()),
                )
            except (InvalidOperation, ValueError):
                continue
            if point.x.is_finite() and point.y.is_finite():
                points.append((row, point))
        return tuple(points)

    def _redraw_from_table(self) -> None:
        source = self._current_source(self._current_variant())
        _figure, calibration = self._figure_and_calibration(source)
        points = self._preview_points()
        self._remove_overlay()
        path = QPainterPath()
        if calibration is not None:
            self._plot_item = self._scene.addRect(
                float(calibration.left),
                float(calibration.top),
                float(calibration.right - calibration.left),
                float(calibration.bottom - calibration.top),
                QPen(QColor("#1976d2"), 1.0),
            )
            for sibling in self._reviewed_siblings(source):
                sibling_path = QPainterPath()
                scale = self._model.source_x_scale(sibling.id)
                for point in sibling.points:
                    x, y = source_point_to_pixel(
                        CurvePoint(x=point.x / scale, y=point.y), calibration
                    )
                    if sibling_path.elementCount() == 0:
                        sibling_path.moveTo(float(x), float(y))
                    else:
                        sibling_path.lineTo(float(x), float(y))
                sibling_pen = QPen(QColor("#607d8b"), 1.5)
                sibling_pen.setStyle(Qt.PenStyle.DashLine)
                self._sibling_items.append(
                    self._scene.addPath(sibling_path, sibling_pen)
                )
            self._syncing = True
            try:
                for row, point in points:
                    try:
                        x, y = source_point_to_pixel(point, calibration)
                    except ValueError:
                        continue
                    position = QPointF(float(x), float(y))
                    if path.elementCount() == 0:
                        path.moveTo(position)
                    else:
                        path.lineTo(position)
                    handle = _CurvePointHandle(
                        row, self._constrain_handle, self._handle_moved
                    )
                    self._scene.addItem(handle)
                    self._handles.append(handle)
                    self._handle_rows.append(row)
                    handle.setPos(position)
            finally:
                self._syncing = False
        self._overlay_item = self._scene.addPath(path, QPen(QColor("#e53935"), 2.0))
        self.set_overlay_visible(self._overlay_toggle.isChecked())

    def _remove_overlay(self) -> None:
        for item in (
            self._overlay_item,
            self._plot_item,
            *self._sibling_items,
            *self._handles,
        ):
            if item is not None:
                self._scene.removeItem(item)
        self._overlay_item = None
        self._sibling_items = []
        self._plot_item = None
        self._handles = []
        self._handle_rows = []

    def _reviewed_siblings(
        self, source: SourceReference
    ) -> tuple[FaultTimeVoltageVariant, ...]:
        selected_id = self._variant_selector.currentData()
        return tuple(
            variant
            for rule in self._model.draft.curves
            for variant in rule.variants
            if variant.id != selected_id
            and _source_matches(variant.source, source)
            and _manual_curve_review_is_current(self._model.draft, variant)
        )

    def _constrain_handle(self, row: int, candidate: QPointF) -> QPointF:
        source = self._current_source(self._current_variant())
        _figure, calibration = self._figure_and_calibration(source)
        if calibration is None:
            return candidate
        left = float(calibration.left)
        right = float(calibration.right)
        top = float(calibration.top)
        bottom = float(calibration.bottom)
        x = min(max(candidate.x(), left), right)
        y = min(max(candidate.y(), top), bottom)
        gap = 0.000001
        index = self._handle_rows.index(row)
        if index:
            x = max(x, self._handles[index - 1].pos().x() + gap)
        if index + 1 < len(self._handles):
            x = min(x, self._handles[index + 1].pos().x() - gap)
        x = min(max(x, left), right)
        return QPointF(x, y)

    def _handle_moved(self, row: int, position: QPointF) -> None:
        if self._syncing:
            return
        source = self._current_source(self._current_variant())
        _figure, calibration = self._figure_and_calibration(source)
        if calibration is None:
            return
        try:
            point = pixel_to_source_point(
                Decimal(str(position.x())), Decimal(str(position.y())), calibration
            )
        except ValueError:
            return
        self._syncing = True
        self._set_table_text(row, 0, self._decimal_text(point.x))
        self._set_table_text(row, 1, self._decimal_text(point.y))
        self._syncing = False
        self._update_overlay_path()

    def _update_overlay_path(self) -> None:
        if self._overlay_item is None:
            return
        source = self._current_source(self._current_variant())
        _figure, calibration = self._figure_and_calibration(source)
        if calibration is None:
            return
        points = self._preview_points()
        path = QPainterPath()
        for _row, point in points:
            try:
                x, y = source_point_to_pixel(point, calibration)
            except ValueError:
                continue
            if path.elementCount() == 0:
                path.moveTo(float(x), float(y))
            else:
                path.lineTo(float(x), float(y))
        self._overlay_item.setPath(path)

    def _acceptance_error(self, variant: FaultTimeVoltageVariant | None) -> str | None:
        """Require stored manual provenance and an unchanged, currently visible table."""

        if variant is None:
            return "Save at least two valid points before accepting this variant."
        source = self._current_source(variant)
        figure, calibration = self._figure_and_calibration(source)
        calibrations = tuple(
            item
            for item in self._model.draft.curve_calibrations
            if item.figure_artifact_sha256 == figure.artifact_sha256
            and item.calibration.figure_artifact_sha256 == figure.artifact_sha256
            and item.calibration_sha256 == canonical_model_sha256(item.calibration)
        )
        if calibration is None or len(calibrations) != 1:
            return "A current manual calibration is required before accepting this variant."
        try:
            visible_points = self._table_points()
        except ValueError:
            return "Visible points are not ready; save points before accepting this variant."
        scale = self._model.source_x_scale(variant.id)
        stored_points = tuple(
            CurvePoint(x=point.x / scale, y=point.y) for point in variant.points
        )
        if visible_points != stored_points:
            return "Visible points have unsaved changes; save points before accepting."
        calibration_sha256 = calibrations[0].calibration_sha256
        source_artifact_sha256 = _manual_reviewed_artifact_sha256(
            figure, calibration_sha256
        )
        inputs = tuple(
            item
            for item in self._model.draft.manual_curve_variant_inputs
            if item.variant_id == variant.id
            and item.variant_sha256 == canonical_model_sha256(variant)
            and item.source_artifact_sha256 == source_artifact_sha256
            and item.calibration_sha256 == calibration_sha256
        )
        if (
            variant.reviewed_artifact_sha256 != source_artifact_sha256
            or len(inputs) != 1
        ):
            return "Saved points lack current manual provenance; save points before accepting."
        return None

    def _require_notes(self, action: str) -> bool:
        if self.notes_edit.text().strip():
            return True
        self._status.setText(f"Review notes are required before {action}.")
        return False

    def _table_text(self, row: int, column: int) -> str:
        item = self.point_table.item(row, column)
        return item.text() if item is not None else ""

    def _set_table_text(self, row: int, column: int, text: str) -> None:
        item = self.point_table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.point_table.setItem(row, column, item)
        item.setText(text)

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value, "f")


__all__ = ["CurveReviewDialog", "CurveReviewModel"]
