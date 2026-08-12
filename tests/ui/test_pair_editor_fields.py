from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.pairs import reconcile_pairs


def _make_project() -> Project:
    nets = tuple(NetClass(id=UUID(int=i + 1), name=n) for i, n in enumerate(("HV+", "HV-")))
    return Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Editor Fields"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="iec-60664", version="2020.1", sha256="a" * 64
        ),
        defaults=ProjectDefaults(),
        net_classes=nets,
        pairs=reconcile_pairs(nets, ()),
    )


@pytest.fixture
def editor(qtbot):
    from insulation_coordination.ui.pair_editor import PairEditor

    project = _make_project()
    editor = PairEditor()
    editor.load_pair(project.pairs[0])
    qtbot.addWidget(editor)
    return editor


def test_set_impulse_override(editor) -> None:
    editor.set_impulse_override("800 V")
    assert editor.pair is not None
    assert editor.pair.impulse_v.is_override is True
    assert editor.pair.impulse_v.value == Decimal(800)
    assert editor._impulse_source_label.text() == "Manual"


def test_clear_impulse_override(editor) -> None:
    editor.set_impulse_override("800 V")
    editor.clear_impulse_override()
    assert editor.pair is not None
    assert editor.pair.impulse_v.is_override is False
    assert editor._impulse_source_label.text() == "Project default"


def test_set_field_override(editor) -> None:
    editor.set_field_override(FieldCondition.HOMOGENEOUS)
    assert editor.pair is not None
    assert editor.pair.field_condition.is_override
    assert editor.pair.field_condition.value == FieldCondition.HOMOGENEOUS
    assert editor._field_source_label.text() == "Manual"


def test_set_radius_altitude_pollution_cti(editor) -> None:
    editor.set_radius_override("2.5")
    editor.set_altitude_override("1500")
    editor.set_pollution_override("3")
    editor.set_cti_override("II")
    assert editor.pair is not None
    assert editor.pair.electrode_radius_mm.value == Decimal("2.5")
    assert editor.pair.altitude_m.value == Decimal(1500)
    assert editor.pair.pollution_degree.value == 3
    assert editor.pair.cti_or_material_group.value == "II"
    assert editor._radius_source_label.text() == "Manual"
    assert editor._altitude_source_label.text() == "Manual"
    assert editor._pollution_source_label.text() == "Manual"
    assert editor._cti_source_label.text() == "Manual"


def test_set_construction_override_and_notes(editor) -> None:
    editor.set_construction_override(ConstructionType.PRINTED_WIRING)
    editor.set_notes("PVC insulation")
    assert editor.pair is not None
    assert editor.pair.construction_type.value == ConstructionType.PRINTED_WIRING
    assert editor.pair.notes == "PVC insulation"
    assert editor._construction_source_label.text() == "Manual"


def test_rms_not_applicable_button(editor) -> None:
    editor._on_rms_na()
    assert editor.pair is not None
    assert editor.pair.voltages.long_term_rms_v.applicability == "not_applicable"
    assert editor.pair.voltages.long_term_rms_v.justification


def test_steady_not_applicable_button(editor) -> None:
    editor._on_steady_na()
    assert editor.pair is not None
    assert editor.pair.voltages.steady_state_peak_v.applicability == "not_applicable"
    assert editor.pair.voltages.steady_state_peak_v.justification


def test_temporary_not_applicable_button(editor) -> None:
    editor._on_to_na()
    assert editor.pair is not None
    assert editor.pair.voltages.temporary_overvoltage_peak_v.applicability == "not_applicable"


