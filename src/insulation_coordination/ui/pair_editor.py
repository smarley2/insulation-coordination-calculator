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
from insulation_coordination.domain.enums import InsulationType
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

        self._insulation_combo.blockSignals(False)
        self._rms_edit.blockSignals(False)
        self._steady_peak_edit.blockSignals(False)
        self._recurring_peak_edit.blockSignals(False)
        self._to_peak_edit.blockSignals(False)
        self._freq_edit.blockSignals(False)

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

    def clear_impulse_override(self) -> None:
        if self._pair is None:
            return
        self._update_pair(impulse_v=OverrideValue[Decimal].inherit())

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
