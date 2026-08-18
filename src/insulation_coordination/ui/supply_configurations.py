"""The supported supply arrangements a project declares, and what they derive.

One row is one :class:`~insulation_coordination.domain.supply.SupplyConfiguration`. The left
half of every row is what a user entered; the right half - validation, derived impulse,
derived temporary overvoltage, warnings - is what the active rule package makes of it, read
back from the derivation service and never computed here.

Three things about the presentation are deliberate.

*Every bad row shows at once.* Incompleteness is reportable data, not an exception, so the
validation column carries one row's problems while its neighbours carry theirs, and a
configuration the package could not derive from shows the typed blocks that stopped it rather
than disappearing from the table.

*Derived values are read-only.* No derived figure has an editable control anywhere on this
page, and nothing writes one back into a configuration. Switching the last enabled row off
stops the derivation and leaves the manual project fields exactly as they were - the notice
under the table says so, because a user who has just turned the feature off is owed the
statement that their own entries are back in charge.

*A warning stays while its condition does.* Every warning shown here is re-read from the
derivation on each refresh, so an overvoltage-category warning cannot be dismissed while the
category that raises it is still selected.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.supply_rules import (
    SupplyRuleBlock,
    read_supply_rules,
    supply_rule_blocks,
)
from insulation_coordination.calculation.supply_stress import SupplyStressService
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    DerivedSupplyScenario,
    EarthingArrangement,
    GoverningSupplyStress,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyConfigurationProblem,
    SupplyKind,
    UnresolvedSupplyScenario,
    validate_supply_configurations,
)
from insulation_coordination.ui.value_options import populate_combo

COLUMN_LABELS = (
    "Enabled",
    "Name",
    "Supply kind",
    "Nominal voltage",
    "Phase",
    "Earthing",
    "OVC",
    "Input topology",
    "Validation",
    "Derived impulse",
    "Derived TOV",
    "Warnings",
)

#: Shown wherever a cell has no value, so a column never collapses into blankness that
#: reads as "nothing to say" when it means "nothing was derived".
EMPTY_CELL = "—"

#: What the summaries say before any derivation has produced a governing value.
NOT_DERIVED_TEXT = "not derived"

GOVERNING_IMPULSE_PREFIX = "Governing impulse: "
GOVERNING_TOV_PREFIX = "Governing temporary OV: "

#: Shown whenever no enabled configuration is a mains one - including when nothing at all is
#: enabled. It is the state every project that predates this feature is in, and the state a
#: user returns to by unticking the last row.
MANUAL_ENTRY_NOTICE = (
    "No mains supply configuration is enabled, so nothing is derived and the project's own "
    "impulse and temporary-overvoltage entries are what every pair is dimensioned from. No "
    "derived value is ever copied into them."
)

#: The name a new row is created under. It is disabled and incomplete on purpose: a row
#: invented by the Add button must not look like an arrangement anybody described.
NEW_CONFIGURATION_NAME = "New supply configuration"

_ID_ROLE = Qt.ItemDataRole.UserRole


def _words(member: StrEnum) -> str:
    """One enum member as a label, which for these enums is its own name in words."""

    return member.value.replace("_", " ")


def _options(enum: type[StrEnum]) -> tuple[tuple[str, str], ...]:
    return tuple((_words(member), member.value) for member in enum)


def parse_declared_voltages(text: str) -> tuple[DeclaredSystemVoltage, ...]:
    """``measure = value`` pairs, comma separated, as the model's own tuple.

    The measure vocabulary belongs to the active rule package, which names the measure that
    applies on the resolution rule's own output - so this field takes the name rather than
    offering a list this application would have to keep in step. A configuration missing the
    measure a lookup needs is told which one, by name, in its validation column.
    """

    declared: list[DeclaredSystemVoltage] = []
    for part in text.split(","):
        if not part.strip():
            continue
        measure, separator, value = part.partition("=")
        if not separator:
            raise ValueError(f"{part.strip()!r} is not a 'measure = voltage' pair")
        declared.append(
            DeclaredSystemVoltage(measure=measure.strip(), value_v=Decimal(value.strip()))
        )
    return tuple(declared)


def declared_voltages_text(configuration: SupplyConfiguration) -> str:
    return ", ".join(
        f"{declared.measure} = {declared.value_v}"
        for declared in configuration.declared_system_voltages
    )


def nominal_voltage_text(configuration: SupplyConfiguration) -> str:
    """The headline figure, and the measures the arrangement states beside it.

    Both, because the nominal voltage is what the row is called and the declared measures are
    what a lookup actually reads - a row showing only the first hides the difference between
    the two on exactly the arrangements where they differ.
    """

    semantics = declared_voltages_text(configuration)
    return f"{configuration.nominal_voltage_v} V" + (f" ({semantics})" if semantics else "")


def scenario_impulse_text(scenario: DerivedSupplyScenario) -> str:
    return f"{scenario.rated_impulse_v} V"


def scenario_tov_text(scenario: DerivedSupplyScenario) -> str:
    parts = [
        f"{value} V {basis}"
        for value, basis in (
            (scenario.temporary_overvoltage_peak_v, "peak"),
            (scenario.temporary_overvoltage_rms_v, "rms"),
        )
        if value is not None
    ]
    return " / ".join(parts) if parts else EMPTY_CELL


def governing_impulse_text(governing: GoverningSupplyStress | None) -> str:
    if governing is None or governing.impulse_v is None:
        return f"{GOVERNING_IMPULSE_PREFIX}{NOT_DERIVED_TEXT}"
    name = _scenario_name(governing, governing.impulse_configuration_id)
    return f"{GOVERNING_IMPULSE_PREFIX}{governing.impulse_v} V — {name}"


def governing_tov_text(governing: GoverningSupplyStress | None) -> str:
    if governing is None or (governing.tov_peak_v is None and governing.tov_rms_v is None):
        return f"{GOVERNING_TOV_PREFIX}{NOT_DERIVED_TEXT}"
    parts = [
        f"{value} V {basis} — {_scenario_name(governing, owner)}"
        for value, owner, basis in (
            (governing.tov_peak_v, governing.tov_configuration_id, "peak"),
            (governing.tov_rms_v, governing.tov_rms_configuration_id, "rms"),
        )
        if value is not None
    ]
    return GOVERNING_TOV_PREFIX + " / ".join(parts)


def _scenario_name(governing: GoverningSupplyStress, owner: UUID | None) -> str:
    return next(
        (
            scenario.configuration_name
            for scenario in governing.scenarios
            if scenario.configuration_id == owner
        ),
        EMPTY_CELL,
    )


def rule_block_text(blocks: tuple[SupplyRuleBlock, ...]) -> str:
    """Why the active package cannot answer the supply questions, all reasons at once."""

    if not blocks:
        return ""
    return "The active rule package cannot derive supply stresses: " + "; ".join(
        block.message for block in blocks
    )


class SupplyConfigurationsPanel(QWidget):
    """Lists the project's supply configurations, edits the selected one, shows what it derives.

    Every action produces one complete replacement project and emits it once, exactly as the
    galvanic-domain and barrier panels beside it do.
    """

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._package: RulePackage | None = None

        group = QGroupBox("Supported supply configurations")
        outer = QVBoxLayout(group)

        row = QHBoxLayout()
        self._table = QTableWidget(0, len(COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(self._on_row_changed)
        row.addWidget(self._table, 3)

        controls = QVBoxLayout()
        self._add_button = QPushButton("Add…")
        self._add_button.clicked.connect(self._on_add_clicked)
        controls.addWidget(self._add_button)
        self._duplicate_button = QPushButton("Duplicate")
        self._duplicate_button.clicked.connect(self._on_duplicate_clicked)
        controls.addWidget(self._duplicate_button)
        self._remove_button = QPushButton("Remove…")
        self._remove_button.clicked.connect(self._on_remove_clicked)
        controls.addWidget(self._remove_button)

        form_box = QGroupBox("Selected configuration")
        form = QFormLayout(form_box)
        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(
            lambda: self._edit(name=self._name_edit.text().strip())
        )
        form.addRow("Name:", self._name_edit)
        self._kind_combo = self._enum_combo(SupplyKind, "supply_kind", blank=False)
        form.addRow("Supply kind:", self._kind_combo)
        self._voltage_edit = QLineEdit()
        self._voltage_edit.editingFinished.connect(self._on_voltage_changed)
        form.addRow("Nominal voltage (V):", self._voltage_edit)
        self._phase_combo = self._enum_combo(PhaseSystem, "phase_system")
        form.addRow("Phase system:", self._phase_combo)
        self._earthing_combo = self._enum_combo(
            EarthingArrangement, "earthing_arrangement", blank=False
        )
        form.addRow("Earthing:", self._earthing_combo)
        self._ovc_combo = self._enum_combo(OvervoltageCategory, "overvoltage_category")
        form.addRow("Overvoltage category:", self._ovc_combo)
        self._topology_combo = self._enum_combo(InputTopology, "input_topology", blank=False)
        form.addRow("Input topology:", self._topology_combo)
        self._bridge_edit = QLineEdit()
        self._bridge_edit.setPlaceholderText("Highest RMS AC before rectification")
        self._bridge_edit.editingFinished.connect(self._on_bridge_changed)
        form.addRow("Bridge RMS (V):", self._bridge_edit)
        self._measures_edit = QLineEdit()
        self._measures_edit.setPlaceholderText("measure = volts, measure = volts")
        self._measures_edit.editingFinished.connect(self._on_measures_changed)
        form.addRow("System voltages:", self._measures_edit)
        self._notes_edit = QLineEdit()
        self._notes_edit.editingFinished.connect(
            lambda: self._edit(notes=self._notes_edit.text().strip())
        )
        form.addRow("Notes:", self._notes_edit)
        controls.addWidget(form_box)
        controls.addStretch(1)
        row.addLayout(controls, 2)
        outer.addLayout(row)

        self._impulse_label = QLabel(governing_impulse_text(None))
        outer.addWidget(self._impulse_label)
        self._tov_label = QLabel(governing_tov_text(None))
        outer.addWidget(self._tov_label)
        self._notice_label = QLabel(MANUAL_ENTRY_NOTICE)
        self._notice_label.setWordWrap(True)
        outer.addWidget(self._notice_label)
        self._blocks_label = QLabel("")
        self._blocks_label.setWordWrap(True)
        outer.addWidget(self._blocks_label)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        self._refresh()

    # -- what the page reads back ----------------------------------------------------

    @property
    def governing_impulse_summary(self) -> str:
        return self._impulse_label.text()

    @property
    def governing_tov_summary(self) -> str:
        return self._tov_label.text()

    @property
    def manual_entry_notice(self) -> str:
        """The notice, or empty while a mains arrangement is enabled and derives instead."""

        return "" if self._notice_label.isHidden() else self._notice_label.text()

    @property
    def rule_blocks_summary(self) -> str:
        return self._blocks_label.text()

    def row_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return "" if item is None else item.text()

    def row_of(self, configuration_id: UUID) -> int:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.data(_ID_ROLE) == str(configuration_id):
                return row
        raise LookupError(f"No row for supply configuration {configuration_id}")

    # -- inputs -----------------------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self._project = project
        self._refresh()

    def set_rules_package(self, package: RulePackage | None) -> None:
        self._package = package
        self._refresh()

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    # -- actions: usable directly, and by the buttons below ---------------------------

    def add_configuration(self, name: str, nominal_voltage_v: Decimal) -> None:
        """Append one disabled, incomplete row for the user to finish.

        Disabled because an arrangement nobody has described yet must not take part in any
        calculation, and incomplete because inventing a phase, an earthing arrangement or a
        category would be this application answering a question about the user's equipment.
        """

        configuration = SupplyConfiguration(
            id=uuid4(),
            enabled=False,
            name=name,
            supply_kind=SupplyKind.AC_MAINS,
            nominal_voltage_v=nominal_voltage_v,
            phase_system=None,
            earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
            overvoltage_category=None,
            input_topology=InputTopology.DIRECT_INPUT,
        )
        self._apply((*self.project.supply_configurations, configuration))

    def duplicate_configuration(self, configuration_id: UUID) -> None:
        """Copy one row, disabled and renamed, directly after the row it came from.

        Disabled so that duplicating cannot silently change a result, and renamed so the copy
        is a second configuration rather than a duplicate name reported as a problem.
        """

        configurations = list(self.project.supply_configurations)
        index = self._index_of(configuration_id)
        original = configurations[index]
        copy = original.model_copy(
            update={"id": uuid4(), "enabled": False, "name": f"{original.name} (copy)"}
        )
        configurations.insert(index + 1, copy)
        self._apply(tuple(configurations))

    def remove_configuration(self, configuration_id: UUID) -> None:
        self._apply(
            tuple(
                item for item in self.project.supply_configurations if item.id != configuration_id
            )
        )

    def set_enabled(self, configuration_id: UUID, enabled: bool) -> None:
        self._replace(self._configuration(configuration_id), enabled=enabled)

    def update_configuration(self, configuration: SupplyConfiguration) -> None:
        configurations = list(self.project.supply_configurations)
        configurations[self._index_of(configuration.id)] = configuration
        self._apply(tuple(configurations))

    # -- internals ---------------------------------------------------------------------

    def _index_of(self, configuration_id: UUID) -> int:
        for index, item in enumerate(self.project.supply_configurations):
            if item.id == configuration_id:
                return index
        raise LookupError(f"No supply configuration {configuration_id}")

    def _configuration(self, configuration_id: UUID) -> SupplyConfiguration:
        return self.project.supply_configurations[self._index_of(configuration_id)]

    def _selected(self) -> SupplyConfiguration | None:
        row = self._table.currentRow()
        if self._project is None or row < 0 or row >= len(self._project.supply_configurations):
            return None
        return self._project.supply_configurations[row]

    def _apply(self, configurations: tuple[SupplyConfiguration, ...]) -> None:
        self._project = self.project.model_copy(update={"supply_configurations": configurations})
        self._refresh()
        self.project_changed.emit(self._project)

    def _replace(self, configuration: SupplyConfiguration, **updates: object) -> None:
        """Rebuild one configuration through its own validation, not through ``model_copy``.

        ``model_copy`` skips validation, so a contradiction - a phase system on a DC supply, a
        bridge voltage on a topology with no bridges - would be persisted rather than refused.
        Refusing here is what keeps the model's own message the one the user reads.
        """

        fields = dict(configuration.model_dump(mode="python"))
        fields.update(updates)
        try:
            updated = SupplyConfiguration.model_validate(fields)
        except ValueError as error:
            QMessageBox.warning(self, "Supply configuration", str(error))
            self._refresh()
            return
        if updated != configuration:
            self.update_configuration(updated)

    def _edit(self, **updates: object) -> None:
        configuration = self._selected()
        if configuration is not None:
            self._replace(configuration, **updates)

    def _enum_combo(self, enum: type[StrEnum], field: str, *, blank: bool = True) -> QComboBox:
        combo = QComboBox()
        populate_combo(combo, _options(enum), blank=blank)
        combo.currentIndexChanged.connect(
            lambda index, field=field, combo=combo: self._edit(**{field: combo.itemData(index)})
        )
        return combo

    def _on_voltage_changed(self) -> None:
        self._edit_decimal("nominal_voltage_v", self._voltage_edit.text(), required=True)

    def _on_bridge_changed(self) -> None:
        self._edit_decimal("rectifier_bridge_rms_v", self._bridge_edit.text(), required=False)

    def _edit_decimal(self, field: str, text: str, *, required: bool) -> None:
        text = text.strip()
        if not text:
            if required:
                self._refresh()
                return
            self._edit(**{field: None})
            return
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Supply configuration", f"{text!r} is not a voltage")
            self._refresh()
            return
        self._edit(**{field: value})

    def _on_measures_changed(self) -> None:
        try:
            declared = parse_declared_voltages(self._measures_edit.text())
        except (InvalidOperation, ValueError) as error:
            QMessageBox.warning(self, "System voltages", str(error))
            self._refresh()
            return
        self._edit(declared_system_voltages=declared)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or self._project is None:
            return
        configuration_id = UUID(str(item.data(_ID_ROLE)))
        self.set_enabled(configuration_id, item.checkState() == Qt.CheckState.Checked)

    def _on_row_changed(self, row: int, _column: int, _previous_row: int, _previous: int) -> None:
        self._show_selected()

    def _derive(
        self,
    ) -> tuple[GoverningSupplyStress | None, tuple[SupplyRuleBlock, ...]]:
        """What the enabled configurations derive, or why nothing was asked of the package.

        Nothing is asked at all while no configuration is enabled: that is the guarantee an
        existing project relies on, and it holds on this page too - a package carrying no
        supply content is only reported as unable once somebody enables a row.
        """

        project = self._project
        if project is None or not any(item.enabled for item in project.supply_configurations):
            return None, ()
        blocks = supply_rule_blocks(self._package)
        if blocks:
            return None, blocks
        rules = read_supply_rules(self._package)
        return SupplyStressService().derive_all(project.supply_configurations, rules), ()

    def _refresh(self) -> None:
        selected = self._selected_id()
        governing, blocks = self._derive()
        configurations = () if self._project is None else self._project.supply_configurations
        problems = validate_supply_configurations(configurations)
        scenarios: dict[UUID, DerivedSupplyScenario] = {}
        unresolved: dict[UUID, UnresolvedSupplyScenario] = {}
        if governing is not None:
            scenarios = {item.configuration_id: item for item in governing.scenarios}
            unresolved = {item.configuration_id: item for item in governing.unresolved}

        self._table.blockSignals(True)
        self._table.setRowCount(len(configurations))
        for row, configuration in enumerate(configurations):
            enabled = QTableWidgetItem("")
            enabled.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            enabled.setCheckState(
                Qt.CheckState.Checked if configuration.enabled else Qt.CheckState.Unchecked
            )
            enabled.setData(_ID_ROLE, str(configuration.id))
            self._table.setItem(row, 0, enabled)
            scenario = scenarios.get(configuration.id)
            for column, text in enumerate(
                (
                    configuration.name,
                    _words(configuration.supply_kind),
                    nominal_voltage_text(configuration),
                    EMPTY_CELL
                    if configuration.phase_system is None
                    else _words(configuration.phase_system),
                    _words(configuration.earthing_arrangement),
                    EMPTY_CELL
                    if configuration.overvoltage_category is None
                    else configuration.overvoltage_category.value,
                    _words(configuration.input_topology),
                    _validation_text(configuration, problems, unresolved.get(configuration.id)),
                    EMPTY_CELL if scenario is None else scenario_impulse_text(scenario),
                    EMPTY_CELL if scenario is None else scenario_tov_text(scenario),
                    EMPTY_CELL
                    if scenario is None or not scenario.warnings
                    else "; ".join(warning.message for warning in scenario.warnings),
                ),
                start=1,
            ):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self._table.setItem(row, column, cell)
        self._table.resizeColumnsToContents()
        if selected is not None:
            index = next(
                (row for row, item in enumerate(configurations) if str(item.id) == selected),
                None,
            )
            if index is not None:
                self._table.setCurrentCell(index, 1)
        self._table.blockSignals(False)

        self._impulse_label.setText(governing_impulse_text(governing))
        self._tov_label.setText(governing_tov_text(governing))
        self._notice_label.setVisible(
            not any(item.enabled and item.is_mains for item in configurations)
        )
        self._blocks_label.setText(rule_block_text(blocks))
        self._show_selected()

    def _selected_id(self) -> str | None:
        item = self._table.item(self._table.currentRow(), 0)
        return None if item is None else str(item.data(_ID_ROLE))

    def _show_selected(self) -> None:
        configuration = self._selected()
        widgets: tuple[QWidget, ...] = (
            self._name_edit,
            self._kind_combo,
            self._voltage_edit,
            self._phase_combo,
            self._earthing_combo,
            self._ovc_combo,
            self._topology_combo,
            self._bridge_edit,
            self._measures_edit,
            self._notes_edit,
        )
        for widget in widgets:
            widget.blockSignals(True)
            widget.setEnabled(configuration is not None)
        if configuration is None:
            self._name_edit.clear()
            self._voltage_edit.clear()
            self._bridge_edit.clear()
            self._measures_edit.clear()
            self._notes_edit.clear()
        else:
            self._name_edit.setText(configuration.name)
            _select(self._kind_combo, configuration.supply_kind)
            self._voltage_edit.setText(str(configuration.nominal_voltage_v))
            _select(self._phase_combo, configuration.phase_system)
            _select(self._earthing_combo, configuration.earthing_arrangement)
            _select(self._ovc_combo, configuration.overvoltage_category)
            _select(self._topology_combo, configuration.input_topology)
            self._bridge_edit.setText(
                ""
                if configuration.rectifier_bridge_rms_v is None
                else str(configuration.rectifier_bridge_rms_v)
            )
            self._measures_edit.setText(declared_voltages_text(configuration))
            self._notes_edit.setText(configuration.notes)
        for widget in widgets:
            widget.blockSignals(False)
        self._duplicate_button.setEnabled(configuration is not None)
        self._remove_button.setEnabled(configuration is not None)

    # -- Qt glue: gather input, then delegate to the actions above ----------------------

    def _on_add_clicked(self) -> None:
        if self._project is None:
            return
        name, ok = QInputDialog.getText(
            self, "Add Supply Configuration", "Name:", text=NEW_CONFIGURATION_NAME
        )
        if not ok or not name.strip():
            return
        text, ok = QInputDialog.getText(self, "Add Supply Configuration", "Nominal voltage (V):")
        if not ok:
            return
        try:
            self.add_configuration(name.strip(), Decimal(text.strip()))
        except (InvalidOperation, ValueError) as error:
            QMessageBox.warning(self, "Add Supply Configuration", str(error))

    def _on_duplicate_clicked(self) -> None:
        configuration = self._selected()
        if configuration is not None:
            self.duplicate_configuration(configuration.id)

    def _on_remove_clicked(self) -> None:
        configuration = self._selected()
        if configuration is None:
            return
        reply = QMessageBox.question(
            self,
            "Remove Supply Configuration",
            f"Remove '{configuration.name}'? Any stress derived from it is removed with it.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.remove_configuration(configuration.id)


def _select(combo: QComboBox, value: StrEnum | None) -> None:
    """Show ``value``, or the blank entry for ``None``.

    Not ``QComboBox.findData``: it does not match the null item data a blank entry carries,
    exactly as ``ui.value_options`` records for the same reason.
    """

    target = None if value is None else value.value
    combo.setCurrentIndex(
        next((index for index in range(combo.count()) if combo.itemData(index) == target), -1)
    )


def _validation_text(
    configuration: SupplyConfiguration,
    problems: tuple[SupplyConfigurationProblem, ...],
    unresolved: UnresolvedSupplyScenario | None,
) -> str:
    """One row's problems and blocks, all of them, never only the first.

    Incompleteness and a refused derivation read the same way here on purpose: both are
    reasons this row contributes nothing, and a user fixing them wants the whole list.
    """

    messages = [
        problem.message for problem in problems if problem.configuration_id == configuration.id
    ]
    if unresolved is not None:
        messages.extend(block.message for block in unresolved.blocks)
    if messages:
        return "; ".join(messages)
    return "OK" if configuration.enabled else EMPTY_CELL


__all__ = [
    "COLUMN_LABELS",
    "EMPTY_CELL",
    "GOVERNING_IMPULSE_PREFIX",
    "GOVERNING_TOV_PREFIX",
    "MANUAL_ENTRY_NOTICE",
    "NEW_CONFIGURATION_NAME",
    "NOT_DERIVED_TEXT",
    "SupplyConfigurationsPanel",
    "declared_voltages_text",
    "governing_impulse_text",
    "governing_tov_text",
    "nominal_voltage_text",
    "parse_declared_voltages",
    "rule_block_text",
    "scenario_impulse_text",
    "scenario_tov_text",
]
