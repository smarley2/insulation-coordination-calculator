"""The DVC guide dialog: package-sourced facts, keyboard reachable, offline.

No IEC value appears here - the synthetic fixture package's numbers are invented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from insulation_coordination.domain.dvc import (
    VOLTAGE_QUANTITY_COLUMN_TOKENS,
    DvcGuidanceService,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.ui.dvc_guide import (
    DVC_AS_CONDITION_NOTE,
    STRESS_BASIS_EXPLANATION,
    DvcGuideDialog,
)
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package


def _label(column: int) -> str:
    """Our own label for Table 2's Nth data column, read from the one place it is set."""
    return dict(VOLTAGE_QUANTITY_COLUMN_TOKENS)[f"voltage-quantity-{column}"]


def test_dialog_opens_and_shows_the_class_in_its_title(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.isVisible()
    assert "DVC B" in dialog.windowTitle()


def test_body_always_carries_the_stress_basis_explanation(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_C)
    qtbot.addWidget(dialog)
    assert STRESS_BASIS_EXPLANATION in dialog.body_text()


def test_dvc_as_body_states_the_dry_condition_note(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_AS)
    qtbot.addWidget(dialog)
    assert DVC_AS_CONDITION_NOTE in dialog.body_text()


def test_dvc_b_body_omits_the_dry_condition_note(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    assert DVC_AS_CONDITION_NOTE not in dialog.body_text()


def test_synthetic_package_limits_render_with_their_source(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_AS)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{_label(1)}: 11 V" in body
    assert "IEC 62477-1 2022" in body
    assert "Table synthetic-table-2" in body


def test_a_reference_cell_names_the_rule_it_refers_to_not_a_number(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{_label(4)}: refers to" in body
    assert "iec62477_2022.supply.impulse_by_system_voltage_ovc" in body


def test_a_not_applicable_cell_says_so(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_C)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{_label(5)}: not applicable" in body


def test_protection_relationships_render_with_their_source(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_AS)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert "Protection requirements" in body
    assert "protection-context-1: none" in body


def test_a_package_missing_the_dvc_rules_degrades_with_a_stated_reason(qtbot) -> None:
    service = DvcGuidanceService(synthetic_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert "not available from the active package" in body
    assert "iec62477_2022.dvc.voltage_limits" in body


def test_a_wrong_edition_package_is_refused(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package(edition="1999"))
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert "not available from the active package" in body
    assert "1999" in body


def test_no_package_loaded_degrades_with_a_stated_reason(qtbot) -> None:
    service = DvcGuidanceService(None)
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_AS)
    qtbot.addWidget(dialog)
    assert "No rule package is loaded" in dialog.body_text()


def test_not_evaluated_shows_no_limits(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.NOT_EVALUATED)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert "No decisive voltage class has been assigned" in body


def test_dialog_text_is_wrapped_and_selectable(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    label = dialog.findChild(type(dialog._body), "_dvc_guide_body")
    assert label is not None
    assert label.wordWrap()
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_close_button_is_keyboard_reachable(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    with qtbot.waitSignal(dialog.rejected, timeout=1000):
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
