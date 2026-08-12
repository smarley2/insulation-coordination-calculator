"""The reusable help control that sits beside a voltage field.

A tooltip alone is not help: it needs a mouse, it vanishes, and it holds one
line. This control shows the same short line on hover *and* on keyboard focus,
and opens the long form on click, Enter, or Space, so the explanation is
reachable however the field is being used — including when the field itself is
read-only or disabled.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.rule_provenance import citation, rule_provenance
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.ui.voltage_guidance import (
    FIELD_STATE_IDS,
    VoltageGuidance,
    VoltageGuidanceId,
    accessible_help_name,
    field_state_label,
    guidance_for,
)

#: The glyph on the control. A letter, not an icon file, so it scales with the font.
_HELP_GLYPH = "ⓘ"

#: A dialog wide enough for prose but not so wide that a line becomes hard to track.
_DIALOG_WIDTH = 460
_DIALOG_HEIGHT = 420


class GuidanceDialog(QDialog):
    """The long form behind a help control: guidance, examples, and context.

    ``context`` carries whatever only the caller knows — the justification stored
    with a not-applicable stress, or the provenance of a derived value. It is
    shown with the guidance rather than replacing it.

    ``package`` is the project's active rule package, when the caller has one. Guidance
    that names a semantic rule then also shows where that rule was read from, under its
    own heading so that package-derived provenance is never mistaken for the application's
    own prose above it. Without a package the guidance still reads; it just says that it
    cannot cite one.
    """

    def __init__(
        self,
        guidance_id: StrEnum,
        context: str = "",
        parent: QWidget | None = None,
        package: RulePackage | None = None,
    ) -> None:
        super().__init__(parent)
        guidance = guidance_for(guidance_id)
        self.setWindowTitle(guidance.title[0].upper() + guidance.title[1:])
        self.resize(_DIALOG_WIDTH, _DIALOG_HEIGHT)

        self._body = QLabel(_body_text(guidance_id, context, package))
        self._body.setObjectName("_guidance_body")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Scrolled rather than sized to fit: the longest guidance would otherwise
        # open a dialog taller than a laptop screen.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

    def body_text(self) -> str:
        return self._body.text()


#: Says whose words the reader has just read, before any package citation follows. Without
#: it the two would run together and a clause number would appear to back the prose.
GUIDANCE_AUTHORSHIP_NOTE = "The explanation above is this application's own guidance."

#: Shown for a named rule the active package does not carry. An absence, deliberately: a
#: clause reference is never invented to fill the field.
RULE_NOT_IN_PACKAGE = "not carried by the active rule package"

#: Shown when guidance names a rule but no package is loaded to resolve it against.
NO_PACKAGE_FOR_PROVENANCE = "No rule package is loaded, so no source can be cited for it."


def _body_text(guidance_id: StrEnum, context: str, package: RulePackage | None = None) -> str:
    guidance = guidance_for(guidance_id)
    sections = [guidance.detailed_text]
    if guidance.examples:
        sections.append(_bullets("Examples", guidance.examples))
    if guidance.common_mistakes:
        sections.append(_bullets("Common mistakes", guidance.common_mistakes))
    if context.strip():
        sections.append(f"Recorded for this field:\n{context.strip()}")
    provenance = _provenance_section(guidance, package)
    if provenance:
        sections.append(provenance)
    return "\n\n".join(sections)


def _provenance_section(guidance: VoltageGuidance, package: RulePackage | None) -> str:
    """The rules this guidance names, and where the active package read each one from.

    Omitted entirely when the guidance names no rule — a voltage-stress field explains
    itself and cites nothing, and an empty heading would only suggest something is missing.
    """
    named = rule_provenance(package, _guidance_text(guidance))
    if not named:
        return ""
    if package is None:
        return f"{GUIDANCE_AUTHORSHIP_NOTE} {NO_PACKAGE_FOR_PROVENANCE}"
    heading = (
        f"{GUIDANCE_AUTHORSHIP_NOTE} The rules it names are read from the active rule package, at:"
    )
    lines = [heading]
    for entry in named:
        lines.append(f"  • {entry.rule_id}: {citation(entry.source) or RULE_NOT_IN_PACKAGE}")
    return "\n".join(lines)


def _guidance_text(guidance: VoltageGuidance) -> str:
    """Every part of an entry a rule id can be named in, as one searchable block."""
    return "\n".join((guidance.detailed_text, *guidance.examples, *guidance.common_mistakes))


def _bullets(heading: str, lines: tuple[str, ...]) -> str:
    return "\n".join((f"{heading}:", *(f"  • {line}" for line in lines)))


class HelpIndicator(QToolButton):
    """A focusable ⓘ beside a field label, explaining the field it belongs to."""

    details_requested = Signal(str)

    def __init__(self, guidance_id: StrEnum, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guidance_id = guidance_id
        self._context = ""
        self._package: RulePackage | None = None
        self.setText(_HELP_GLYPH)
        self.set_guidance(guidance_id)
        self.setAutoRaise(True)
        # Tab-reachable: hover-only help is help that a keyboard user cannot get to.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Derived from the font rather than fixed in pixels, so the target stays
        # clickable when the display scales.
        side = self.fontMetrics().height() + 6
        self.setMinimumSize(side, side)
        self.clicked.connect(self._on_activated)

    @property
    def guidance_id(self) -> StrEnum:
        return self._guidance_id

    def set_guidance(self, guidance_id: StrEnum) -> None:
        """Point the control at another explanation, as a changing state does."""
        self._guidance_id = guidance_id
        guidance = guidance_for(guidance_id)
        self.setToolTip(guidance.short_text)
        self.setAccessibleName(accessible_help_name(guidance_id))
        self.setAccessibleDescription(guidance.short_text)

    def set_context(self, context: str) -> None:
        """Attach field-specific detail — an N/A justification, a value's provenance."""
        self._context = context

    def set_rules_package(self, package: RulePackage | None) -> None:
        """Let the long form cite the rules its guidance names, from this package."""
        self._package = package

    def open_details(self) -> GuidanceDialog:
        """Show the long form. Non-modal ``open`` so it never blocks the editor."""
        dialog = GuidanceDialog(self._guidance_id, self._context, self, self._package)
        dialog.open()
        return dialog

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        QToolTip.hideText()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter activates as Space already does; every other key is passed on.

        QAbstractButton answers Space by itself but leaves Return alone, and a
        control that offers only one of the two is not keyboard-accessible.
        """
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)

    def _on_activated(self) -> None:
        self.details_requested.emit(self._guidance_id.value)
        self.open_details()


#: Shown where no state has been decided, so the badge column never collapses.
_NO_STATE_TEXT = "—"


class FieldStateBadge(HelpIndicator):
    """Says in words where a value came from, and explains that state on demand.

    Colour is never the only signal: the state is spelled out, and activating the
    badge opens the same guidance the ⓘ beside the label would.
    """

    def __init__(
        self,
        state: VoltageGuidanceId | None = None,
        states: tuple[VoltageGuidanceId, ...] = FIELD_STATE_IDS,
        parent: QWidget | None = None,
    ):
        super().__init__(VoltageGuidanceId.INHERITED_DEFAULT, parent)
        # Wide enough for the longest state this field can reach, from the start:
        # a value that turns out to be derived must not shove its field sideways.
        # Pass every state the field can take, or the width will move when one
        # that was left out arrives.
        advance = self.fontMetrics().horizontalAdvance
        widest = max(advance(field_state_label(state_id)) for state_id in states)
        self.setMinimumWidth(widest + 12)
        self.set_state(state)

    def set_state(self, state: VoltageGuidanceId | None) -> None:
        """Show ``state``; ``None`` means nobody has answered this field yet."""
        if state is None:
            self.setText(_NO_STATE_TEXT)
            self.setToolTip("")
            self.setAccessibleName("No value entered")
            # Nothing to explain about an unanswered field, so it is not a stop
            # on the keyboard path either.
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self.set_guidance(state)
        self.setText(field_state_label(state))


def labelled(text: str, help_indicator: HelpIndicator) -> QWidget:
    """A form label with its ⓘ beside it, so the help never sits inside the value.

    It lives beside the control it carries because every page that puts help on a form
    needs the same row, and two copies of it drift.
    """
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(text))
    row.addWidget(help_indicator)
    row.addStretch(1)
    return container
