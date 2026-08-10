"""The help control must work by mouse, by keyboard, and beside a dead field."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QToolTip

from insulation_coordination.ui.help_indicator import GuidanceDialog, HelpIndicator
from insulation_coordination.ui.voltage_guidance import (
    VoltageGuidanceId,
    accessible_help_name,
    guidance_for,
)


@pytest.fixture
def indicator(qtbot):
    widget = HelpIndicator(VoltageGuidanceId.RECURRING_PEAK)
    qtbot.addWidget(widget)
    # Shown, or Qt delivers no focus events and the keyboard tests prove nothing.
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_hover_shows_the_short_text(indicator) -> None:
    """A Qt tooltip is what a mouse hover displays, so this is the hover behaviour."""
    assert indicator.toolTip() == guidance_for(VoltageGuidanceId.RECURRING_PEAK).short_text


def test_keyboard_focus_shows_the_same_short_text(indicator, monkeypatch) -> None:
    # Showing the only widget in a window already focused it; start from unfocused.
    indicator.clearFocus()
    shown: list[str] = []
    monkeypatch.setattr(
        QToolTip, "showText", staticmethod(lambda point, text, *args: shown.append(text))
    )
    indicator.setFocus(Qt.FocusReason.TabFocusReason)
    assert shown == [guidance_for(VoltageGuidanceId.RECURRING_PEAK).short_text]


def test_focus_out_hides_the_tooltip(indicator, monkeypatch) -> None:
    hidden: list[bool] = []
    monkeypatch.setattr(QToolTip, "hideText", staticmethod(lambda: hidden.append(True)))
    indicator.setFocus(Qt.FocusReason.TabFocusReason)
    indicator.clearFocus()
    assert hidden == [True]


def test_it_is_reachable_by_tab(indicator) -> None:
    assert indicator.focusPolicy() & Qt.FocusPolicy.TabFocus


def test_accessible_name_names_the_field(indicator) -> None:
    assert indicator.accessibleName() == accessible_help_name(VoltageGuidanceId.RECURRING_PEAK)


@pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter])
def test_keyboard_activation_requests_details(indicator, qtbot, key) -> None:
    with qtbot.waitSignal(indicator.details_requested) as blocker:
        qtbot.keyClick(indicator, key)
    assert blocker.args == [VoltageGuidanceId.RECURRING_PEAK.value]


def test_click_requests_details(indicator, qtbot) -> None:
    with qtbot.waitSignal(indicator.details_requested):
        indicator.click()


def test_click_opens_the_detail_dialog(indicator, qtbot) -> None:
    dialog = indicator.open_details()
    qtbot.addWidget(dialog)
    assert dialog.isVisible()
    assert guidance_for(VoltageGuidanceId.RECURRING_PEAK).detailed_text[:40] in dialog.body_text()


def test_a_typed_key_is_left_to_the_field_beside_it(indicator, qtbot) -> None:
    """The indicator must not swallow ordinary editing keys from its neighbour."""
    edit = QLineEdit()
    qtbot.addWidget(edit)
    qtbot.keyClicks(edit, "1200")
    assert edit.text() == "1200"


def test_help_stays_usable_beside_a_disabled_field(qtbot) -> None:
    indicator = HelpIndicator(VoltageGuidanceId.DERIVED_VALUE)
    field = QLineEdit()
    field.setEnabled(False)
    qtbot.addWidget(indicator)
    qtbot.addWidget(field)
    assert indicator.isEnabled()
    with qtbot.waitSignal(indicator.details_requested):
        indicator.click()


def test_it_has_a_high_dpi_safe_minimum_size(indicator) -> None:
    """Sized from the font metrics, so it scales with the display rather than pixels."""
    assert indicator.minimumWidth() >= indicator.fontMetrics().height()
    assert indicator.minimumHeight() >= indicator.fontMetrics().height()


def test_dialog_text_wraps_and_is_selectable(qtbot) -> None:
    dialog = GuidanceDialog(VoltageGuidanceId.TEMPORARY_OVERVOLTAGE)
    qtbot.addWidget(dialog)
    label = dialog.findChild(QLabel, "_guidance_body")
    assert label is not None
    assert label.wordWrap()
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_dialog_lists_examples_and_mistakes(qtbot) -> None:
    guidance = guidance_for(VoltageGuidanceId.RECURRING_PEAK)
    dialog = GuidanceDialog(VoltageGuidanceId.RECURRING_PEAK)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    for line in (*guidance.examples, *guidance.common_mistakes):
        assert line in body


def test_context_is_shown_with_the_guidance(qtbot) -> None:
    """The N/A justification and #36 provenance have no other home in the UI."""
    dialog = GuidanceDialog(VoltageGuidanceId.NOT_APPLICABLE, context="No coupling path exists")
    qtbot.addWidget(dialog)
    assert "No coupling path exists" in dialog.body_text()


def test_indicator_passes_its_context_to_the_dialog(indicator, qtbot) -> None:
    indicator.set_context("Derived from the project supply")
    dialog = indicator.open_details()
    qtbot.addWidget(dialog)
    assert "Derived from the project supply" in dialog.body_text()


def test_the_dialog_title_names_the_field(qtbot) -> None:
    dialog = GuidanceDialog(VoltageGuidanceId.RECURRING_PEAK)
    qtbot.addWidget(dialog)
    assert "recurring peak" in dialog.windowTitle().lower()
