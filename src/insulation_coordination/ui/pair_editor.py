from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.engine import PairResult
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    OverrideValue,
    PairCase,
    PairVoltage,
    Project,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.ui.pair_models import CoverageMatrixModel, PairListModel


def _parse_voltage(text: str) -> Decimal:
    text = text.strip()
    for unit in (" V", " kV", "V", "kV"):
        if text.endswith(unit):
            text = text[: -len(unit)].strip()
            value = Decimal(text)
            if unit.strip().endswith("kV"):
                value *= Decimal(1000)
            return value
    return Decimal(text)


def _parse_frequency(text: str) -> Decimal:
    text = text.strip()
    for unit in (" Hz", " kHz", " MHz", "Hz", "kHz", "MHz"):
        if text.endswith(unit):
            text = text[: -len(unit)].strip()
            value = Decimal(text)
            if "k" in unit:
                value *= Decimal(1000)
            elif "M" in unit:
                value *= Decimal(1_000_000)
            return value
    return Decimal(text)


def _override_row(widget: QWidget, label: QLabel) -> QWidget:
    """Wrap a control plus a Default/Override provenance label."""
    row = QHBoxLayout()
    row.addWidget(widget, 1)
    row.addWidget(label)
    container = QWidget()
    container.setLayout(row)
    return container


