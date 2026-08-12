"""Curve review model: local-only maintainer corrections over reviewed curves.

Every mutation delegates to the importer's correction functions, so each change
records an audited correction and resets the aggregate proposal. No source pixels
are stored; the source view decodes the current local PDF crop in memory only.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pdfplumber
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
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
    """Zoomable read-only view of the verified source crop."""

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class _PointPlot(QWidget):
    """Read-only log-log plot of the table points, in reviewed axis units."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(200)
        self._bounds: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
        self._points: tuple[CurvePoint, ...] = ()
        self._siblings: tuple[tuple[CurvePoint, ...], ...] = ()
        self._siblings_visible = True

    def set_curve(
        self,
        bounds: tuple[Decimal, Decimal, Decimal, Decimal] | None,
        points: tuple[CurvePoint, ...],
        siblings: tuple[tuple[CurvePoint, ...], ...] = (),
    ) -> None:
        self._bounds = bounds
        self._points = points
        self._siblings = siblings
        self.update()

    def set_siblings_visible(self, visible: bool) -> None:
        self._siblings_visible = visible
        self.update()

    @property
    def vertices(self) -> tuple[tuple[float, float], ...]:
        """Widget positions of the plotted points, in table-row order."""

        return self._widget_points(self._points)

    @property
    def sibling_vertices(self) -> tuple[tuple[tuple[float, float], ...], ...]:
        """Widget positions of each reviewed sibling curve currently drawn."""

        if not self._siblings_visible:
            return ()
        return tuple(self._widget_points(points) for points in self._siblings)

    def _calibration(self) -> ManualPlotCalibration | None:
        if self._bounds is None:
            return None
        x_min, x_max, y_min, y_max = self._bounds
        try:
            return ManualPlotCalibration(
                # ponytail: display-only; this hash never reaches the draft.
                figure_artifact_sha256="0" * 64,
                x_min=x_min,
                x_max=x_max,
                y_min=y_min,
                y_max=y_max,
            )
        except ValueError:
            return None

    def _rectangle(self) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
        left, top = 52.0, 12.0
        right, bottom = self.width() - 14.0, self.height() - 26.0
        if right - left < 20 or bottom - top < 20:
            return None
        return tuple(  # type: ignore[return-value]
            Decimal(str(value)) for value in (left, top, right, bottom)
        )

    def _pixels(
        self, points: tuple[CurvePoint, ...]
    ) -> tuple[tuple[Decimal, Decimal], ...]:
        calibration = self._calibration()
        rectangle = self._rectangle()
        if calibration is None or rectangle is None:
            return ()
        pixels: list[tuple[Decimal, Decimal]] = []
        for point in points:
            try:
                pixels.append(source_point_to_pixel(point, calibration, rectangle))
            except ValueError:
                continue
        return tuple(pixels)

    def _widget_points(
        self, points: tuple[CurvePoint, ...]
    ) -> tuple[tuple[float, float], ...]:
        return tuple((float(x), float(y)) for x, y in self._pixels(points))

    @staticmethod
    def _decades(minimum: Decimal, maximum: Decimal) -> tuple[Decimal, ...]:
        exponent = int(minimum.log10().to_integral_value(rounding=ROUND_CEILING))
        values: list[Decimal] = []
        while (value := Decimal(10) ** exponent) <= maximum:
            values.append(value)
            exponent += 1
        return tuple(values)

    @staticmethod
    def _polyline(pixels: tuple[tuple[Decimal, Decimal], ...]) -> QPainterPath:
        path = QPainterPath()
        for x, y in pixels:
            position = QPointF(float(x), float(y))
            if path.elementCount() == 0:
                path.moveTo(position)
            else:
                path.lineTo(position)
        return path

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        calibration = self._calibration()
        rectangle = self._rectangle()
        if calibration is None or rectangle is None:
            painter.setPen(QColor("#757575"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Enter axis bounds to plot the entered points.",
            )
            return
        left, top, right, bottom = (float(value) for value in rectangle)
        painter.setPen(QPen(QColor("#e0e0e0"), 1.0))
        for value in self._decades(calibration.x_min, calibration.x_max):
            x, _y = source_point_to_pixel(
                CurvePoint(x=value, y=calibration.y_min), calibration, rectangle
            )
            painter.drawLine(QPointF(float(x), top), QPointF(float(x), bottom))
        for value in self._decades(calibration.y_min, calibration.y_max):
            _x, y = source_point_to_pixel(
                CurvePoint(x=calibration.x_min, y=value), calibration, rectangle
            )
            painter.drawLine(QPointF(left, float(y)), QPointF(right, float(y)))
        painter.setPen(QPen(QColor("#9e9e9e"), 1.0))
        painter.drawRect(QRectF(left, top, right - left, bottom - top))
        painter.setPen(QColor("#616161"))
        for alignment, value in (
            (Qt.AlignmentFlag.AlignLeft, calibration.x_min),
            (Qt.AlignmentFlag.AlignRight, calibration.x_max),
        ):
            painter.drawText(
                QRectF(left, bottom, right - left, 24.0),
                alignment | Qt.AlignmentFlag.AlignVCenter,
                format(value, "f"),
            )
        for edge, value in ((top, calibration.y_max), (bottom, calibration.y_min)):
            painter.drawText(
                QRectF(0.0, edge - 8.0, left - 6.0, 16.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format(value, "f"),
            )
        if self._siblings_visible:
            sibling_pen = QPen(QColor("#607d8b"), 1.5)
            sibling_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(sibling_pen)
            for points in self._siblings:
                painter.drawPath(self._polyline(self._pixels(points)))
        pixels = self._pixels(self._points)
        painter.setPen(QPen(QColor("#e53935"), 2.0))
        painter.drawPath(self._polyline(pixels))
        painter.setBrush(QColor("#e53935"))
        for x, y in pixels:
            painter.drawEllipse(QPointF(float(x), float(y)), 3.0, 3.0)


class CurveReviewDialog(QDialog):
    """Read a verified local crop and author one selected curve from typed points."""

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
        self.resize(1440, 820)
        self._model = CurveReviewModel(draft)
        self._actor = actor
        self._pdf_paths = {key: Path(value) for key, value in pdf_paths.items()}
        self._pdf_passwords = dict(pdf_passwords or {})
        self._scene = QGraphicsScene(self)
        self._view = _CurveGraphicsView(self._scene)
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
        self._sibling_toggle = QCheckBox("Show reviewed siblings")
        self._sibling_toggle.setChecked(True)
        self._sibling_toggle.toggled.connect(self.set_siblings_visible)
        selector_row.addWidget(self._sibling_toggle)
        layout.addLayout(selector_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._view)

        editor_pane = QWidget()
        editor_layout = QVBoxLayout(editor_pane)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self._bounds_box = QGroupBox("Axis bounds")
        bounds_form = QFormLayout(self._bounds_box)
        self.x_min_edit = QLineEdit()
        self.x_max_edit = QLineEdit()
        self.y_min_edit = QLineEdit()
        self.y_max_edit = QLineEdit()
        for label, field in (
            ("X minimum", self.x_min_edit),
            ("X maximum", self.x_max_edit),
            ("Y minimum", self.y_min_edit),
            ("Y maximum", self.y_max_edit),
        ):
            field.textChanged.connect(self._refresh_point_plot)
            bounds_form.addRow(label, field)
        self.apply_bounds_button = QPushButton("Apply axis bounds")
        self.apply_bounds_button.clicked.connect(self.apply_axis_bounds)
        bounds_form.addRow(self.apply_bounds_button)
        editor_layout.addWidget(self._bounds_box)

        self.point_table = QTableWidget(0, 2)
        self.point_table.setHorizontalHeaderLabels(("X (source unit)", "Y"))
        self.point_table.itemChanged.connect(self._table_changed)
        editor_layout.addWidget(self.point_table, 1)
        point_actions = QHBoxLayout()
        self.add_point_button = QPushButton("Add point")
        self.add_point_button.clicked.connect(self.add_point)
        point_actions.addWidget(self.add_point_button)
        self.remove_point_button = QPushButton("Remove point")
        self.remove_point_button.clicked.connect(self.remove_point)
        point_actions.addWidget(self.remove_point_button)
        editor_layout.addLayout(point_actions)
        self.point_plot = _PointPlot()
        editor_layout.addWidget(self.point_plot, 1)
        splitter.addWidget(editor_pane)
        splitter.setSizes((820, 600))
        layout.addWidget(splitter, 1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Review notes (required for axis bounds, save, and acceptance)")
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
            self.apply_bounds_button,
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

    def set_siblings_visible(self, visible: bool) -> None:
        self.point_plot.set_siblings_visible(visible)

    def point_text(self, row: int) -> tuple[str, str]:
        return (
            self._table_text(row, 0),
            self._table_text(row, 1),
        )

    def set_point_text(self, row: int, x: str, y: str) -> None:
        self._set_table_text(row, 0, x)
        self._set_table_text(row, 1, y)
        if not self._syncing:
            self._refresh_point_plot()

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
        self._refresh_point_plot()

    def apply_axis_bounds(self) -> None:
        """Save the reviewed log-axis domain currently typed into the fields."""

        if not self._source_loaded:
            self._status.setText(
                "A verified local source must be loaded before saving axis bounds."
            )
            return
        if not self._require_notes("axis bounds"):
            return
        bounds = self._bounds_values()
        if bounds is None:
            self._status.setText("Enter valid decimal axis bounds.")
            return
        try:
            self._save_bounds(*bounds)
        except (ApprovalError, ValueError) as error:
            self._status.setText(f"Enter valid decimal axis bounds: {error}")

    def set_axis_bounds(
        self,
        x_min: Decimal,
        x_max: Decimal,
        y_min: Decimal,
        y_max: Decimal,
    ) -> None:
        """Save the same axis bounds the fields would submit."""

        if not self._source_loaded:
            self._status.setText(
                "A verified local source must be loaded before saving axis bounds."
            )
            return
        if not self._require_notes("axis bounds"):
            return
        try:
            self._save_bounds(x_min, x_max, y_min, y_max)
        except (ApprovalError, ValueError) as error:
            self._status.setText(f"Enter valid decimal axis bounds: {error}")

    def save_points(self) -> None:
        if not self._require_notes("saving points"):
            return
        self._store_points()

    def _store_points(self) -> bool:
        variant_id = self._variant_selector.currentData()
        if not isinstance(variant_id, str):
            self._status.setText("Choose a semantic curve variant first.")
            return False
        try:
            points = self._table_points()
        except (InvalidOperation, ValueError) as error:
            self._status.setText(str(error))
            return False
        if self._stored_points_match(points):
            self._status.setText("Visible points already match the saved variant.")
            return True
        try:
            self._model.replace_points(
                variant_id,
                points,
                actor=self._actor,
                notes=self.notes_edit.text().strip(),
                input_origin=self._model.input_origin(variant_id),
            )
        except (ApprovalError, InvalidOperation, ValueError) as error:
            self._status.setText(str(error))
            return False
        self.draft_changed.emit(self._model.draft)
        self._load_current_variant(self._variant_selector.currentIndex())
        self._status.setText("Points saved; accept the variant after reviewing them.")
        return True

    def accept_variant(self) -> None:
        """Store the visible table, then record the manual review of what was stored."""

        if not self._require_notes("acceptance"):
            return
        try:
            source = self._current_source(self._current_variant())
            _figure, calibration = self._figure_and_calibration(source)
        except ApprovalError as failure:
            self._status.setText(str(failure))
            return
        if calibration is None:
            self._status.setText(
                "A current manual calibration is required before accepting this variant."
            )
            return
        if not self._store_points():
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

    def _stored_points_match(self, points: tuple[CurvePoint, ...]) -> bool:
        """Report whether the visible points already are the saved variant."""

        variant = self._current_variant()
        if variant is None:
            return False
        scale = self._model.source_x_scale(variant.id)
        return points == tuple(
            CurvePoint(x=point.x / scale, y=point.y) for point in variant.points
        )

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
            raise ApprovalError("curve source lacks a unique source figure")
        calibrations = tuple(
            item.calibration
            for item in self._model.draft.curve_calibrations
            if item.figure_artifact_sha256 == figures[0].artifact_sha256
        )
        if len(calibrations) > 1:
            raise ApprovalError("curve source has ambiguous calibration evidence")
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
        self._set_bounds_fields(calibration)
        self._populate_table(variant)
        self._refresh_point_plot()
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
            status += " Read the figure's log-axis bounds and apply them before saving points."
        self._status.setText(status)

    def _set_source_available(self, available: bool) -> None:
        self._source_loaded = available
        self.point_table.setEnabled(available)
        self._bounds_box.setEnabled(available)
        for control in self._mutation_controls:
            control.setEnabled(available)

    def _block_source(self, error: Exception) -> None:
        self._scene.clear()
        self._syncing = True
        self.point_table.setRowCount(0)
        self._syncing = False
        self.point_plot.set_curve(None, ())
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

    def _bounds_values(self) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
        try:
            return (
                Decimal(self.x_min_edit.text().strip()),
                Decimal(self.x_max_edit.text().strip()),
                Decimal(self.y_min_edit.text().strip()),
                Decimal(self.y_max_edit.text().strip()),
            )
        except InvalidOperation:
            return None

    def _set_bounds_fields(self, calibration: ManualPlotCalibration | None) -> None:
        values = (
            ("", "", "", "")
            if calibration is None
            else tuple(
                self._decimal_text(value)
                for value in (
                    calibration.x_min,
                    calibration.x_max,
                    calibration.y_min,
                    calibration.y_max,
                )
            )
        )
        for field, value in zip(
            (self.x_min_edit, self.x_max_edit, self.y_min_edit, self.y_max_edit),
            values,
            strict=True,
        ):
            field.setText(value)

    def _save_bounds(
        self, x_min: Decimal, x_max: Decimal, y_min: Decimal, y_max: Decimal
    ) -> None:
        source = self._current_source(self._current_variant())
        figure, _calibration = self._figure_and_calibration(source)
        if source.figure is None:
            raise ApprovalError("curve source lacks a figure identifier")
        calibration = ManualPlotCalibration(
            figure_artifact_sha256=figure.artifact_sha256,
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
        self._refresh_point_plot()
        self._status.setText("Axis bounds saved.")

    def _table_changed(self, _item: QTableWidgetItem) -> None:
        if not self._syncing:
            self._refresh_point_plot()

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

    def _preview_points(self) -> tuple[CurvePoint, ...]:
        """Return each independently valid table row without save-only constraints."""

        points: list[CurvePoint] = []
        for row in range(self.point_table.rowCount()):
            try:
                point = CurvePoint(
                    x=Decimal(self._table_text(row, 0).strip()),
                    y=Decimal(self._table_text(row, 1).strip()),
                )
            except (InvalidOperation, ValueError):
                continue
            if point.x.is_finite() and point.y.is_finite():
                points.append(point)
        return tuple(points)

    def _refresh_point_plot(self) -> None:
        self.point_plot.set_curve(
            self._bounds_values(), self._preview_points(), self._sibling_points()
        )

    def _sibling_points(self) -> tuple[tuple[CurvePoint, ...], ...]:
        try:
            source = self._current_source(self._current_variant())
        except ApprovalError:
            return ()
        siblings: list[tuple[CurvePoint, ...]] = []
        for variant in self._reviewed_siblings(source):
            scale = self._model.source_x_scale(variant.id)
            siblings.append(
                tuple(
                    CurvePoint(x=point.x / scale, y=point.y) for point in variant.points
                )
            )
        return tuple(siblings)

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
        if not self._stored_points_match(visible_points):
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
