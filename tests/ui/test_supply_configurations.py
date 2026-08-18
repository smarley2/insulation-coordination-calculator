"""The project page's supply-configuration table.

Every figure here comes from the synthetic supply fixture, whose bands and cell values are
invented for this repository. ``DERIVED_IMPULSE_V`` is what that fixture answers for the
configuration below: it is asserted rather than recomputed so a fixture whose numbers move
fails loudly instead of quietly agreeing with itself.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.domain.project import Project
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyKind,
)
from insulation_coordination.project.persistence import load_project, save_project_atomic
from insulation_coordination.ui.supply_configurations import (
    COLUMN_LABELS,
    EMPTY_CELL,
    MANUAL_ENTRY_NOTICE,
    NOT_DERIVED_TEXT,
    SupplyConfigurationsPanel,
    parse_declared_voltages,
)
from tests.fixtures.supply_topologies import supply_topology
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

#: The band the synthetic fixture's three-band axis tops out at.
IN_BAND = Decimal(33)

#: What the fixture derives for ``_configuration()``. Invented, like every number it reads.
DERIVED_IMPULSE_V = Decimal(328)

ENABLED = COLUMN_LABELS.index("Enabled")
NAME = COLUMN_LABELS.index("Name")
NOMINAL = COLUMN_LABELS.index("Nominal voltage")
VALIDATION = COLUMN_LABELS.index("Validation")
DERIVED_IMPULSE = COLUMN_LABELS.index("Derived impulse")
DERIVED_TOV = COLUMN_LABELS.index("Derived TOV")
WARNINGS = COLUMN_LABELS.index("Warnings")


def _configuration(**overrides: object) -> SupplyConfiguration:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": IN_BAND,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.IV,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=IN_BAND),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _project(*configurations: SupplyConfiguration) -> Project:
    return supply_topology(("Primary",)).model_copy(
        update={"supply_configurations": configurations}
    )


@pytest.fixture
def panel(qtbot) -> SupplyConfigurationsPanel:
    widget = SupplyConfigurationsPanel()
    qtbot.addWidget(widget)
    widget.set_rules_package(synthetic_supply_rule_package())
    return widget


# --- what a row shows ---------------------------------------------------------------


def test_an_enabled_row_shows_what_the_package_derives_for_it(panel) -> None:
    panel.set_project(_project(_configuration()))

    assert panel.row_text(0, NAME) == "Synthetic mains"
    assert panel.row_text(0, NOMINAL) == f"{IN_BAND} V (phase_to_earth_rms = {IN_BAND})"
    assert panel.row_text(0, DERIVED_IMPULSE) == f"{DERIVED_IMPULSE_V} V"
    assert "peak" in panel.row_text(0, DERIVED_TOV)
    assert panel.row_text(0, VALIDATION) == "OK"


def test_the_governing_summaries_name_the_scenario_that_governs(panel) -> None:
    panel.set_project(_project(_configuration()))

    assert panel.governing_impulse_summary.endswith(f"{DERIVED_IMPULSE_V} V — Synthetic mains")
    assert "Synthetic mains" in panel.governing_tov_summary
    assert panel.manual_entry_notice == ""


def test_every_incomplete_row_reports_its_own_problems_at_once(panel) -> None:
    panel.set_project(
        _project(
            _configuration(id=UUID(int=1), name="No category", overvoltage_category=None),
            _configuration(id=UUID(int=2), name="No phase", phase_system=None),
        )
    )

    assert "overvoltage category" in panel.row_text(0, VALIDATION)
    assert "phase system" in panel.row_text(1, VALIDATION)


def test_a_duplicate_name_is_reported_against_the_later_row(panel) -> None:
    panel.set_project(
        _project(_configuration(id=UUID(int=1)), _configuration(id=UUID(int=2), enabled=False))
    )

    assert panel.row_text(0, VALIDATION) == "OK"
    assert "already named" in panel.row_text(1, VALIDATION)


def test_an_unresolved_scenario_shows_the_blocks_that_stopped_it(panel) -> None:
    panel.set_project(_project(_configuration(declared_system_voltages=())))

    validation = panel.row_text(0, VALIDATION)
    assert "phase_to_earth_rms" in validation
    assert panel.row_text(0, DERIVED_IMPULSE) == EMPTY_CELL
    assert panel.governing_impulse_summary.endswith(NOT_DERIVED_TEXT)


def test_the_lowest_category_warning_stays_across_a_refresh(panel) -> None:
    project = _project(_configuration(overvoltage_category=OvervoltageCategory.I))
    panel.set_project(project)
    first = panel.row_text(0, WARNINGS)

    panel.set_project(project)

    assert "overvoltage category I" in first
    assert panel.row_text(0, WARNINGS) == first


def test_an_unusable_package_is_only_reported_once_a_row_is_enabled(panel) -> None:
    panel.set_rules_package(None)

    panel.set_project(_project(_configuration(enabled=False)))
    assert panel.rule_blocks_summary == ""

    panel.set_project(_project(_configuration(enabled=True)))
    assert "cannot derive supply stresses" in panel.rule_blocks_summary


# --- editing ---------------------------------------------------------------------------


def test_enabling_a_row_derives_and_disabling_it_restores_manual_entry(panel) -> None:
    configuration = _configuration(enabled=False)
    panel.set_project(_project(configuration))
    assert panel.manual_entry_notice == MANUAL_ENTRY_NOTICE

    panel.set_enabled(configuration.id, True)
    assert panel.row_text(0, DERIVED_IMPULSE) == f"{DERIVED_IMPULSE_V} V"

    panel.set_enabled(configuration.id, False)
    assert panel.row_text(0, DERIVED_IMPULSE) == EMPTY_CELL
    assert panel.governing_impulse_summary.endswith(NOT_DERIVED_TEXT)
    assert panel.manual_entry_notice == MANUAL_ENTRY_NOTICE
    # The row itself is untouched apart from the tick: nothing derived was written into it.
    assert panel.project.supply_configurations == (configuration,)


def test_the_enabled_checkbox_toggles_the_row_it_belongs_to(panel) -> None:
    from PySide6.QtCore import Qt

    configuration = _configuration(enabled=False)
    panel.set_project(_project(configuration))

    item = panel._table.item(panel.row_of(configuration.id), ENABLED)
    item.setCheckState(Qt.CheckState.Checked)

    assert panel.project.supply_configurations[0].enabled is True


def test_each_action_produces_one_project(panel, qtbot) -> None:
    panel.set_project(_project(_configuration()))
    emitted: list[Project] = []
    panel.project_changed.connect(emitted.append)

    panel.add_configuration("Bench supply", Decimal(24))
    panel.duplicate_configuration(UUID(int=1))
    panel.remove_configuration(UUID(int=1))

    assert len(emitted) == 3
    names = [item.name for item in emitted[-1].supply_configurations]
    assert names == ["Synthetic mains (copy)", "Bench supply"]


def test_a_duplicate_arrives_disabled_and_renamed(panel) -> None:
    panel.set_project(_project(_configuration()))

    panel.duplicate_configuration(UUID(int=1))

    copy = panel.project.supply_configurations[1]
    assert copy.name == "Synthetic mains (copy)"
    assert copy.enabled is False
    assert copy.id != UUID(int=1)


def test_an_added_row_is_disabled_and_takes_no_part_in_the_derivation(panel) -> None:
    panel.set_project(_project())

    panel.add_configuration("Bench supply", Decimal(24))

    added = panel.project.supply_configurations[0]
    assert added.enabled is False
    assert panel.row_text(0, VALIDATION) == EMPTY_CELL
    assert panel.governing_impulse_summary.endswith(NOT_DERIVED_TEXT)


def test_an_edit_that_contradicts_the_model_is_refused_with_its_own_message(
    panel, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    refusals: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: refusals.append(args[-1]))
    configuration = _configuration(
        supply_kind=SupplyKind.NON_MAINS_DC, phase_system=None, enabled=False
    )
    panel.set_project(_project(configuration))
    panel._table.setCurrentCell(0, NAME)

    panel._edit(phase_system=PhaseSystem.SINGLE_PHASE)

    assert refusals and "DC supply has no phase system" in refusals[0]
    assert panel.project.supply_configurations == (configuration,)


def test_the_selected_row_is_edited_through_the_form(panel) -> None:
    panel.set_project(_project(_configuration(enabled=False)))
    panel._table.setCurrentCell(0, NAME)

    panel._name_edit.setText("Renamed supply")
    panel._name_edit.editingFinished.emit()

    assert panel.project.supply_configurations[0].name == "Renamed supply"


def test_choosing_a_category_re_derives_the_row(panel) -> None:
    panel.set_project(_project(_configuration(overvoltage_category=None)))
    panel._table.setCurrentCell(0, NAME)

    panel._ovc_combo.setCurrentIndex(
        next(
            index
            for index in range(panel._ovc_combo.count())
            if panel._ovc_combo.itemData(index) == OvervoltageCategory.IV.value
        )
    )

    assert panel.project.supply_configurations[0].overvoltage_category is OvervoltageCategory.IV
    assert panel.row_text(0, DERIVED_IMPULSE) == f"{DERIVED_IMPULSE_V} V"


def test_a_voltage_that_is_not_a_number_leaves_the_row_alone(panel, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    refusals: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: refusals.append(args[-1]))
    configuration = _configuration()
    panel.set_project(_project(configuration))
    panel._table.setCurrentCell(0, NAME)

    panel._voltage_edit.setText("not a voltage")
    panel._voltage_edit.editingFinished.emit()

    assert refusals and "not a voltage" in refusals[0]
    assert panel.project.supply_configurations == (configuration,)
    assert panel._voltage_edit.text() == str(IN_BAND)


def test_the_system_voltage_field_states_the_measures_a_lookup_reads(panel) -> None:
    panel.set_project(_project(_configuration(declared_system_voltages=())))
    panel._table.setCurrentCell(0, NAME)
    assert panel.row_text(0, DERIVED_IMPULSE) == EMPTY_CELL

    panel._measures_edit.setText(f"phase_to_earth_rms = {IN_BAND}")
    panel._measures_edit.editingFinished.emit()

    assert panel.row_text(0, DERIVED_IMPULSE) == f"{DERIVED_IMPULSE_V} V"


# --- the page that hosts the table -----------------------------------------------------


def test_the_project_page_hosts_the_table_and_forwards_its_edits(qtbot) -> None:
    from insulation_coordination.ui.project_pages import ProjectPage

    page = ProjectPage()
    qtbot.addWidget(page)
    page.load_project(_project(_configuration(enabled=False)))
    page.set_rules_package(synthetic_supply_rule_package())
    emitted: list[Project] = []
    page.project_changed.connect(emitted.append)

    page._supply_panel.set_enabled(UUID(int=1), True)

    assert emitted and emitted[-1].supply_configurations[0].enabled is True
    assert page.project.supply_configurations[0].enabled is True
    assert page._supply_panel.row_text(0, DERIVED_IMPULSE) == f"{DERIVED_IMPULSE_V} V"
    assert page.is_dirty


# --- the measure field -------------------------------------------------------------------


def test_declared_voltages_parse_as_measure_and_value_pairs() -> None:
    declared = parse_declared_voltages(" phase_to_earth_rms = 33 , conductor_to_conductor = 44 ")

    assert declared == (
        DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=Decimal(33)),
        DeclaredSystemVoltage(measure="conductor_to_conductor", value_v=Decimal(44)),
    )


def test_a_measure_without_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="measure = voltage"):
        parse_declared_voltages("phase_to_earth_rms")


# --- persistence --------------------------------------------------------------------------


def test_configurations_built_here_round_trip_with_their_ids_and_order(
    panel, tmp_path: Path
) -> None:
    panel.set_project(_project(_configuration()))
    panel.add_configuration("Bench supply", Decimal(24))
    path = tmp_path / "project.icproj"

    save_project_atomic(path, panel.project)
    reloaded = load_project(path)

    assert [item.id for item in reloaded.supply_configurations] == [
        item.id for item in panel.project.supply_configurations
    ]
    assert [item.name for item in reloaded.supply_configurations] == [
        "Synthetic mains",
        "Bench supply",
    ]
    assert [item.enabled for item in reloaded.supply_configurations] == [True, False]
