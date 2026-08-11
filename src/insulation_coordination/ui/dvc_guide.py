"""The DVC guide: what a decisive voltage class means, read from the active package.

A decisive voltage class (DVC A-s, B, or C) is an engineer's own classification of a
circuit - never something this application derives or recommends. What *does* follow
from a class, once assigned, is which voltage limits and protection requirements the
active rule package associates with it. This dialog shows exactly those two things,
through :class:`~insulation_coordination.domain.dvc.DvcGuidanceService`, plus a short,
fixed explanation of how the underlying voltage quantities relate to each other. It
carries no IEC content of its own: every number, reference, and "not applicable" comes
from the package, with the clause, table, and page it was read from.

Like :class:`~insulation_coordination.ui.help_indicator.GuidanceDialog`, the body is a
single word-wrapped, selectable, scrollable label behind a Close button - plain text
that a screen reader, a browser find, or a copy-paste can reach, rather than a custom
search feature. To look at a different class, close the dialog, change the DVC
dropdown, and reopen it; the dialog itself does not offer a second way to pick one.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.dvc import (
    DvcGuidanceService,
    DvcLimitSummary,
    DvcProtectionSummary,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.domain.rules import SourceReference

_DIALOG_WIDTH = 520
_DIALOG_HEIGHT = 480

_DVC_TITLES: dict[DecisiveVoltageClass, str] = {
    DecisiveVoltageClass.NOT_EVALUATED: "not evaluated",
    DecisiveVoltageClass.DVC_AS: "DVC A-s",
    DecisiveVoltageClass.DVC_B: "DVC B",
    DecisiveVoltageClass.DVC_C: "DVC C",
}

#: This application's own explanation of how the four Table 2 voltage quantities and
#: the fault-time behaviour relate - paraphrasing no clause and stating no number.
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

#: Maintainer confirmed 2026-08-11: DVC A-s here always shows the dry-condition row.
#: The wet and salt-water-wet row exists in the source but has no enum member, so this
#: sentence is the only place that says so - see domain.dvc.VOLTAGE_LIMITS_ROW_TOKENS.
DVC_AS_CONDITION_NOTE = (
    "These are the dry-condition limits for DVC A-s. Wet and salt-water-wet conditions "
    "are stricter and are not shown here."
)


def _cite(source: SourceReference | None) -> str:
    if source is None:
        return ""
    parts = [f"{source.standard} {source.edition}"]
    if source.table:
        parts.append(f"Table {source.table}")
    if source.clause:
        parts.append(f"clause {source.clause}")
    if source.page is not None:
        parts.append(f"p.{source.page}")
    return ", ".join(parts)


def _render_limits(summary: DvcLimitSummary) -> str:
    if not summary.available:
        return f"Voltage limits: not available from the active package. {summary.reason}"
    lines = ["Voltage limits (from the active rule package):"]
    for quantity in summary.quantities:
        citation = _cite(quantity.source)
        suffix = f" [{citation}]" if citation else ""
        if quantity.status == "value":
            lines.append(f"  • {quantity.label}: {quantity.value} {quantity.unit}{suffix}")
        elif quantity.status == "reference":
            lines.append(f"  • {quantity.label}: refers to {quantity.reference_rule_id}{suffix}")
        elif quantity.status == "not_applicable":
            lines.append(f"  • {quantity.label}: not applicable{suffix}")
        else:
            lines.append(f"  • {quantity.label}: no data in the active package for this cell")
    return "\n".join(lines)


def _render_protection(summary: DvcProtectionSummary) -> str:
    if not summary.available:
        return (
            "Protection requirements: not available from the active package. "
            f"{summary.reason}"
        )
    if not summary.relationships:
        return "Protection requirements: none recorded in the active package for this class."
    lines = ["Protection requirements (from the active rule package):"]
    for item in summary.relationships:
        citation = _cite(item.source)
        suffix = f" [{citation}]" if citation else ""
        lines.append(f"  • {item.protection_context}: {item.requirement}{suffix}")
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

        self._body = QLabel(dvc_guide_body_text(service, dvc))
        self._body.setObjectName("_dvc_guide_body")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

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


__all__ = [
    "DVC_AS_CONDITION_NOTE",
    "STRESS_BASIS_EXPLANATION",
    "DvcGuideDialog",
    "dvc_guide_body_text",
]