class PairEditor(QWidget):
    """Detailed editor for a single pair case."""

    pair_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._pair: PairCase | None = None

        layout = QVBoxLayout(self)

        voltages_group = QGroupBox("Voltages")
        voltages_layout = QFormLayout(voltages_group)
        self._rms_edit = QLineEdit()
        self._rms_edit.editingFinished.connect(self._on_rms_changed)
        voltages_layout.addRow("Long-term RMS:", self._rms_edit)
        self._steady_peak_edit = QLineEdit()
        self._steady_peak_edit.editingFinished.connect(self._on_steady_peak_changed)
        voltages_layout.addRow("Steady-state peak:", self._steady_peak_edit)
        self._recurring_peak_edit = QLineEdit()
        self._recurring_peak_edit.editingFinished.connect(self._on_recurring_peak_changed)
        voltages_layout.addRow("Recurring peak:", self._recurring_peak_edit)
        self._to_peak_edit = QLineEdit()
        self._to_peak_edit.editingFinished.connect(self._on_to_peak_changed)
        voltages_layout.addRow("Temporary OV peak:", self._to_peak_edit)
        layout.addWidget(voltages_group)

        na_group = QGroupBox("Not applicable (with justification)")
        na_layout = QHBoxLayout(na_group)
        self._rms_na_button = QPushButton("RMS N/A")
        self._rms_na_button.clicked.connect(self._on_rms_na)
        na_layout.addWidget(self._rms_na_button)
        self._steady_na_button = QPushButton("Steady peak N/A")
        self._steady_na_button.clicked.connect(self._on_steady_na)
        na_layout.addWidget(self._steady_na_button)
        self._recurring_na_button = QPushButton("Recurring N/A")
        self._recurring_na_button.clicked.connect(self._on_recurring_na)
        na_layout.addWidget(self._recurring_na_button)
        self._to_na_button = QPushButton("Temp OV N/A")
        self._to_na_button.clicked.connect(self._on_to_na)
        na_layout.addWidget(self._to_na_button)
        layout.addWidget(na_group)

        params_group = QGroupBox("Parameters")
        params_layout = QFormLayout(params_group)

        self._freq_edit = QLineEdit()
        self._freq_edit.editingFinished.connect(self._on_freq_changed)
        self._freq_source_label = QLabel("Default")
        freq_row = QHBoxLayout()
        freq_row.addWidget(self._freq_edit)
        freq_row.addWidget(self._freq_source_label)
        freq_widget = QWidget()
        freq_widget.setLayout(freq_row)
        params_layout.addRow("Frequency:", freq_widget)

        self._insulation_combo = QComboBox()
        for t in InsulationType:
            self._insulation_combo.addItem(t.value)
        self._insulation_combo.currentTextChanged.connect(self._on_insulation_changed)
        params_layout.addRow("Insulation type:", self._insulation_combo)

        self._impulse_edit = QLineEdit()
        self._impulse_edit.editingFinished.connect(self._on_impulse_changed)
        self._impulse_source_label = QLabel("Default")
        params_layout.addRow(
            "Impulse:", _override_row(self._impulse_edit, self._impulse_source_label)
        )

        self._field_combo = QComboBox()
        self._field_combo.addItem("")
        for field in FieldCondition:
            self._field_combo.addItem(field.value)
        self._field_combo.currentTextChanged.connect(self._on_field_changed)
        self._field_source_label = QLabel("Default")
        params_layout.addRow(
            "Field condition:", _override_row(self._field_combo, self._field_source_label)
        )

        self._radius_edit = QLineEdit()
        self._radius_edit.editingFinished.connect(self._on_radius_changed)
        self._radius_source_label = QLabel("Default")
        params_layout.addRow(
            "Electrode radius (mm):", _override_row(self._radius_edit, self._radius_source_label)
        )

        self._altitude_edit = QLineEdit()
        self._altitude_edit.editingFinished.connect(self._on_altitude_changed)
        self._altitude_source_label = QLabel("Default")
        params_layout.addRow(
            "Altitude (m):", _override_row(self._altitude_edit, self._altitude_source_label)
        )

        self._pollution_edit = QLineEdit()
        self._pollution_edit.editingFinished.connect(self._on_pollution_changed)
        self._pollution_source_label = QLabel("Default")
        params_layout.addRow(
            "Pollution degree:", _override_row(self._pollution_edit, self._pollution_source_label)
        )

        self._construction_combo = QComboBox()
        self._construction_combo.addItem("")
        for construction in ConstructionType:
            self._construction_combo.addItem(construction.value)
        self._construction_combo.currentTextChanged.connect(self._on_construction_changed)
        self._construction_source_label = QLabel("Default")
        params_layout.addRow(
            "Construction:", _override_row(self._construction_combo, self._construction_source_label)
        )

        self._cti_edit = QLineEdit()
        self._cti_edit.editingFinished.connect(self._on_cti_changed)
        self._cti_source_label = QLabel("Default")
        params_layout.addRow(
            "CTI / material group:", _override_row(self._cti_edit, self._cti_source_label)
        )

        self._notes_edit = QLineEdit()
        self._notes_edit.editingFinished.connect(self._on_notes_changed)
        params_layout.addRow("Notes:", self._notes_edit)

        layout.addWidget(params_group)

    @property
    def pair(self) -> PairCase | None:
        return self._pair

    @property
    def frequency_source_text(self) -> str:
        return self._freq_source_label.text()

    def load_pair(self, pair: PairCase) -> None:
        self._pair = pair
        self._rms_edit.blockSignals(True)
        self._steady_peak_edit.blockSignals(True)
        self._recurring_peak_edit.blockSignals(True)
        self._to_peak_edit.blockSignals(True)
        self._freq_edit.blockSignals(True)
        self._insulation_combo.blockSignals(True)
        self._impulse_edit.blockSignals(True)
        self._field_combo.blockSignals(True)
        self._radius_edit.blockSignals(True)
        self._altitude_edit.blockSignals(True)
        self._pollution_edit.blockSignals(True)
        self._construction_combo.blockSignals(True)
        self._cti_edit.blockSignals(True)
        self._notes_edit.blockSignals(True)

        self._rms_edit.setText(
            str(pair.voltages.long_term_rms_v.value) if pair.voltages.long_term_rms_v.value else ""
        )
        self._steady_peak_edit.setText(
            str(pair.voltages.steady_state_peak_v.value)
            if pair.voltages.steady_state_peak_v.value
            else ""
        )
        self._recurring_peak_edit.setText(
            str(pair.voltages.recurring_peak_v.value)
            if pair.voltages.recurring_peak_v.value
            else ""
        )
        self._to_peak_edit.setText(
            str(pair.voltages.temporary_overvoltage_peak_v.value)
            if pair.voltages.temporary_overvoltage_peak_v.value
            else ""
        )
        if pair.frequency_hz.is_override and pair.frequency_hz.value is not None:
            self._freq_edit.setText(str(pair.frequency_hz.value))
            self._freq_source_label.setText("Override")
        else:
            self._freq_edit.setText("")
            self._freq_source_label.setText("Default")

        self._impulse_edit.setText(
            str(pair.impulse_v.value) if pair.impulse_v.value is not None else ""
        )
        self._impulse_source_label.setText("Override" if pair.impulse_v.is_override else "Default")
        self._field_combo.setCurrentText(
            pair.field_condition.value.value if pair.field_condition.value else ""
        )
        self._field_source_label.setText(
            "Override" if pair.field_condition.is_override else "Default"
        )
        self._radius_edit.setText(
            str(pair.electrode_radius_mm.value)
            if pair.electrode_radius_mm.value is not None
            else ""
        )
        self._radius_source_label.setText(
            "Override" if pair.electrode_radius_mm.is_override else "Default"
        )
        self._altitude_edit.setText(
            str(pair.altitude_m.value) if pair.altitude_m.value is not None else ""
        )
        self._altitude_source_label.setText("Override" if pair.altitude_m.is_override else "Default")
        self._pollution_edit.setText(
            str(pair.pollution_degree.value) if pair.pollution_degree.value is not None else ""
        )
        self._pollution_source_label.setText(
            "Override" if pair.pollution_degree.is_override else "Default"
        )
        self._construction_combo.setCurrentText(
            pair.construction_type.value.value if pair.construction_type.value else ""
        )
        self._construction_source_label.setText(
            "Override" if pair.construction_type.is_override else "Default"
        )
        self._cti_edit.setText(pair.cti_or_material_group.value or "")
        self._cti_source_label.setText(
            "Override" if pair.cti_or_material_group.is_override else "Default"
        )
        self._notes_edit.setText(pair.notes or "")

        self._insulation_combo.blockSignals(False)
        self._rms_edit.blockSignals(False)
        self._steady_peak_edit.blockSignals(False)
        self._recurring_peak_edit.blockSignals(False)
        self._to_peak_edit.blockSignals(False)
        self._freq_edit.blockSignals(False)
        self._impulse_edit.blockSignals(False)
        self._field_combo.blockSignals(False)
        self._radius_edit.blockSignals(False)
        self._altitude_edit.blockSignals(False)
        self._pollution_edit.blockSignals(False)
        self._construction_combo.blockSignals(False)
        self._cti_edit.blockSignals(False)
        self._notes_edit.blockSignals(False)

    def set_long_term_rms(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        voltage = PairVoltage.applicable(value)
        self._update_pair(voltages=self._pair.voltages.model_copy(update={"long_term_rms_v": voltage}))

    def set_long_term_rms_not_applicable(self, justification: str) -> None:
        if self._pair is None:
            return
        voltage = PairVoltage.not_applicable(justification)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"long_term_rms_v": voltage})
        )

    def set_steady_state_peak(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        voltage = PairVoltage.applicable(value)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"steady_state_peak_v": voltage})
        )

    def set_steady_state_peak_not_applicable(self, justification: str) -> None:
        if self._pair is None:
            return
        voltage = PairVoltage.not_applicable(justification)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(
                update={"steady_state_peak_v": voltage}
            )
        )

    def set_recurring_peak(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        voltage = PairVoltage.applicable(value)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"recurring_peak_v": voltage})
        )

    def set_recurring_peak_not_applicable(self, justification: str) -> None:
        if self._pair is None:
            return
        voltage = PairVoltage.not_applicable(justification)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"recurring_peak_v": voltage})
        )

    def set_temporary_overvoltage_not_applicable(self) -> None:
        if self._pair is None:
            return
        voltage = PairVoltage.not_applicable("Not applicable")
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"temporary_overvoltage_peak_v": voltage})
        )

    def set_impulse_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        override = OverrideValue[Decimal].override(value)
        self._update_pair(impulse_v=override)
        self._impulse_source_label.setText("Override")

    def clear_impulse_override(self) -> None:
        if self._pair is None:
            return
        self._update_pair(impulse_v=OverrideValue[Decimal].inherit())
        self._impulse_source_label.setText("Default")

    def set_frequency_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_frequency(text)
        override = OverrideValue[Decimal].override(value)
        self._update_pair(frequency_hz=override)
        self._freq_source_label.setText("Override")

    def _on_rms_changed(self) -> None:
        text = self._rms_edit.text().strip()
        if not text:
            return
        try:
            self.set_long_term_rms(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_steady_peak_changed(self) -> None:
        text = self._steady_peak_edit.text().strip()
        if not text:
            return
        try:
            self.set_steady_state_peak(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_recurring_peak_changed(self) -> None:
        text = self._recurring_peak_edit.text().strip()
        if not text:
            return
        try:
            self.set_recurring_peak(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_to_peak_changed(self) -> None:
        text = self._to_peak_edit.text().strip()
        if not text or self._pair is None:
            return
        try:
            value = _parse_voltage(text)
            voltage = PairVoltage.applicable(value)
            self._update_pair(
                voltages=self._pair.voltages.model_copy(
                    update={"temporary_overvoltage_peak_v": voltage}
                )
            )
        except (InvalidOperation, ValueError):
            pass

    def _on_freq_changed(self) -> None:
        text = self._freq_edit.text().strip()
        if not text:
            return
        try:
            self.set_frequency_override(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_insulation_changed(self, text: str) -> None:
        if self._pair is None:
            return
        try:
            insulation = InsulationType(text)
        except ValueError:
            return
        override = OverrideValue[InsulationType].override(insulation)
        self._update_pair(insulation_type=override)

    def set_field_override(self, value: FieldCondition) -> None:
        if self._pair is None:
            return
        self._update_pair(field_condition=OverrideValue[FieldCondition].override(value))
        self._field_source_label.setText("Override")

    def clear_field_override(self) -> None:
        if self._pair is None:
            return
        self._update_pair(field_condition=OverrideValue[FieldCondition].inherit())
        self._field_source_label.setText("Default")

    def set_radius_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = Decimal(text.strip())
        self._update_pair(electrode_radius_mm=OverrideValue[Decimal].override(value))
        self._radius_source_label.setText("Override")

    def set_altitude_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = Decimal(text.strip())
        self._update_pair(altitude_m=OverrideValue[Decimal].override(value))
        self._altitude_source_label.setText("Override")

    def set_pollution_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = int(text.strip())
        self._update_pair(pollution_degree=OverrideValue[int].override(value))
        self._pollution_source_label.setText("Override")

    def set_construction_override(self, value: ConstructionType) -> None:
        if self._pair is None:
            return
        self._update_pair(construction_type=OverrideValue[ConstructionType].override(value))
        self._construction_source_label.setText("Override")

    def set_cti_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = text.strip()
        self._update_pair(cti_or_material_group=OverrideValue[str].override(value))
        self._cti_source_label.setText("Override")

    def set_notes(self, text: str) -> None:
        if self._pair is None:
            return
        self._update_pair(notes=(text.strip() or None))

    def _on_impulse_changed(self) -> None:
        text = self._impulse_edit.text().strip()
        if not text:
            return
        try:
            self.set_impulse_override(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_field_changed(self, text: str) -> None:
        if self._pair is None or not text:
            return
        try:
            self.set_field_override(FieldCondition(text))
        except ValueError:
            pass

    def _on_radius_changed(self) -> None:
        text = self._radius_edit.text().strip()
        if not text:
            return
        try:
            self.set_radius_override(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_altitude_changed(self) -> None:
        text = self._altitude_edit.text().strip()
        if not text:
            return
        try:
            self.set_altitude_override(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_pollution_changed(self) -> None:
        text = self._pollution_edit.text().strip()
        if not text:
            return
        try:
            self.set_pollution_override(text)
        except (InvalidOperation, ValueError):
            pass

    def _on_construction_changed(self, text: str) -> None:
        if self._pair is None or not text:
            return
        try:
            self.set_construction_override(ConstructionType(text))
        except ValueError:
            pass

    def _on_cti_changed(self) -> None:
        text = self._cti_edit.text().strip()
        if not text:
            return
        try:
            self.set_cti_override(text)
        except ValueError:
            pass

    def _on_notes_changed(self) -> None:
        if self._pair is None:
            return
        self.set_notes(self._notes_edit.text())

    def _on_rms_na(self) -> None:
        if self._pair is None:
            return
        self.set_long_term_rms_not_applicable("Not applicable per design review")
        self._rms_edit.clear()

    def _on_steady_na(self) -> None:
        if self._pair is None:
            return
        self.set_steady_state_peak_not_applicable("Not applicable per design review")
        self._steady_peak_edit.clear()

    def _on_recurring_na(self) -> None:
        if self._pair is None:
            return
        self.set_recurring_peak_not_applicable("Not applicable per design review")
        self._recurring_peak_edit.clear()

    def _on_to_na(self) -> None:
        if self._pair is None:
            return
        self.set_temporary_overvoltage_not_applicable()
        self._to_peak_edit.clear()

    def _update_pair(self, **updates: object) -> None:
        if self._pair is None:
            return
        self._pair = self._pair.model_copy(update=updates)
        self.pair_changed.emit(self._pair)


class PairPage(QWidget):
    """Full pair-editing page: matrix + list + editor + calculation review."""

    project_changed = Signal(object)
    rules_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._rules: RulePackage | None = None
        self._results: dict[str, PairResult] = {}
        self._selected_pair_id: str | None = None

        layout = QVBoxLayout(self)

        self.matrix_model = CoverageMatrixModel()
        from PySide6.QtWidgets import QTableView

        self._matrix_view = QTableView()
        self._matrix_view.setModel(self.matrix_model)
        self._matrix_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._matrix_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self._matrix_view.clicked.connect(self._on_matrix_clicked)
        layout.addWidget(QLabel("Coverage Matrix:"))
        layout.addWidget(self._matrix_view)

        self.pair_list_model = PairListModel()
        from PySide6.QtWidgets import QListView

        self._pair_list_view = QListView()
        self._pair_list_view.setModel(self.pair_list_model)
        self._pair_list_view.clicked.connect(self._on_list_clicked)
        layout.addWidget(QLabel("Pairs:"))
        layout.addWidget(self._pair_list_view)

        self.editor = PairEditor()
        self.editor.pair_changed.connect(self._on_pair_changed)
        layout.addWidget(self.editor)

        self.recalc_button = QPushButton("Recalculate")
        self.recalc_button.clicked.connect(self.recalculate)
        layout.addWidget(self.recalc_button)

        from insulation_coordination.ui.calculation_review import CalculationReviewPage

        self.calculation_review = CalculationReviewPage()
        layout.addWidget(self.calculation_review)

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    def load_project(self, project: Project) -> None:
        self._project = project
        self.matrix_model.load_project(project)
        self.pair_list_model.load_project(project)
        self.calculation_review.load_project(project)

    def load_rules(self, rules: RulePackage) -> None:
        self._rules = rules

    def select_pair_by_id(self, pair_id: str) -> None:
        self._selected_pair_id = pair_id
        if self._project is None:
            return
        for pair in self._project.pairs:
            if str(pair.id) == pair_id:
                self.editor.load_pair(pair)
                return

    def _on_matrix_clicked(self, index: QModelIndex) -> None:
        pair = self.matrix_model.pair_at(index.row(), index.column())
        if pair is not None:
            self.select_pair_by_id(str(pair.id))

    def _on_list_clicked(self, index: QModelIndex) -> None:
        if self._project is None:
            return
        idx = index.row()
        if 0 <= idx < len(self._project.pairs):
            pair = self._project.pairs[idx]
            self.select_pair_by_id(str(pair.id))

    def _on_pair_changed(self, updated_pair: PairCase) -> None:
        if self._project is None:
            return
        pairs = tuple(
            updated_pair if p.id == updated_pair.id else p for p in self._project.pairs
        )
        self._project = self._project.model_copy(update={"pairs": pairs})
        self.project_changed.emit(self._project)

    def recalculate(self) -> None:
        if self._project is None or self._rules is None:
            return
        from insulation_coordination.calculation.engine import calculate_pair
        from insulation_coordination.project.resolver import resolve_effective_case

        self._results = {}
        for pair in self._project.pairs:
            try:
                effective = resolve_effective_case(self._project.defaults, pair)
                result = calculate_pair(effective, self._rules)
                self._results[str(pair.id)] = result
            except (ValueError, RuntimeError, TypeError, KeyError):
                continue


        results_tuple: tuple[PairResult, ...] = tuple(self._results.values())
        if results_tuple:
            self.calculation_review.update_results(results_tuple, self._project)

    def result_by_id(self, pair_id: UUID) -> object | None:
        return self._results.get(str(pair_id))

    def pair_by_id(self, pair_id: UUID) -> PairCase | None:
        return self.project.pair_by_id(pair_id)

    def _pair_by_id(self, pair_id: UUID) -> PairCase | None:
        if self._project is None:
            return None
        for pair in self._project.pairs:
            if pair.id == pair_id:
                return pair
        return None
