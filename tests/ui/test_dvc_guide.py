"""The DVC guide dialog: package-sourced facts, keyboard reachable, offline.

No IEC value appears here - the synthetic fixture package's numbers are invented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QTextBrowser

from insulation_coordination.domain.dvc import DvcGuidanceService, selector_label
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.ui.dvc_guide import (
    DVC_AS_CONDITION_NOTE,
    SEARCH_WRAPPED_STATUS,
    STRESS_BASIS_EXPLANATION,
    DvcGuideDialog,
)
from tests.domain.test_dvc import FAULT_COLUMN, IMPULSE_COLUMN, RMS_COLUMN
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package

#: The search tests need a class whose body is fully populated, so a match exists to find.
DVC_FOR_SEARCH = DecisiveVoltageClass.DVC_B


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
    assert f"{selector_label(*RMS_COLUMN)}: 11 V" in body
    assert "IEC 62477-1 2022" in body
    assert "Table synthetic-table-2" in body


def test_the_impulse_cell_states_its_deferral_and_names_the_supply_rule(qtbot) -> None:
    """Issue #36 owns the supply resolution; this cell must say so, not print a number."""
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{selector_label(*IMPULSE_COLUMN)}: resolved from the applicable system-voltage" in body
    assert "iec62477_2022.supply.impulse_by_system_voltage_ovc" in body
    assert "depends on the project's own supply" in body


def test_the_fault_time_cell_is_worded_as_a_behaviour_not_a_supply_deferral(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{selector_label(*FAULT_COLUMN)}: resolved from the fault-time voltage rule" in body
    assert "iec62477_2022.dvc.fault_time_voltage" in body


def test_no_positional_table_token_ever_reaches_the_reader(qtbot) -> None:
    """Physical coordinates are extraction provenance, and never reach a reader."""
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    for dvc in DecisiveVoltageClass:
        dialog = DvcGuideDialog(service, dvc)
        qtbot.addWidget(dialog)
        body = dialog.body_text()
        assert "voltage-quantity-" not in body
        assert "protection-context-" not in body
        for index in range(1, 5):
            assert f"dvc-{index}" not in body


def test_a_not_applicable_cell_says_so(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_C)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"{selector_label(*FAULT_COLUMN)}: not applicable" in body


def test_protection_requirements_render_for_the_class_with_their_source(qtbot) -> None:
    """Nothing is withheld any more; #53A's semantic Table 3 selector removed the question."""
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_C)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert "Protection requirements (from the active rule package):" in body
    assert "enhanced_protection" in body
    assert "IEC 62477-1 2022" in body


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


def test_dialog_text_is_wrapped_selectable_and_read_only(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    body = dialog.findChild(QTextBrowser, "_dvc_guide_body")
    assert body is not None
    assert body.lineWrapMode() is QTextBrowser.LineWrapMode.WidgetWidth
    assert body.isReadOnly()
    assert body.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


# --- search: offline, keyboard reachable, and never blocking the Close path -----------


def _dialog(qtbot) -> DvcGuideDialog:
    dialog = DvcGuideDialog(DvcGuidanceService(synthetic_dvc_rule_package()), DVC_FOR_SEARCH)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    # A window shortcut only fires for the active window, offscreen included, and focus
    # assertions need an active window too. The activation is delivered as an event, so it
    # has to be pumped before the first key reaches the dialog.
    dialog.activateWindow()
    qtbot.wait(10)
    return dialog


def test_search_field_is_keyboard_reachable_and_named(qtbot) -> None:
    dialog = _dialog(qtbot)
    field = dialog.findChild(QLineEdit, "_dvc_guide_search")
    assert field is not None
    assert field.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert field.accessibleName()
    assert field.placeholderText()


def test_ctrl_f_focuses_the_search_field(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._body.setFocus()
    qtbot.keyClick(dialog, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert dialog._search_field.hasFocus()


def test_finding_an_existing_term_selects_it_in_the_body(qtbot) -> None:
    """Case-insensitively: a reader searching a guide is looking for a word, not a spelling."""
    dialog = _dialog(qtbot)
    dialog._search_field.setText("VOLTAGE LIMITS")

    assert dialog.find_next() is True

    assert dialog._body.textCursor().selectedText().lower() == "voltage limits"
    assert dialog.search_status() == ""


def test_enter_in_the_search_field_finds_instead_of_closing_the_dialog(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._search_field.setText("Voltage limits")
    dialog._search_field.setFocus()

    qtbot.keyClick(dialog._search_field, Qt.Key.Key_Return)

    assert dialog.isVisible()
    assert dialog._body.textCursor().selectedText().lower() == "voltage limits"


def test_a_term_that_is_not_there_says_so_and_moves_nothing(qtbot) -> None:
    dialog = _dialog(qtbot)
    before = dialog._body.textCursor().position()
    dialog._search_field.setText("zzz-not-in-this-guide")

    assert dialog.find_next() is False

    assert "No match" in dialog.search_status()
    assert dialog._body.textCursor().position() == before


def test_next_advances_through_repeated_matches_and_previous_comes_back(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._search_field.setText("package")

    assert dialog.find_next() is True
    first = dialog._body.textCursor().position()
    assert dialog.find_next() is True
    second = dialog._body.textCursor().position()
    assert second > first

    assert dialog.find_previous() is True
    assert dialog._body.textCursor().position() < second


def test_searching_past_the_last_match_continues_from_the_top(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._search_field.setText("package")
    while dialog.search_status() == "":
        assert dialog.find_next() is True
    assert dialog.search_status() == SEARCH_WRAPPED_STATUS


def test_editing_the_term_clears_a_stale_no_match_message(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._search_field.setText("zzz-not-in-this-guide")
    dialog.find_next()
    assert "No match" in dialog.search_status()

    dialog._search_field.setText("zzz-not-in-this-guid")

    assert dialog.search_status() == ""


def test_an_empty_term_searches_nothing_and_says_nothing(qtbot) -> None:
    dialog = _dialog(qtbot)
    assert dialog.find_next() is False
    assert dialog.search_status() == ""


def test_escape_still_closes_the_dialog_from_the_search_field(qtbot) -> None:
    dialog = _dialog(qtbot)
    dialog._search_field.setFocus()
    with qtbot.waitSignal(dialog.rejected, timeout=1000):
        qtbot.keyClick(dialog._search_field, Qt.Key.Key_Escape)
    assert not dialog.isVisible()


def test_close_button_is_keyboard_reachable(qtbot) -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    dialog = DvcGuideDialog(service, DecisiveVoltageClass.DVC_B)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    with qtbot.waitSignal(dialog.rejected, timeout=1000):
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
