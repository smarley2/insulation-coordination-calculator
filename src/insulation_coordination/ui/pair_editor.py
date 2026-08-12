from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.engine import PairResult
from insulation_coordination.domain.display import pair_label
from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    OverrideValue,
    PairCase,
    PairVoltage,
    Project,
    ProjectDefaults,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.ui.help_indicator import FieldStateBadge, HelpIndicator
from insulation_coordination.ui.pair_models import (
    MATRIX_PARAMETERS,
    CoverageMatrixModel,
    PairListModel,
)
from insulation_coordination.ui.value_options import (
    IMPULSE_OPTIONS,
    MATERIAL_OPTIONS,
    POLLUTION_OPTIONS,
    impulse_display,
    populate_combo,
    select_combo_value,
)
from insulation_coordination.ui.voltage_guidance import (
    VoltageGuidanceId,
    guidance_for,
    override_field_state,
    voltage_field_state,
)


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


#: Pair inputs hold short values, so they stay narrow and hug the right edge.
_FIELD_WIDTH = 220

#: The states a voltage stress can reach today. #36 adds the derived ones.
_VOLTAGE_STATES = (VoltageGuidanceId.MANUAL_VALUE, VoltageGuidanceId.NOT_APPLICABLE)

#: A defaultable parameter carries either the pair's own value or the project's.
_OVERRIDE_STATES = (VoltageGuidanceId.MANUAL_VALUE, VoltageGuidanceId.INHERITED_DEFAULT)

#: Shown in a voltage field that was marked not applicable, because an empty box
#: is indistinguishable from a stress nobody has filled in yet.
_NOT_APPLICABLE_TEXT = "N/A"


def _voltage_text(voltage: PairVoltage) -> str:
    if voltage.applicability is Applicability.NOT_APPLICABLE:
        return _NOT_APPLICABLE_TEXT
    return "" if voltage.value is None else str(voltage.value)


def _field_row(widget: QWidget) -> QHBoxLayout:
    """Start a form row whose control keeps its minimum width, aligned right."""
    widget.setMaximumWidth(_FIELD_WIDTH)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    row.addWidget(widget)
    return row


def _wrap(row: QHBoxLayout) -> QWidget:
    container = QWidget()
    container.setLayout(row)
    return container


def _form_layout(parent: QWidget) -> QFormLayout:
    """Build a form whose wrapped field rows receive the available width."""
    layout = QFormLayout(parent)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return layout


def _labelled(label: QLabel, help_indicator: HelpIndicator) -> QWidget:
    """A form label with its ⓘ beside it, never inside the value.

    Returned as one widget so the two of them occupy the form's label column and
    the value column keeps its full width.
    """
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(label)
    row.addWidget(help_indicator)
    row.addStretch(1)
    return _wrap(row)


def _override_row(
    widget: QWidget,
    label: FieldStateBadge,
    reset_slot: Callable[[], None],
    object_name: str,
) -> QWidget:
    """Wrap a control plus its provenance badge."""
    row = _field_row(widget)
    row.addWidget(label)
    reset_button = QPushButton("Default")
    reset_button.setObjectName(object_name)
    reset_button.setToolTip("Use project default")
    reset_button.setAutoDefault(False)
    reset_button.clicked.connect(reset_slot)
    row.addWidget(reset_button)
    return _wrap(row)


def _select_enum(combo: QComboBox, value: object, enum: type[StrEnum]) -> None:
    """Show an enum value, or nothing at all when none resolves for this pair."""
    if isinstance(value, enum):
        combo.setCurrentText(value.value)
    else:
        combo.setCurrentIndex(-1)


def _voltage_row(edit: QLineEdit, badge: FieldStateBadge, na_button: QPushButton) -> QWidget:
    row = _field_row(edit)
    row.addWidget(badge)
    row.addWidget(na_button)
    return _wrap(row)


#: What Ctrl+C/Ctrl+V carries between cells: every pair field except the ones that
#: say *which* pair it is. Notes travel too — a reason that applies to one pair
#: usually applies to every pair it is pasted onto.
_COPIED_PAIR_FIELDS = tuple(
    name for name in PairCase.model_fields if name not in {"id", "key", "net_a", "net_b"}
)


class _MatrixView(QTableView):
    """Coverage matrix whose Ctrl+C/Ctrl+V carry a whole pair configuration.

    Handled here rather than with a ``QShortcut`` so the keys stay scoped to this
    view — the editor's line edits keep their own text copy and paste.
    """

    copy_requested = Signal()
    paste_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
        else:
            super().keyPressEvent(event)