def test_clear_defaultable_overrides_returns_to_project_defaults(qtbot):
    from insulation_coordination.ui.pair_editor import PairEditor

    project = _make_project().model_copy(
        update={
            "defaults": ProjectDefaults(
                frequency_hz=Decimal(50), insulation_type=InsulationType.BASIC
            )
        }
    )
    editor = PairEditor()
    editor.load_pair(project.pairs[0], project.defaults)
    qtbot.addWidget(editor)

    editor.set_frequency_override("100 kHz")
    editor.set_insulation_override(InsulationType.REINFORCED)
    editor.clear_frequency_override()
    editor.clear_insulation_override()

    assert editor.pair is not None
    assert not editor.pair.frequency_hz.is_override
    assert not editor.pair.insulation_type.is_override
    assert editor._freq_edit.text() == "50"
    assert editor._insulation_combo.currentText() == "basic"


def test_not_applicable_buttons_share_voltage_rows(editor):
    assert editor._rms_na_button.parentWidget() is editor._rms_edit.parentWidget()
    assert editor._steady_na_button.parentWidget() is editor._steady_peak_edit.parentWidget()
    assert editor._recurring_na_button.parentWidget() is editor._recurring_peak_edit.parentWidget()
    assert editor._to_na_button.parentWidget() is editor._to_peak_edit.parentWidget()


def _next_tab_stop(widget):
    """The next widget Tab would land on, skipping the layout containers."""
    from PySide6.QtCore import Qt

    node = widget.nextInFocusChain()
    while node is not widget:
        if node.isEnabled() and node.focusPolicy() & Qt.FocusPolicy.TabFocus:
            return node
        node = node.nextInFocusChain()
    return None


def test_every_voltage_field_carries_help(editor):
    from insulation_coordination.ui.help_indicator import HelpIndicator
    from insulation_coordination.ui.voltage_guidance import VoltageGuidanceId

    explained = {
        child.guidance_id
        for child in editor.findChildren(HelpIndicator)
        if type(child) is HelpIndicator
    }
    assert explained == {
        VoltageGuidanceId.LONG_TERM_RMS,
        VoltageGuidanceId.STEADY_STATE_PEAK,
        VoltageGuidanceId.RECURRING_PEAK,
        VoltageGuidanceId.TEMPORARY_OVERVOLTAGE,
        VoltageGuidanceId.TRANSIENT_OVERVOLTAGE,
        VoltageGuidanceId.FREQUENCY,
    }


def test_a_blank_stress_gets_no_state(editor):
    assert editor._rms_badge.text() == "—"
    assert not editor._rms_badge.isEnabled()


def test_entering_a_value_names_it_manual(editor):
    editor.set_long_term_rms("1200")
    assert editor._rms_badge.text() == "Manual"


def test_declaring_a_stress_absent_names_it_and_explains_why(editor, qtbot):
    editor.set_recurring_peak_not_applicable("No coupling path at this barrier")
    assert editor._recurring_badge.text() == "N/A"

    dialog = editor._recurring_help.open_details()
    qtbot.addWidget(dialog)
    assert "No coupling path at this barrier" in dialog.body_text()


def test_a_defaultable_field_names_its_source(editor):
    assert editor._freq_source_label.text() == "Project default"
    editor.set_frequency_override("100 kHz")
    assert editor._freq_source_label.text() == "Manual"
    editor.clear_frequency_override()
    assert editor._freq_source_label.text() == "Project default"


def test_help_sits_before_its_field_in_the_tab_order(editor):
    assert _next_tab_stop(editor._rms_help) is editor._rms_edit
    assert _next_tab_stop(editor._freq_help) is editor._freq_edit


def test_typing_into_a_field_still_works_beside_its_help(editor, qtbot):
    qtbot.keyClicks(editor._rms_edit, "1200")
    assert editor._rms_edit.text() == "1200"


def test_the_na_buttons_stay_distinguishable_without_their_labels(editor):
    names = {
        button.accessibleName()
        for button in (
            editor._rms_na_button,
            editor._steady_na_button,
            editor._recurring_na_button,
            editor._to_na_button,
        )
    }
    assert len(names) == 4
    assert "Mark recurring peak voltage not applicable" in names
