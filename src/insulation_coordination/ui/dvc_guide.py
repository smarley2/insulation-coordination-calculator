"""The DVC guide: what a decisive voltage class means, read from the active package.

A decisive voltage class (DVC A-s, B, or C) is an engineer's own classification of a
circuit - never something this application derives or recommends. What *does* follow
from a class, once assigned, is which voltage limits and protection requirements the
active rule package associates with it. This dialog shows exactly those two things,
through :class:`~insulation_coordination.domain.dvc.DvcGuidanceService`, plus a short,
fixed explanation of how the underlying voltage quantities relate to each other. It
carries no IEC content of its own: every number, reference, and "not applicable" comes
from the package, with the clause, table, and page it was read from.

The body is one read-only, word-wrapped, selectable document behind a Close button, with
a search field above it: Ctrl+F focuses the field, Enter and Shift+Enter step forward and
back through the matches, and the search runs against the text already rendered here - no
index, no network, nothing to load. Searching a document this short earns nothing more
elaborate than the text widget's own find. To look at a different class, close the dialog,
change the DVC dropdown, and reopen it; the dialog itself does not offer a second way to
pick one.

Where a cell defers to another rule the guide says so in words and names the rule, rather
than printing a number it cannot justify. The transient-impulse cell is the case that
matters: its requirement follows from a system voltage and an overvoltage category, which
issue #36 resolves from the project's supply. Until then this is a stated deferral, not a
gap - see :data:`~insulation_coordination.domain.dvc.DvcReferenceKind`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.dvc import (
    DvcGuidanceService,
    DvcLimitSummary,
    DvcProtectionSummary,
    DvcReferenceKind,
    DvcVoltageQuantity,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.domain.rule_provenance import citation

_DIALOG_WIDTH = 520
_DIALOG_HEIGHT = 480

_DVC_TITLES: dict[DecisiveVoltageClass, str] = {
    DecisiveVoltageClass.NOT_EVALUATED: "not evaluated",
    DecisiveVoltageClass.DVC_AS: "DVC A-s",
    DecisiveVoltageClass.DVC_B: "DVC B",
    DecisiveVoltageClass.DVC_C: "DVC C",
}

#: This application's own explanation of how the Table 2 voltage quantities and the
#: fault-time behaviour relate - paraphrasing no clause and stating no number.
STRESS_BASIS_EXPLANATION = (
    "A decisive voltage class is an engineer's own classification of a circuit - this "
    "application never derives or recommends one. Once a class is assigned, the active "
    "rule package's own voltage limits and protection requirements apply to it.\n\n"
    "Within those limits, a single, non-repetitive pulse is evaluated against the DC "
    "limit, while a pulse that repeats - every cycle or every switching period - is "
    "evaluated against the AC limits instead. A voltage that occurs only during an "
    "abnormal condition or a single fault is not judged against either fixed "
    "normal-operation limit on its own; it follows whatever time-voltage behaviour the "
    "package's fault-time rule states for that duration."
)

#: Maintainer confirmed 2026-08-11: DVC A-s here always shows the dry-condition reading.
#: A wet or salt-water-wet reading has no enum member, so this sentence is the only place
#: that says so to a reader - see domain.dvc.READ_ENVIRONMENTS for the selection itself.
DVC_AS_CONDITION_NOTE = (
    "These are the dry-condition limits for DVC A-s. The source distinguishes a second "
    "set of conditions - wet and salt-water-wet - for this class; this application has "
    "no way to select that condition and does not show it."
)

#: What a referring cell says instead of a number, per kind of deferral. Both name the
#: rule that answers the question and why this guide cannot answer it, so a reader is
#: never left to guess whether a number is missing or genuinely does not exist here.
_REFERENCE_TEXTS: dict[DvcReferenceKind, str] = {
    "supply_impulse": (
        "resolved from the applicable system-voltage and overvoltage-category rule "
        "({rule}). No single number applies here: the requirement depends on the "
        "project's own supply, which this guide does not read."
    ),
    "fault_time_curve": (
        "resolved from the fault-time voltage rule ({rule}), which states a "
        "time-voltage behaviour for the duration rather than one fixed limit."
    ),
}

#: Shown when the search ran off the end of the document and continued from the other.
SEARCH_WRAPPED_STATUS = "Continued from the other end of the guide."


def _reference_text(quantity: DvcVoltageQuantity) -> str:
    rule = quantity.reference_rule_id or "another rule in the active package"
    if quantity.reference_kind is None:
        return f"refers to {rule}"
    return _REFERENCE_TEXTS[quantity.reference_kind].format(rule=rule)


def _render_limits(summary: DvcLimitSummary) -> str:
    if not summary.available:
        return f"Voltage limits: not available from the active package. {summary.reason}"
    lines = ["Voltage limits (from the active rule package):"]
    for quantity in summary.quantities:
        cited = citation(quantity.source)
        suffix = f" [{cited}]" if cited else ""
        if quantity.status == "value":
            lines.append(f"  • {quantity.label}: {quantity.value} {quantity.unit}{suffix}")
        elif quantity.status == "reference":
            lines.append(f"  • {quantity.label}: {_reference_text(quantity)}{suffix}")
        else:
            lines.append(f"  • {quantity.label}: not applicable{suffix}")
    return "\n".join(lines)


def _render_protection(summary: DvcProtectionSummary) -> str:
    if not summary.available:
        return f"Protection requirements: not available from the active package. {summary.reason}"
    if not summary.relationships:
        return "Protection requirements: none recorded in the active package for this class."
    lines = ["Protection requirements (from the active rule package):"]
    for item in summary.relationships:
        cited = citation(item.source)
        suffix = f" [{cited}]" if cited else ""
        lines.append(f"  • {item.label}: {item.requirement}{suffix}")
    return "\n".join(lines)


def dvc_guide_body_text(service: DvcGuidanceService, dvc: DecisiveVoltageClass) -> str:
    """Compose the guide's text for ``dvc``, independent of any widget."""
    sections = [STRESS_BASIS_EXPLANATION]
    if dvc is DecisiveVoltageClass.DVC_AS:
        sections.append(DVC_AS_CONDITION_NOTE)
    sections.append(_render_limits(service.limits(dvc)))
    sections.append(_render_protection(service.protection_relationships(dvc)))
    return "\n\n".join(sections)