class PairEditor(QWidget):
    """Detailed editor for a single pair case."""

    pair_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._pair: PairCase | None = None
        self._defaults: ProjectDefaults | None = None

        layout = QVBoxLayout(self)

        voltages_group = QGroupBox("Voltages")
        voltages_layout = _form_layout(voltages_group)
        self._rms_edit = QLineEdit()
        self._rms_edit.editingFinished.connect(self._on_rms_changed)
        self._rms_na_button = QPushButton("N/A")
        self._rms_na_button.clicked.connect(self._on_rms_na)
        self._rms_badge = FieldStateBadge(states=_VOLTAGE_STATES)
        self._rms_help = HelpIndicator(VoltageGuidanceId.LONG_TERM_RMS)
        voltages_layout.addRow(
            _labelled(QLabel("Long-term RMS:"), self._rms_help),
            _voltage_row(self._rms_edit, self._rms_badge, self._rms_na_button),
        )
        self._steady_peak_edit = QLineEdit()
        self._steady_peak_edit.editingFinished.connect(self._on_steady_peak_changed)
        self._steady_na_button = QPushButton("N/A")
        self._steady_na_button.clicked.connect(self._on_steady_na)
        self._steady_badge = FieldStateBadge(states=_VOLTAGE_STATES)
        self._steady_help = HelpIndicator(VoltageGuidanceId.STEADY_STATE_PEAK)
        voltages_layout.addRow(
            _labelled(QLabel("Steady-state peak:"), self._steady_help),
            _voltage_row(self._steady_peak_edit, self._steady_badge, self._steady_na_button),
        )
        self._recurring_peak_edit = QLineEdit()
        self._recurring_peak_edit.editingFinished.connect(self._on_recurring_peak_changed)
        self._recurring_na_button = QPushButton("N/A")
        self._recurring_na_button.clicked.connect(self._on_recurring_na)
        self._recurring_badge = FieldStateBadge(states=_VOLTAGE_STATES)
        self._recurring_help = HelpIndicator(VoltageGuidanceId.RECURRING_PEAK)
        voltages_layout.addRow(
            _labelled(QLabel("Recurring peak:"), self._recurring_help),
            _voltage_row(
                self._recurring_peak_edit, self._recurring_badge, self._recurring_na_button
            ),
        )
        self._to_peak_edit = QLineEdit()
        self._to_peak_edit.editingFinished.connect(self._on_to_peak_changed)
        self._to_na_button = QPushButton("N/A")
        self._to_na_button.clicked.connect(self._on_to_na)
        self._to_badge = FieldStateBadge(states=_VOLTAGE_STATES)
        self._to_help = HelpIndicator(VoltageGuidanceId.TEMPORARY_OVERVOLTAGE)
        voltages_layout.addRow(
            _labelled(QLabel("Temporary OV peak:"), self._to_help),
            _voltage_row(self._to_peak_edit, self._to_badge, self._to_na_button),
        )
        layout.addWidget(voltages_group)

        #: Every voltage stress with the widgets that display it, so one pass over
        #: the pair keeps badge, help context, and text in step.
        self._voltage_fields = (
            ("long_term_rms_v", self._rms_badge, self._rms_help, self._rms_na_button),
            ("steady_state_peak_v", self._steady_badge, self._steady_help, self._steady_na_button),
            (
                "recurring_peak_v",
                self._recurring_badge,
                self._recurring_help,
                self._recurring_na_button,
            ),
            ("temporary_overvoltage_peak_v", self._to_badge, self._to_help, self._to_na_button),
        )
        # Every N/A button reads "N/A": the row label says which stress it belongs
        # to, but a screen reader announcing four identical buttons does not.
        for _field, _badge, help_indicator, na_button in self._voltage_fields:
            stress = guidance_for(help_indicator.guidance_id).title
            na_button.setAccessibleName(f"Mark {stress} not applicable")

        params_group = QGroupBox("Parameters")
        params_layout = _form_layout(params_group)

        self._freq_edit = QLineEdit()
        self._freq_edit.editingFinished.connect(self._on_freq_changed)
        self._freq_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        self._freq_help = HelpIndicator(VoltageGuidanceId.FREQUENCY)
        params_layout.addRow(
            _labelled(QLabel("Frequency:"), self._freq_help),
            _override_row(
                self._freq_edit,
                self._freq_source_label,
                self.clear_frequency_override,
                "_freq_default_button",
            ),
        )

        self._insulation_combo = QComboBox()
        for t in InsulationType:
            self._insulation_combo.addItem(t.value)
        self._insulation_combo.currentTextChanged.connect(self._on_insulation_changed)
        self._insulation_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Insulation type:",
            _override_row(
                self._insulation_combo,
                self._insulation_source_label,
                self.clear_insulation_override,
                "_insulation_default_button",
            ),
        )

        self._impulse_combo = QComboBox()
        populate_combo(self._impulse_combo, IMPULSE_OPTIONS, blank=False)
        self._impulse_combo.currentIndexChanged.connect(self._on_impulse_selected)
        self._impulse_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        self._impulse_help = HelpIndicator(VoltageGuidanceId.TRANSIENT_OVERVOLTAGE)
        params_layout.addRow(
            _labelled(QLabel("Impulse:"), self._impulse_help),
            _override_row(
                self._impulse_combo,
                self._impulse_source_label,
                self.clear_impulse_override,
                "_impulse_default_button",
            ),
        )

        self._field_combo = QComboBox()
        for field in FieldCondition:
            self._field_combo.addItem(field.value)
        self._field_combo.currentTextChanged.connect(self._on_field_changed)
        self._field_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Field condition:",
            _override_row(
                self._field_combo,
                self._field_source_label,
                self.clear_field_override,
                "_field_default_button",
            ),
        )

        self._radius_edit = QLineEdit()
        self._radius_edit.editingFinished.connect(self._on_radius_changed)
        self._radius_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Electrode radius (mm):",
            _override_row(
                self._radius_edit,
                self._radius_source_label,
                self.clear_radius_override,
                "_radius_default_button",
            ),
        )

        self._altitude_edit = QLineEdit()
        self._altitude_edit.editingFinished.connect(self._on_altitude_changed)
        self._altitude_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Altitude (m):",
            _override_row(
                self._altitude_edit,
                self._altitude_source_label,
                self.clear_altitude_override,
                "_altitude_default_button",
            ),
        )

        self._pollution_combo = QComboBox()
        populate_combo(self._pollution_combo, POLLUTION_OPTIONS, blank=False)
        self._pollution_combo.currentIndexChanged.connect(self._on_pollution_selected)
        self._pollution_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Pollution degree:",
            _override_row(
                self._pollution_combo,
                self._pollution_source_label,
                self.clear_pollution_override,
                "_pollution_default_button",
            ),
        )

        self._construction_combo = QComboBox()
        for construction in ConstructionType:
            self._construction_combo.addItem(construction.value)
        self._construction_combo.currentTextChanged.connect(self._on_construction_changed)
        self._construction_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "Construction:",
            _override_row(
                self._construction_combo,
                self._construction_source_label,
                self.clear_construction_override,
                "_construction_default_button",
            ),
        )

        self._cti_combo = QComboBox()
        populate_combo(self._cti_combo, MATERIAL_OPTIONS, blank=False)
        self._cti_combo.currentIndexChanged.connect(self._on_cti_selected)
        self._cti_source_label = FieldStateBadge(VoltageGuidanceId.INHERITED_DEFAULT, _OVERRIDE_STATES)
        params_layout.addRow(
            "CTI / material group:",
            _override_row(
                self._cti_combo,
                self._cti_source_label,
                self.clear_cti_override,
                "_cti_default_button",
            ),
        )

        self._notes_edit = QLineEdit()
        self._notes_edit.editingFinished.connect(self._on_notes_changed)
        params_layout.addRow("Notes:", _wrap(_field_row(self._notes_edit)))

        layout.addWidget(params_group)

    @property
    def pair(self) -> PairCase | None:
        return self._pair

    @property
    def frequency_source_text(self) -> str:
        return self._freq_source_label.text()

    def load_pair(self, pair: PairCase, defaults: ProjectDefaults | None = None) -> None:
        self._pair = pair
        self._defaults = defaults
        effective = resolve_effective_case(defaults, pair) if defaults is not None else None
        self._rms_edit.blockSignals(True)
        self._steady_peak_edit.blockSignals(True)
        self._recurring_peak_edit.blockSignals(True)
        self._to_peak_edit.blockSignals(True)
        self._freq_edit.blockSignals(True)
        self._insulation_combo.blockSignals(True)
        self._impulse_combo.blockSignals(True)
        self._field_combo.blockSignals(True)
        self._radius_edit.blockSignals(True)
        self._altitude_edit.blockSignals(True)
        self._pollution_combo.blockSignals(True)
        self._construction_combo.blockSignals(True)
        self._cti_combo.blockSignals(True)
        self._notes_edit.blockSignals(True)

        for edit, voltage in (
            (self._rms_edit, pair.voltages.long_term_rms_v),
            (self._steady_peak_edit, pair.voltages.steady_state_peak_v),
            (self._recurring_peak_edit, pair.voltages.recurring_peak_v),
            (self._to_peak_edit, pair.voltages.temporary_overvoltage_peak_v),
        ):
            edit.setText(_voltage_text(voltage))
            # The N/A justification has no other home in the UI.
            edit.setToolTip(voltage.justification or "")
        frequency_value = effective.frequency_hz.value if effective is not None else pair.frequency_hz.value
        self._freq_edit.setText(str(frequency_value) if frequency_value is not None else "")
        insulation_value = (
            effective.insulation_type.value
            if effective is not None
            else pair.insulation_type.value
        )
        _select_enum(self._insulation_combo, insulation_value, InsulationType)
        impulse_value = effective.impulse_v.value if effective is not None else pair.impulse_v.value
        select_combo_value(
            self._impulse_combo,
            IMPULSE_OPTIONS,
            impulse_value,
            None if impulse_value is None else impulse_display(impulse_value),
            blank=False,
        )
        field_value = effective.field_condition.value if effective is not None else pair.field_condition.value
        _select_enum(self._field_combo, field_value, FieldCondition)
        radius_value = (
            effective.electrode_radius_mm.value
            if effective is not None
            else pair.electrode_radius_mm.value
        )
        self._radius_edit.setText(
            str(radius_value) if radius_value is not None else ""
        )
        altitude_value = effective.altitude_m.value if effective is not None else pair.altitude_m.value
        self._altitude_edit.setText(str(altitude_value) if altitude_value is not None else "")
        pollution_value = (
            effective.pollution_degree.value
            if effective is not None
            else pair.pollution_degree.value
        )
        select_combo_value(
            self._pollution_combo,
            POLLUTION_OPTIONS,
            pollution_value,
            None if pollution_value is None else str(pollution_value),
            blank=False,
        )
        construction_value = (
            effective.construction_type.value
            if effective is not None
            else pair.construction_type.value
        )
        _select_enum(self._construction_combo, construction_value, ConstructionType)
        cti_value = (
            effective.cti_or_material_group.value
            if effective is not None
            else pair.cti_or_material_group.value
        )
        select_combo_value(
            self._cti_combo, MATERIAL_OPTIONS, cti_value, cti_value, blank=False
        )
        self._notes_edit.setText(pair.notes or "")

        self._insulation_combo.blockSignals(False)
        self._rms_edit.blockSignals(False)
        self._steady_peak_edit.blockSignals(False)
        self._recurring_peak_edit.blockSignals(False)
        self._to_peak_edit.blockSignals(False)
        self._freq_edit.blockSignals(False)
        self._impulse_combo.blockSignals(False)
        self._field_combo.blockSignals(False)
        self._radius_edit.blockSignals(False)
        self._altitude_edit.blockSignals(False)
        self._pollution_combo.blockSignals(False)
        self._construction_combo.blockSignals(False)
        self._cti_combo.blockSignals(False)
        self._notes_edit.blockSignals(False)
        self._refresh_states()

    #: Defaultable fields, paired with the badge that names where their value came from.
    _OVERRIDE_BADGES = (
        ("frequency_hz", "_freq_source_label"),
        ("insulation_type", "_insulation_source_label"),
        ("impulse_v", "_impulse_source_label"),
        ("field_condition", "_field_source_label"),
        ("electrode_radius_mm", "_radius_source_label"),
        ("altitude_m", "_altitude_source_label"),
        ("pollution_degree", "_pollution_source_label"),
        ("construction_type", "_construction_source_label"),
        ("cti_or_material_group", "_cti_source_label"),
    )

    def _refresh_states(self) -> None:
        """Read every badge and help context straight off the loaded pair.

        Deriving them here rather than at each edit site is what keeps the badge
        honest: it reports the engineering provenance the model holds, never what
        a widget happened to be told last.
        """
        pair = self._pair
        if pair is None:
            return
        for field, badge, help_indicator, _na_button in self._voltage_fields:
            voltage: PairVoltage = getattr(pair.voltages, field)
            badge.set_state(voltage_field_state(voltage))
            # The N/A justification has no other home in the UI.
            help_indicator.set_context(voltage.justification or "")
        for field, badge_name in self._OVERRIDE_BADGES:
            badge = getattr(self, badge_name)
            badge.set_state(override_field_state(getattr(pair, field)))

    def set_long_term_rms(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        voltage = PairVoltage.applicable(value)
        self._update_pair(
            voltages=self._pair.voltages.model_copy(update={"long_term_rms_v": voltage})
        )

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
            voltages=self._pair.voltages.model_copy(
                update={"temporary_overvoltage_peak_v": voltage}
            )
        )

    def set_impulse_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_voltage(text)
        override = OverrideValue[Decimal].override(value)
        self._update_pair(impulse_v=override)

    def clear_impulse_override(self) -> None:
        self._clear_override("impulse_v")

    def set_frequency_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = _parse_frequency(text)
        override = OverrideValue[Decimal].override(value)
        self._update_pair(frequency_hz=override)

    def _clear_override(self, field: str) -> None:
        if self._pair is None:
            return
        current = getattr(self._pair, field)
        self._update_pair(**{field: type(current).inherit()})
        if self._pair is not None:
            self.load_pair(self._pair, self._defaults)

    def clear_frequency_override(self) -> None:
        self._clear_override("frequency_hz")

    def set_insulation_override(self, value: InsulationType) -> None:
        if self._pair is None:
            return
        self._update_pair(insulation_type=OverrideValue[InsulationType].override(value))

    def clear_insulation_override(self) -> None:
        self._clear_override("insulation_type")

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
        self.set_insulation_override(insulation)

    def set_field_override(self, value: FieldCondition) -> None:
        if self._pair is None:
            return
        self._update_pair(field_condition=OverrideValue[FieldCondition].override(value))

    def clear_field_override(self) -> None:
        self._clear_override("field_condition")

    def set_radius_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = Decimal(text.strip())
        self._update_pair(electrode_radius_mm=OverrideValue[Decimal].override(value))

    def clear_radius_override(self) -> None:
        self._clear_override("electrode_radius_mm")

    def set_altitude_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = Decimal(text.strip())
        self._update_pair(altitude_m=OverrideValue[Decimal].override(value))

    def clear_altitude_override(self) -> None:
        self._clear_override("altitude_m")

    def set_pollution_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = int(text.strip())
        self._update_pair(pollution_degree=OverrideValue[int].override(value))

    def clear_pollution_override(self) -> None:
        self._clear_override("pollution_degree")

    def set_construction_override(self, value: ConstructionType) -> None:
        if self._pair is None:
            return
        self._update_pair(construction_type=OverrideValue[ConstructionType].override(value))

    def clear_construction_override(self) -> None:
        self._clear_override("construction_type")

    def set_cti_override(self, text: str) -> None:
        if self._pair is None:
            return
        value = text.strip()
        self._update_pair(cti_or_material_group=OverrideValue[str].override(value))

    def clear_cti_override(self) -> None:
        self._clear_override("cti_or_material_group")

    def set_notes(self, text: str) -> None:
        if self._pair is None:
            return
        self._update_pair(notes=(text.strip() or None))

    def _on_impulse_selected(self, index: int) -> None:
        value = self._impulse_combo.itemData(index)
        if value is not None:
            self.set_impulse_override(str(value))

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

    def _on_pollution_selected(self, index: int) -> None:
        value = self._pollution_combo.itemData(index)
        if value is not None:
            self.set_pollution_override(str(value))

    def _on_construction_changed(self, text: str) -> None:
        if self._pair is None or not text:
            return
        try:
            self.set_construction_override(ConstructionType(text))
        except ValueError:
            pass

    def _on_cti_selected(self, index: int) -> None:
        value = self._cti_combo.itemData(index)
        if value is not None:
            self.set_cti_override(str(value))

    def _on_notes_changed(self) -> None:
        if self._pair is None:
            return
        self.set_notes(self._notes_edit.text())

    def _on_rms_na(self) -> None:
        if self._pair is None:
            return
        self.set_long_term_rms_not_applicable("Not applicable per design review")
        self._rms_edit.setText(_NOT_APPLICABLE_TEXT)

    def _on_steady_na(self) -> None:
        if self._pair is None:
            return
        self.set_steady_state_peak_not_applicable("Not applicable per design review")
        self._steady_peak_edit.setText(_NOT_APPLICABLE_TEXT)

    def _on_recurring_na(self) -> None:
        if self._pair is None:
            return
        self.set_recurring_peak_not_applicable("Not applicable per design review")
        self._recurring_peak_edit.setText(_NOT_APPLICABLE_TEXT)

    def _on_to_na(self) -> None:
        if self._pair is None:
            return
        self.set_temporary_overvoltage_not_applicable()
        self._to_peak_edit.setText(_NOT_APPLICABLE_TEXT)

    def _update_pair(self, **updates: object) -> None:
        if self._pair is None:
            return
        self._pair = self._pair.model_copy(update=updates)
        self._refresh_states()
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
        # Hidden columns are keyed by net-class name, not index: the model resets on
        # every pair edit, and an index would then hide whatever moved into its place.
        self._hidden_nets: set[str] = set()
        self._copied_pair_fields: dict[str, object] | None = None

        layout = QVBoxLayout(self)

        self.matrix_model = CoverageMatrixModel()
        self._matrix_view = _MatrixView()
        self._matrix_view.setModel(self.matrix_model)
        # Extended selection so a click on one header and ctrl-click on the next
        # gather several columns for one Hide.
        self._matrix_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._matrix_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._matrix_view.setMinimumHeight(160)
        self._matrix_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        # Interactive is the drag-the-border mode; Stretch squeezed 20 net names
        # into unreadable stubs.
        self._matrix_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._matrix_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._matrix_view.clicked.connect(self._on_matrix_clicked)
        self._matrix_view.setToolTip(
            "Ctrl+C copies the clicked pair's configuration, Ctrl+V applies it to every "
            "selected pair."
        )
        self._matrix_view.copy_requested.connect(self.copy_selected_pair)
        self._matrix_view.paste_requested.connect(self.paste_into_selection)
        # One hook for every reset — load, parameter change, results, pair edit.
        self.matrix_model.modelReset.connect(self._apply_hidden_columns)

        self.pair_list_model = PairListModel()
        self._pair_list_view = QListView()
        self._pair_list_view.setModel(self.pair_list_model)
        self._pair_list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._pair_list_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._pair_list_view.clicked.connect(self._on_list_clicked)

        self.editor = PairEditor()
        self.editor.pair_changed.connect(self._on_pair_changed)

        from insulation_coordination.ui.calculation_review import (
            CalculationReviewPage,
            titled_panel,
        )

        self.calculation_review = CalculationReviewPage()

        matrix_panel = QWidget()
        matrix_layout = QVBoxLayout(matrix_panel)
        matrix_layout.setContentsMargins(0, 0, 0, 0)
        parameter_row = QHBoxLayout()
        parameter_row.addWidget(QLabel("Show in matrix:"))
        self._matrix_parameter_combo = QComboBox()
        for key, label in MATRIX_PARAMETERS:
            self._matrix_parameter_combo.addItem(label, key)
        self._matrix_parameter_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._matrix_parameter_combo.currentIndexChanged.connect(
            self._on_matrix_parameter_changed
        )
        parameter_row.addWidget(self._matrix_parameter_combo)
        self._hide_columns_button = QPushButton("Hide selected columns")
        self._hide_columns_button.clicked.connect(self.hide_selected_columns)
        parameter_row.addWidget(self._hide_columns_button)
        self._show_columns_button = QPushButton("Show all")
        self._show_columns_button.clicked.connect(self.show_all_columns)
        parameter_row.addWidget(self._show_columns_button)
        parameter_row.addStretch(1)
        matrix_layout.addLayout(parameter_row)
        matrix_layout.addWidget(QLabel("Coverage Matrix:"))
        matrix_layout.addWidget(self._matrix_view)

        pairs_panel = titled_panel("Pairs", self._pair_list_view)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setMinimumSize(0, 0)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._editor_scroll.setWidget(self.editor)

        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._top_splitter.setChildrenCollapsible(False)
        self._top_splitter.addWidget(matrix_panel)
        self._top_splitter.addWidget(self._editor_scroll)
        self._top_splitter.setStretchFactor(0, 2)
        self._top_splitter.setStretchFactor(1, 3)

        # Pairs | Calculation Groups | Results, with Recalculate spanning all three.
        self._lower_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._lower_splitter.setChildrenCollapsible(False)
        self._lower_splitter.addWidget(pairs_panel)
        self._lower_splitter.addWidget(self.calculation_review)
        self._lower_splitter.setStretchFactor(0, 1)
        self._lower_splitter.setStretchFactor(1, 2)

        lower_panel = QWidget()
        lower_layout = QVBoxLayout(lower_panel)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        self.recalc_button = QPushButton("Recalculate")
        self.recalc_button.clicked.connect(self.recalculate)
        lower_layout.addWidget(self.recalc_button)
        lower_layout.addWidget(self._lower_splitter)

        self._main_splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter.addWidget(self._top_splitter)
        self._main_splitter.addWidget(lower_panel)
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        layout.addWidget(self._main_splitter)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._splitters_initialized = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._splitters_initialized:
            self._splitters_initialized = True
            QTimer.singleShot(0, self._set_initial_splitter_sizes)

    def _set_initial_splitter_sizes(self) -> None:
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        editor_width = self._preferred_editor_width(width)
        self._top_splitter.setSizes([width - editor_width, editor_width])
        self._main_splitter.setSizes([int(height * 0.6), int(height * 0.4)])
        pairs_width = self._preferred_pairs_width(width)
        self._lower_splitter.setSizes([pairs_width, width - pairs_width])
        self.calculation_review.balance_columns(width - pairs_width)

    def _preferred_pairs_width(self, width: int) -> int:
        """Keep the pair list as narrow as its longest pair name allows.

        The groups and results beside it carry far longer lines, so every pixel
        the names do not need belongs to them.
        """
        needed = (
            self._pair_list_view.sizeHintForColumn(0)
            + self._pair_list_view.verticalScrollBar().sizeHint().width()
            + 2 * self._pair_list_view.frameWidth()
        )
        return max(min(needed, width // 3), self._pair_list_view.minimumSizeHint().width())

    def _preferred_editor_width(self, width: int) -> int:
        """Open the editor no wider than its inputs need, so they sit far right."""
        hint = self.editor.sizeHint().width()
        scrollbar = self._editor_scroll.verticalScrollBar().sizeHint().width()
        needed = hint + scrollbar + 2 * self._editor_scroll.frameWidth()
        return max(min(needed, int(width * 0.5)), int(width * 0.25))

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    def load_project(self, project: Project) -> None:
        self._project = project
        self._splitters_initialized = False
        self.matrix_model.load_project(project)
        self.pair_list_model.load_project(project)
        self.calculation_review.load_project(project)
        if self.isVisible():
            self._splitters_initialized = True
            QTimer.singleShot(0, self._set_initial_splitter_sizes)

    @property
    def hidden_column_names(self) -> tuple[str, ...]:
        """Hidden net classes, in matrix order."""
        if self._project is None:
            return ()
        return tuple(
            net.name for net in self._project.net_classes if net.name in self._hidden_nets
        )

    def hide_selected_columns(self) -> None:
        """Hide every fully selected matrix column, leaving its row in place."""
        if self._project is None:
            return
        nets = self._project.net_classes
        for index in self._matrix_view.selectionModel().selectedColumns():
            if 0 <= index.column() < len(nets):
                self._hidden_nets.add(nets[index.column()].name)
        self._apply_hidden_columns()

    def show_all_columns(self) -> None:
        """Bring every hidden matrix column back."""
        self._hidden_nets.clear()
        self._apply_hidden_columns()

    def _apply_hidden_columns(self) -> None:
        hidden = 0
        if self._project is not None:
            for column, net in enumerate(self._project.net_classes):
                is_hidden = net.name in self._hidden_nets
                self._matrix_view.setColumnHidden(column, is_hidden)
                hidden += is_hidden
        self._matrix_view.resizeColumnsToContents()
        self._show_columns_button.setText(f"Show all ({hidden})" if hidden else "Show all")

    def _on_matrix_parameter_changed(self, index: int) -> None:
        parameter = self._matrix_parameter_combo.itemData(index)
        if isinstance(parameter, str):
            self.matrix_model.set_parameter(parameter)

    def load_rules(self, rules: RulePackage) -> None:
        self._rules = rules

    def select_pair_by_id(self, pair_id: str) -> None:
        self._selected_pair_id = pair_id
        if self._project is None:
            return
        for pair in self._project.pairs:
            if str(pair.id) == pair_id:
                self.editor.load_pair(pair, self._project.defaults)
                return

    def copy_selected_pair(self) -> None:
        """Remember the selected pair's configuration for a later paste."""
        pair = self._selected_pair()
        if pair is not None:
            self._copied_pair_fields = {
                name: getattr(pair, name) for name in _COPIED_PAIR_FIELDS
            }

    def paste_into_selection(self) -> None:
        """Overwrite every selected pair's configuration with the copied one."""
        if self._copied_pair_fields is None:
            return
        targets = self._selected_pairs()
        if not targets:
            return
        self._replace_pairs(
            tuple(pair.model_copy(update=self._copied_pair_fields) for pair in targets)
        )
        # Reload from the updated project so the editor shows the pasted values.
        self.select_pair_by_id(self._selected_pair_id or str(targets[0].id))

    def _selected_pair(self) -> PairCase | None:
        if self._selected_pair_id is None:
            return None
        return self._pair_by_id(UUID(self._selected_pair_id))

    def _selected_pairs(self) -> tuple[PairCase, ...]:
        """Every distinct pair under the matrix selection, clicked cell as fallback.

        A rubber-band or ctrl-click selection covers diagonal cells and both halves
        of the mirrored matrix, so the ids are deduplicated.
        """
        selected: dict[UUID, PairCase] = {}
        for index in self._matrix_view.selectionModel().selectedIndexes():
            pair = self.matrix_model.pair_at(index.row(), index.column())
            if pair is not None:
                selected[pair.id] = pair
        if not selected:
            pair = self._selected_pair()
            if pair is not None:
                selected[pair.id] = pair
        return tuple(selected.values())

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
        self._replace_pairs((updated_pair,))

    def _replace_pairs(self, updated: tuple[PairCase, ...]) -> None:
        """Swap the given pairs into the project and refresh every view once."""
        if self._project is None or not updated:
            return
        replacements = {pair.id: pair for pair in updated}
        pairs = tuple(replacements.get(pair.id, pair) for pair in self._project.pairs)
        self._project = self._project.model_copy(update={"pairs": pairs})
        parameter = self.matrix_model.parameter
        self.matrix_model.load_project(self._project)
        self.matrix_model.set_parameter(parameter)
        self.pair_list_model.load_project(self._project)
        self.calculation_review.load_project(self._project)
        self.project_changed.emit(self._project)

    def recalculate(self) -> None:
        if self._project is None:
            return
        if self._rules is None:
            QMessageBox.critical(
                self,
                "Cannot recalculate",
                "Load an approved rules package before recalculating.",
            )
            return
        from insulation_coordination.calculation.engine import calculate_pair
        from insulation_coordination.project.resolver import resolve_effective_case

        self._results = {}
        self.matrix_model.set_results({})
        self.calculation_review.update_results((), self._project)
        errors: list[str] = []
        for pair in self._project.pairs:
            if pair.is_excluded:
                continue
            try:
                effective = resolve_effective_case(self._project.defaults, pair)
                result = calculate_pair(effective, self._rules)
                self._results[str(pair.id)] = result
            except (ValueError, RuntimeError, TypeError, KeyError) as error:
                errors.append(format_calculation_error(pair_label(self._project, pair), error))

        if errors:
            self._results = {}
            QMessageBox.critical(
                self,
                "Cannot recalculate",
                "Calculation could not be completed for all pairs:\n\n" + "\n".join(errors),
            )
            return

        results_tuple: tuple[PairResult, ...] = tuple(self._results.values())
        self.matrix_model.set_results(self._results)
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


def format_calculation_error(label: str, error: Exception) -> str:
    """Turn an engine validation message into a human-readable pair error."""
    message = str(error).strip() or "Calculation failed."
    replacements = {
        "frequency_hz": "Frequency",
        "impulse_v": "Impulse voltage",
        "insulation_type": "Insulation type",
        "field_condition": "Field condition",
        "electrode_radius_mm": "Electrode radius",
        "altitude_m": "Altitude",
        "pollution_degree": "Pollution degree",
        "construction_type": "Construction",
        "cti_or_material_group": "CTI/material group",
    }
    for source, display in replacements.items():
        message = message.replace(source, display)
    message = message[0].upper() + message[1:]
    if not message.endswith((".", "!", "?")):
        message += "."
    return f"{label} — {message}"
