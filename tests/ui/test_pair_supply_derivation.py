"""The pair page's derived-supply panel and the override recorded beside it.

The numbers come from the synthetic supply fixture and are invented, like every number it
carries. ``DERIVED_IMPULSE_V`` is what it derives for the configuration below; the entered
values on either side of it are chosen so that each test states which of the two is the more
severe, and asserts the ordering rather than assuming it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.domain.project import OverrideValue, PairCase, Project
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    ReductionVerificationMethod,
    SupplyConfiguration,
    SupplyKind,
    VerifiedImpulseOverride,
)
from insulation_coordination.ui.derived_supply_summary import EMPTY_VALUE, NO_DERIVATION_TEXT
from insulation_coordination.ui.pair_editor import PairPage
from tests.fixtures.supply_topologies import (
    ENCLOSURE,
    UNEVALUATED,
    VERIFIED,
    circuit_id,
    pair_between,
    supply_topology,
)
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

IN_BAND = Decimal(33)

#: What the fixture derives for the configuration below, and what everything else is
#: positioned against.
DERIVED_IMPULSE_V = Decimal(328)

#: An entry the derivation is more severe than, and one it is not.
ENTERED_BELOW_V = Decimal(200)
ENTERED_ABOVE_V = Decimal(600)


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


def _project(
    *,
    enabled: bool = True,
    entered_impulse_v: Decimal | None = None,
    barrier: object = VERIFIED,
) -> Project:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, barrier),))
    return project.model_copy(
        update={
            "defaults": project.defaults.model_copy(
                update={"frequency_hz": Decimal(50), "impulse_v": entered_impulse_v}
            ),
            "supply_configurations": (_configuration(enabled=enabled),),
        }
    )


def _pair(project: Project) -> PairCase:
    return pair_between(project, circuit_id(0), ENCLOSURE)


@pytest.fixture
def page(qtbot) -> PairPage:
    widget = PairPage()
    qtbot.addWidget(widget)
    widget.load_rules(synthetic_supply_rule_package())
    return widget


def _open(page: PairPage, project: Project) -> PairCase:
    page.load_project(project)
    pair = _pair(project)
    page.select_pair_by_id(str(pair.id))
    return pair


# --- what the derivation shows ----------------------------------------------------------


def test_an_enabled_arrangement_dimensions_the_pair_from_its_derived_stress(page) -> None:
    _open(page, _project())
    panel = page.editor.supply_panel

    assert panel.notice == ""
    assert panel.value_text("Source scenarios") == f"Synthetic mains: {DERIVED_IMPULSE_V} V"
    assert panel.value_text("Governing before override") == f"{DERIVED_IMPULSE_V} V"
    assert panel.value_text("Verified effective impulse") == f"{DERIVED_IMPULSE_V} V"
    assert panel.dimensioned_from_text == f"{DERIVED_IMPULSE_V} V"
    assert panel.dimensioned_from_badge == "Derived"


def test_the_panel_names_the_domain_the_stress_entered_and_the_rules_it_read(page) -> None:
    _open(page, _project())
    panel = page.editor.supply_panel

    assert "Primary" in panel.value_text("Propagation path")
    assert "iec62477_2022.supply." in panel.value_text("Source rules")
    assert "circuit to surroundings" in panel.value_text("Relationship")


def test_a_temporary_overvoltage_reaches_a_circuit_to_surroundings_pair(page) -> None:
    _open(page, _project())

    assert "peak" in page.editor.supply_panel.value_text("Temporary overvoltage")


# --- which of two figures governs ---------------------------------------------------------


def test_an_entry_below_the_derived_figure_is_superseded_and_both_are_shown(page) -> None:
    _open(page, _project(entered_impulse_v=ENTERED_BELOW_V))
    panel = page.editor.supply_panel

    assert ENTERED_BELOW_V < DERIVED_IMPULSE_V
    assert panel.dimensioned_from_text == f"{DERIVED_IMPULSE_V} V"
    assert panel.dimensioned_from_badge == "Derived"
    assert "superseded" in panel.warnings
    assert str(ENTERED_BELOW_V) in panel.warnings
    assert str(DERIVED_IMPULSE_V) in panel.warnings


def test_an_entry_above_the_derived_figure_governs_and_says_why(page, qtbot) -> None:
    project = _project()
    pair = _pair(project)
    entered = pair.model_copy(
        update={"impulse_v": OverrideValue[Decimal].override(ENTERED_ABOVE_V)}
    )
    project = project.model_copy(
        update={"pairs": tuple(entered if item.id == pair.id else item for item in project.pairs)}
    )
    _open(page, project)
    panel = page.editor.supply_panel

    assert ENTERED_ABOVE_V > DERIVED_IMPULSE_V
    assert panel.dimensioned_from_text == f"{ENTERED_ABOVE_V} V"
    assert panel.dimensioned_from_badge == "Manual"
    assert "the more severe of the two governs" in panel.warnings
    assert str(ENTERED_ABOVE_V) in panel.warnings
    assert str(DERIVED_IMPULSE_V) in panel.warnings


# --- switching the feature off --------------------------------------------------------------


def test_disabling_every_arrangement_restores_manual_entry_with_no_residue(page) -> None:
    project = _project(entered_impulse_v=ENTERED_BELOW_V)
    pair = _open(page, project)
    assert page.editor.supply_panel.dimensioned_from_text == f"{DERIVED_IMPULSE_V} V"

    # The same project with the tick removed, so the pair is the one that was derived for.
    _open(
        page, project.model_copy(update={"supply_configurations": (_configuration(enabled=False),)})
    )
    panel = page.editor.supply_panel

    assert panel.notice == NO_DERIVATION_TEXT
    assert panel.value_text("Governing before override") == EMPTY_VALUE
    assert panel.dimensioned_from_text == EMPTY_VALUE
    assert panel.warnings == ""
    # Nothing derived was left behind in the pair's own entries.
    restored = page.project.pair_by_id(pair.id)
    assert restored is not None
    assert restored.impulse_v.is_override is False
    assert restored.impulse_override is None
    assert restored.voltages == pair.voltages


def test_an_unresolved_barrier_blocks_propagation_and_says_so(page) -> None:
    _open(page, _project(barrier=UNEVALUATED))
    panel = page.editor.supply_panel

    assert "not evaluated" in panel.value_text("Relationship")
    assert "topology is unresolved" in panel.warnings
    assert panel.value_text("Governing before override") == EMPTY_VALUE


# --- the override recorded at the pair ----------------------------------------------------


def _reduction() -> VerifiedImpulseOverride:
    return VerifiedImpulseOverride(
        value_v=Decimal(120),
        basis=ImpulseOverrideBasis.VERIFIED_CIRCUIT_CHARACTERISTIC,
        verification_method=ReductionVerificationMethod.TEST,
        justification="Measured on the assembled unit",
        evidence_reference="SYN-EVIDENCE-1",
        affected_location="Primary to enclosure",
    )


def test_recording_an_override_changes_what_the_pair_is_dimensioned_from(page) -> None:
    pair = _open(page, _project())
    editor = page.editor.override_editor

    editor.set_override(_reduction())
    assert editor.record_override() is True

    stored = page.project.pair_by_id(pair.id)
    assert stored is not None
    assert stored.impulse_override == _reduction()
    panel = page.editor.supply_panel
    assert panel.value_text("Governing before override") == f"{DERIVED_IMPULSE_V} V"
    assert panel.value_text("Verified effective impulse") == "120 V"
    assert panel.dimensioned_from_badge == "Verified override"
    assert "Applied" in editor.status_text


def test_clearing_the_override_restores_the_derived_value(page) -> None:
    pair = _open(page, _project())
    editor = page.editor.override_editor
    editor.set_override(_reduction())
    editor.record_override()

    editor.clear_override()

    stored = page.project.pair_by_id(pair.id)
    assert stored is not None
    assert stored.impulse_override is None
    assert stored.impulse_v.is_override is False
    panel = page.editor.supply_panel
    assert panel.value_text("Verified effective impulse") == f"{DERIVED_IMPULSE_V} V"
    assert panel.dimensioned_from_badge == "Derived"


def test_an_override_recorded_on_a_pair_is_shown_when_it_is_reopened(page) -> None:
    pair = _open(page, _project())
    page.editor.override_editor.set_override(_reduction())
    page.editor.override_editor.record_override()

    page.select_pair_by_id(str(pair.id))

    assert page.editor.override_editor.override == _reduction()
