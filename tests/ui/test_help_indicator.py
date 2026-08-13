"""The help control must work by mouse, by keyboard, and beside a dead field."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QToolTip

from insulation_coordination.ui.help_indicator import (
    GUIDANCE_AUTHORSHIP_NOTE,
    NO_PACKAGE_FOR_PROVENANCE,
    RULE_NOT_IN_PACKAGE,
    FieldStateBadge,
    GuidanceDialog,
    HelpIndicator,
)
from insulation_coordination.ui.topology_guidance import TopologyGuidanceId
from insulation_coordination.ui.voltage_guidance import (
    VoltageGuidanceId,
    accessible_help_name,
    guidance_for,
)
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package


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
    shown: list[str] = []
    monkeypatch.setattr(
        QToolTip, "showText", staticmethod(lambda point, text, *args: shown.append(text))
    )
    QApplication.sendEvent(
        indicator,
        QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason),
    )
    assert shown == [guidance_for(VoltageGuidanceId.RECURRING_PEAK).short_text]


def test_focus_out_hides_the_tooltip(indicator, monkeypatch) -> None:
    hidden: list[bool] = []
    monkeypatch.setattr(QToolTip, "hideText", staticmethod(lambda: hidden.append(True)))
    QApplication.sendEvent(
        indicator,
        QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason),
    )
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


# --- source provenance: application guidance and package citation stay distinguishable ---


def test_guidance_naming_no_rule_gets_no_provenance_section(qtbot) -> None:
    """A voltage-stress field explains itself and cites nothing; an empty heading would lie."""
    dialog = GuidanceDialog(VoltageGuidanceId.RECURRING_PEAK, package=synthetic_dvc_rule_package())
    qtbot.addWidget(dialog)
    assert GUIDANCE_AUTHORSHIP_NOTE not in dialog.body_text()


def test_a_named_rule_is_cited_from_the_active_package(qtbot) -> None:
    dialog = GuidanceDialog(TopologyGuidanceId.DVC_AS, package=synthetic_dvc_rule_package())
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert GUIDANCE_AUTHORSHIP_NOTE in body
    assert "iec62477_2022.dvc.voltage_limits: IEC 62477-1 2022" in body


def test_a_named_rule_the_package_lacks_is_marked_absent_not_invented(qtbot) -> None:
    dialog = GuidanceDialog(TopologyGuidanceId.DVC_AS, package=synthetic_rule_package())
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert f"iec62477_2022.dvc.voltage_limits: {RULE_NOT_IN_PACKAGE}" in body
    assert "clause" not in body.rsplit(GUIDANCE_AUTHORSHIP_NOTE, 1)[-1]


def test_without_a_package_the_guidance_says_it_cannot_cite_one(qtbot) -> None:
    dialog = GuidanceDialog(TopologyGuidanceId.DVC_AS)
    qtbot.addWidget(dialog)
    body = dialog.body_text()
    assert GUIDANCE_AUTHORSHIP_NOTE in body
    assert NO_PACKAGE_FOR_PROVENANCE in body


def test_the_indicator_passes_its_package_to_the_dialog(qtbot) -> None:
    indicator = HelpIndicator(TopologyGuidanceId.DVC_AS)
    qtbot.addWidget(indicator)
    indicator.set_rules_package(synthetic_dvc_rule_package())
    dialog = indicator.open_details()
    qtbot.addWidget(dialog)
    assert "iec62477_2022.dvc.voltage_limits: IEC 62477-1 2022" in dialog.body_text()


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (VoltageGuidanceId.MANUAL_VALUE, "Manual"),
        (VoltageGuidanceId.INHERITED_DEFAULT, "Project default"),
        (VoltageGuidanceId.DERIVED_VALUE, "Derived"),
        (VoltageGuidanceId.VERIFIED_OVERRIDE, "Verified override"),
        (VoltageGuidanceId.NOT_APPLICABLE, "N/A"),
    ],
)
def test_badge_spells_out_the_state(qtbot, state, expected) -> None:
    badge = FieldStateBadge(state)
    qtbot.addWidget(badge)
    assert badge.text() == expected
    assert badge.isEnabled()
    assert badge.guidance_id is state


def test_badge_explains_its_own_state(qtbot) -> None:
    badge = FieldStateBadge(VoltageGuidanceId.NOT_APPLICABLE)
    qtbot.addWidget(badge)
    with qtbot.waitSignal(badge.details_requested) as blocker:
        badge.click()
    assert blocker.args == [VoltageGuidanceId.NOT_APPLICABLE.value]


def test_badge_stays_quiet_until_a_state_exists(qtbot) -> None:
    badge = FieldStateBadge()
    qtbot.addWidget(badge)
    assert badge.text() == "—"
    assert not badge.isEnabled()


def test_badge_width_does_not_move_when_the_state_changes(qtbot) -> None:
    """A state change must not shove the field it belongs to sideways."""
    badge = FieldStateBadge(VoltageGuidanceId.NOT_APPLICABLE)
    qtbot.addWidget(badge)
    narrow = badge.minimumWidth()
    badge.set_state(VoltageGuidanceId.VERIFIED_OVERRIDE)
    assert badge.minimumWidth() == narrow
    assert narrow >= badge.fontMetrics().horizontalAdvance("Verified override")


def test_help_controls_carry_no_hardcoded_colours() -> None:
    """Dark and light platform palettes can only restyle a control nothing paints over.

    The help component never names a colour, so every theme the platform applies —
    dark, light, or high-contrast — reaches it untouched. A stylesheet or QColor
    anywhere in the module would silently pin one theme's colours under the other.
    """
    import inspect

    from insulation_coordination.ui import help_indicator as module

    source = inspect.getsource(module)
    assert "setStyleSheet" not in source
    assert "QColor" not in source
    assert "setPalette" not in source


def test_the_dialog_title_names_the_field(qtbot) -> None:
    dialog = GuidanceDialog(VoltageGuidanceId.RECURRING_PEAK)
    qtbot.addWidget(dialog)
    assert "recurring peak" in dialog.windowTitle().lower()