class DvcGuideDialog(QDialog):
    """Shows one decisive voltage class's limits and protection requirements."""

    def __init__(
        self,
        service: DvcGuidanceService,
        dvc: DecisiveVoltageClass,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"DVC guide - {_DVC_TITLES[dvc]}")
        self.resize(_DIALOG_WIDTH, _DIALOG_HEIGHT)

        # A browser rather than a label: it scrolls and wraps the same way, but it also
        # carries a document with a cursor, which is what makes find-and-highlight the
        # widget's job instead of this dialog's.
        self._body = QTextBrowser()
        self._body.setObjectName("_dvc_guide_body")
        self._body.setPlainText(dvc_guide_body_text(service, dvc))
        self._body.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)

        self._search_field = QLineEdit()
        self._search_field.setObjectName("_dvc_guide_search")
        self._search_field.setPlaceholderText("Search this guide")
        self._search_field.setAccessibleName("Search this guide")
        self._search_field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._search_field.returnPressed.connect(self.find_next)
        self._search_field.textChanged.connect(self._on_search_text_changed)

        self._previous_button = QPushButton("Previous")
        self._previous_button.setAutoDefault(False)
        self._previous_button.clicked.connect(self.find_previous)
        self._next_button = QPushButton("Next")
        self._next_button.setAutoDefault(False)
        self._next_button.clicked.connect(self.find_next)

        self._search_status = QLabel()
        self._search_status.setObjectName("_dvc_guide_search_status")

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_field, 1)
        search_row.addWidget(self._previous_button)
        search_row.addWidget(self._next_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Without this, Enter in the search field would reach the Close button as the
        # dialog's default and shut the guide instead of finding the next match.
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_button.setAutoDefault(False)
        close_button.setDefault(False)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addWidget(self._search_status)
        layout.addWidget(self._body)
        layout.addWidget(buttons)

        # The field is first in the layout, so it is also first on the tab path; Ctrl+F and
        # F3 exist for the reader who is already scrolling the body.
        QShortcut(QKeySequence.StandardKey.Find, self, self.focus_search)
        QShortcut(QKeySequence.StandardKey.FindNext, self, self.find_next)
        QShortcut(QKeySequence.StandardKey.FindPrevious, self, self.find_previous)
        # A dialog-level shortcut, not a key handler on the field: a shortcut is resolved
        # before the key reaches the focus widget, so this works while the field has focus.
        QShortcut(QKeySequence("Shift+Return"), self, self.find_previous)
        QShortcut(QKeySequence("Shift+Enter"), self, self.find_previous)

    def body_text(self) -> str:
        return self._body.toPlainText()

    def focus_search(self) -> None:
        """Put the caret in the search field, selecting whatever is already there."""
        self._search_field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search_field.selectAll()

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_previous(self) -> bool:
        return self._find(backward=True)

    def search_status(self) -> str:
        return self._search_status.text()

    def _on_search_text_changed(self, _text: str) -> None:
        """Clear a stale "no match" as soon as the term changes; do not search yet.

        Searching on every keystroke would drag the view around while a word is still
        being typed, and the term is short enough that Enter is no burden.
        """
        self._search_status.setText("")

    def _find(self, *, backward: bool) -> bool:
        term = self._search_field.text()
        if not term:
            self._search_status.setText("")
            return False
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self._body.find(term, flags):
            self._search_status.setText("")
            return True
        # Nothing further in this direction. Restart from the far end and try once more,
        # so a reader who started mid-document still sees the matches above them.
        cursor = self._body.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
        )
        self._body.setTextCursor(cursor)
        if self._body.find(term, flags):
            self._search_status.setText(SEARCH_WRAPPED_STATUS)
            return True
        self._search_status.setText(f'No match for "{term}".')
        return False


__all__ = [
    "DVC_AS_CONDITION_NOTE",
    "SEARCH_WRAPPED_STATUS",
    "STRESS_BASIS_EXPLANATION",
    "DvcGuideDialog",
    "dvc_guide_body_text",
]
