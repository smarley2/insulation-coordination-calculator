"""The project's library of recorded voltage figures, and what each one is worth.

One row is one :class:`~insulation_coordination.domain.verification.VoltageEvidence` entry.
The left half of every row is what somebody recorded; the "Comparison" column on the right is
what :class:`~insulation_coordination.calculation.voltage_evidence.VoltageEvidenceService`
makes of it against every other entry for the same target and quantity. Nothing on this panel
decides which figure governs - it asks the service and shows the answer.

Four things about the presentation are deliberate.

*An unapproved figure never reads as an approved one.* The approval state is spelled out in
words in its own column, and the comparison beside it says in a sentence whether the entry
governs. The case that matters is a draft **above** the governing figure: it is the one a
reader would otherwise take for the answer, so its comparison says outright that a higher
figure is recorded and does not govern, and the summary above the table repeats it.

*Nothing is edited in place once it has been approved.* A draft is still somebody's working
note and may be corrected. An approved entry has been relied on, so changing it means
recording a revision: the original is superseded with a justification and the new figure joins
the library beside it, in one project update. Deletion exists, asks first, and is the only way
anything ever leaves.

*One action produces one project.* Every method here ends in a single replacement project
emitted once, so a half-applied change cannot exist and no widget holds a mutable copy.

*The filters narrow what is shown and nothing else.* Hiding a row never changes what governs;
the summary is always computed over every applicable entry, filtered or not.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.voltage_evidence import (
    GoverningEvidenceResult,
    VoltageEvidenceService,
)
from insulation_coordination.domain.display import pair_label
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    EvidenceTarget,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
)
from insulation_coordination.ui.help_indicator import HelpIndicator, labelled, wrapping_label
from insulation_coordination.ui.value_options import populate_combo
from insulation_coordination.ui.voltage_guidance import VoltageGuidanceId

COLUMN_LABELS: Final = (
    "Target",
    "Quantity",
    "Method",
    "Value",
    "Operating condition",
    "Source / evidence",
    "Approval",
    "Measurement",
    "Comparison",
)

#: Shown wherever a cell has nothing in it, so a column never collapses into blankness.
EMPTY_CELL: Final = "—"

#: The filter entry that selects every value of its field.
ANY_OPTION: Final = "Any"

#: Shown while the library is empty. Not a warning: a project that has recorded nothing is the
#: state every project starts in and the one every existing project is in.
NO_EVIDENCE_TEXT: Final = (
    "No voltage figures are recorded for this project yet. Nothing here is required before a "
    "clearance or creepage result; it is what a dielectric verification plan is established "
    "from."
)

#: The heading of the summary line, so a test can find it without matching a whole sentence.
GOVERNING_PREFIX: Final = "Governing: "

#: What the summary says when nothing approved was found for the summarised target.
NOTHING_GOVERNS_TEXT: Final = "no approved figure"

#: The comparison a reader must not miss. A draft above the governing figure is exactly the
#: entry that would be taken for the answer if the column said only "draft".
ABOVE_GOVERNING_TEXT: Final = "higher than the governing figure and awaiting a decision"

#: Refused rather than performed. An approved figure has been relied on, so correcting it is a
#: revision that leaves the original in place, not an edit that overwrites it.
EDIT_APPROVED_REFUSAL: Final = (
    "This entry is not a draft, so it cannot be edited in place. Record a revision instead: "
    "the entry is superseded with a justification and the new figure joins the library beside "
    "it."
)

#: Asked before an entry leaves the library for good.
DELETE_CONFIRMATION: Final = (
    "Delete this entry? It is removed from the project and from every report, and no record "
    "that it existed is kept. Superseding it instead keeps it and states why it no longer "
    "governs."
)

#: Which explanation the ⓘ beside the quantity field offers. Each quantity is asking the
#: question one of the existing stress-field entries already answers, so the registry is read
#: rather than added to - a second explanation of the same quantity is how two drift apart.
_QUANTITY_GUIDANCE: Final[dict[VoltageQuantityKind, VoltageGuidanceId]] = {
    VoltageQuantityKind.AC_RMS: VoltageGuidanceId.LONG_TERM_RMS,
    VoltageQuantityKind.DC_MEAN: VoltageGuidanceId.LONG_TERM_RMS,
    VoltageQuantityKind.RECURRING_PEAK: VoltageGuidanceId.RECURRING_PEAK,
    VoltageQuantityKind.IMPULSE: VoltageGuidanceId.TRANSIENT_OVERVOLTAGE,
    VoltageQuantityKind.TEMPORARY_OVERVOLTAGE: VoltageGuidanceId.TEMPORARY_OVERVOLTAGE,
}

_ID_ROLE = Qt.ItemDataRole.UserRole

_TARGET_COLUMN = COLUMN_LABELS.index("Target")


def _words(value: str) -> str:
    return value.replace("_", " ")


def _options(enum: type[StrEnum]) -> tuple[tuple[str, str], ...]:
    return tuple((_words(member.value), member.value) for member in enum)


def target_label(project: Project, target: EvidenceTarget) -> str:
    """What a target is called on screen: a net by name, a pair by both of its names."""

    if target.pair_id is not None:
        pair = project.pair_by_id(target.pair_id)
        return "unknown pair" if pair is None else f"pair {pair_label(project, pair)}"
    name = next(
        (net.name for net in project.net_classes if net.id == target.net_id),
        None,
    )
    return "unknown net" if name is None else f"net {name}"


def evidence_targets(project: Project) -> tuple[tuple[str, EvidenceTarget], ...]:
    """Every target a figure can be recorded against, nets first and then pairs."""

    nets = tuple(EvidenceTarget(net_id=net.id) for net in project.net_classes)
    pairs = tuple(EvidenceTarget(pair_id=pair.id) for pair in project.pairs)
    return tuple((target_label(project, target), target) for target in (*nets, *pairs))


def measurement_text(entry: VoltageEvidence) -> str:
    """Where the figure was measured and to what uncertainty, for an entry that was."""

    parts = [part for part in (entry.measurement_points, entry.tolerance_or_uncertainty) if part]
    return " / ".join(parts) if parts else EMPTY_CELL


def comparison_text(entry: VoltageEvidence, result: GoverningEvidenceResult) -> str:
    """How ``entry`` stands against everything else recorded for its target and quantity.

    Never a bare state name. A reader looking at this column is asking "is this the number",
    and the answer for an entry that is not is always why not.
    """

    governing = result.approved_value_v
    if entry.approval_state is EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION:
        return f"superseded, does not govern — {entry.approval_justification}"
    if entry.approval_state is EvidenceApprovalState.DRAFT:
        if governing is None or entry.value_v > governing:
            return f"draft, does not govern — {ABOVE_GOVERNING_TEXT}"
        return "draft, does not govern — awaiting a decision"
    if governing is not None and entry.value_v == governing:
        tied = len(result.governing) > 1
        return "governs, tied with another approved figure" if tied else "governs"
    return "approved, below the governing figure"


def governing_summary(project: Project, result: GoverningEvidenceResult) -> str:
    """One line naming what governs a target's quantity, and what is still outstanding.

    The outstanding half is not a footnote. An approved figure with a higher draft beside it
    is the case the whole approval gate exists for, and a summary that stopped at the approved
    number would be the one place in this application where a draft won.
    """

    subject = f"{target_label(project, result.target)}, {_words(result.quantity.value)}"
    value = (
        NOTHING_GOVERNS_TEXT if result.approved_value_v is None else f"{result.approved_value_v} V"
    )
    line = f"{GOVERNING_PREFIX}{subject} — {value}"
    drafts = result.awaiting_approval
    if drafts:
        highest = max(entry.value_v for entry in drafts)
        line += (
            f"; {len(drafts)} awaiting a decision, the highest at {highest} V, "
            "and none of them governs"
        )
    superseded = result.superseded
    if superseded:
        line += f"; {len(superseded)} superseded with justification"
    return line


class VoltageEvidencePanel(QWidget):
    """The project's evidence library: add, revise, approve, supersede, filter, delete.

    Every action produces one complete replacement project and emits it once, exactly as the
    supply-configuration and galvanic panels beside it do.
    """

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._service = VoltageEvidenceService()
        #: The targets offered by the filter and the form, in the order the combos show them.
        #: Kept so a row can be found from a combo index without re-deriving the order.
        self._targets: tuple[tuple[str, EvidenceTarget], ...] = ()

        group = QGroupBox("Working voltage evidence")
        outer = QVBoxLayout(group)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Target:"))
        self._filter_target = QComboBox()
        self._filter_target.currentIndexChanged.connect(lambda _index: self._refresh())
        filters.addWidget(self._filter_target, 1)
        filters.addWidget(QLabel("Quantity:"))
        self._filter_quantity = self._filter_combo(VoltageQuantityKind)
        filters.addWidget(self._filter_quantity)
        filters.addWidget(QLabel("Method:"))
        self._filter_method = self._filter_combo(VoltageEvidenceMethod)
        filters.addWidget(self._filter_method)
        self._filter_unresolved = QCheckBox("Unresolved only")
        self._filter_unresolved.setToolTip(
            "Show only entries whose target and quantity still have a decision outstanding."
        )
        self._filter_unresolved.stateChanged.connect(lambda _state: self._refresh())
        filters.addWidget(self._filter_unresolved)
        outer.addLayout(filters)

        row = QHBoxLayout()
        self._table = QTableWidget(0, len(COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.currentCellChanged.connect(self._on_row_changed)
        row.addWidget(self._table, 3)

        controls = QVBoxLayout()
        form_box = QGroupBox("Entry")
        form = QFormLayout(form_box)
        self._target_combo = QComboBox()
        form.addRow("Target:", self._target_combo)
        self._quantity_combo = QComboBox()
        populate_combo(self._quantity_combo, _options(VoltageQuantityKind), blank=False)
        self._quantity_help = HelpIndicator(VoltageGuidanceId.LONG_TERM_RMS)
        self._quantity_combo.currentIndexChanged.connect(lambda _index: self._show_quantity_help())
        form.addRow(labelled("Quantity:", self._quantity_help), self._quantity_combo)
        self._method_combo = QComboBox()
        populate_combo(self._method_combo, _options(VoltageEvidenceMethod), blank=False)
        form.addRow("Method:", self._method_combo)
        self._value_edit = QLineEdit()
        form.addRow("Value (V):", self._value_edit)
        self._condition_edit = QLineEdit()
        self._condition_edit.setPlaceholderText("The operating condition the figure holds under")
        form.addRow("Operating condition:", self._condition_edit)
        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText("The document, model or record behind it")
        form.addRow("Source / evidence:", self._source_edit)
        self._points_edit = QLineEdit()
        self._points_edit.setPlaceholderText("Where a measurement was taken")
        form.addRow("Measurement points:", self._points_edit)
        self._uncertainty_edit = QLineEdit()
        form.addRow("Tolerance / uncertainty:", self._uncertainty_edit)
        self._notes_edit = QLineEdit()
        form.addRow("Notes:", self._notes_edit)
        controls.addWidget(form_box)

        self._add_button = QPushButton("Add entry")
        self._add_button.clicked.connect(self._on_add_clicked)
        controls.addWidget(self._add_button)
        self._edit_button = QPushButton("Update draft")
        self._edit_button.setToolTip(
            "Correct the selected draft in place. Only a draft may be corrected this way."
        )
        self._edit_button.clicked.connect(self._on_edit_clicked)
        controls.addWidget(self._edit_button)
        self._revise_button = QPushButton("Record revision…")
        self._revise_button.setToolTip(
            "Supersede the selected entry with a justification and add the form's figure "
            "beside it. Nothing is overwritten."
        )
        self._revise_button.clicked.connect(self._on_revise_clicked)
        controls.addWidget(self._revise_button)
        self._approve_button = QPushButton("Approve for design")
        self._approve_button.clicked.connect(self._on_approve_clicked)
        controls.addWidget(self._approve_button)
        self._supersede_button = QPushButton("Supersede…")
        self._supersede_button.clicked.connect(self._on_supersede_clicked)
        controls.addWidget(self._supersede_button)
        self._delete_button = QPushButton("Delete…")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        controls.addWidget(self._delete_button)
        controls.addStretch(1)
        row.addLayout(controls, 2)
        outer.addLayout(row)

        self._summary = wrapping_label("")
        self._summary.setObjectName("_evidence_summary")
        outer.addWidget(self._summary)
        self._notice = wrapping_label(NO_EVIDENCE_TEXT)
        outer.addWidget(self._notice)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)
        self._refresh()

    # -- what the page reads back ------------------------------------------------------

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    @property
    def summary_text(self) -> str:
        return self._summary.text()

    @property
    def notice_text(self) -> str:
        return "" if self._notice.isHidden() else self._notice.text()

    @property
    def row_count(self) -> int:
        return self._table.rowCount()

    def row_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return "" if item is None else item.text()

    def row_of(self, entry_id: UUID) -> int:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.data(_ID_ROLE) == str(entry_id):
                return row
        raise LookupError(f"No row for voltage evidence {entry_id}")

    def select_entry(self, entry_id: UUID) -> None:
        self._table.setCurrentCell(self.row_of(entry_id), 0)

    # -- inputs ------------------------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self._project = project
        self._refresh_targets()
        self._refresh()

    # -- actions: usable directly, and by the buttons above ----------------------------

    def add_evidence(self, entry: VoltageEvidence) -> None:
        """Record one new figure. It starts as a draft unless the caller says otherwise."""

        self._apply((*self.project.voltage_evidence, entry))

    def update_draft(self, entry_id: UUID, **changes: object) -> None:
        """Correct a draft in place, refusing anything that is no longer one.

        A draft is still a working note. Once an entry is approved for design something has
        been dimensioned against it, and an edit that quietly moved the figure would leave a
        report citing an entry that never held the value it was read for.
        """

        entry = self._entry(entry_id)
        if entry.approval_state is not EvidenceApprovalState.DRAFT:
            raise ValueError(EDIT_APPROVED_REFUSAL)
        self._apply(self._replaced(entry_id, self._rebuilt(entry, changes)))

    def revise_evidence(
        self, entry_id: UUID, replacement: VoltageEvidence, justification: str
    ) -> None:
        """Supersede one entry and record ``replacement`` beside it, in one project update.

        Both halves land together or neither does. A revision that superseded the original and
        then failed to add its replacement would leave the target with nothing governing it,
        which is the one outcome a revision must never produce.
        """

        entry = self._entry(entry_id)
        superseded = self._rebuilt(
            entry,
            {
                "approval_state": EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION,
                "approval_justification": justification,
            },
        )
        self._apply((*self._replaced(entry_id, superseded), replacement))

    def set_approval(
        self, entry_id: UUID, state: EvidenceApprovalState, justification: str = ""
    ) -> None:
        """Approve an entry for design, or stand one down with the reason it no longer holds.

        The model refuses a supersession without a justification, and that refusal is the
        message a user reads: the rule is written once, where the entry is defined.
        """

        entry = self._entry(entry_id)
        self._apply(
            self._replaced(
                entry_id,
                self._rebuilt(
                    entry, {"approval_state": state, "approval_justification": justification}
                ),
            )
        )

    def remove_evidence(self, entry_id: UUID) -> None:
        """Delete one entry outright. The only way anything leaves the library."""

        self._apply(tuple(item for item in self.project.voltage_evidence if item.id != entry_id))

    def build_entry(self, entry_id: UUID | None = None) -> VoltageEvidence:
        """The entry the form currently describes, validated by the model that defines it."""

        target = self._selected_target(self._target_combo)
        if target is None:
            raise ValueError("Select the net or pair this figure is about")
        return VoltageEvidence(
            id=entry_id or uuid4(),
            pair_id=target.pair_id,
            net_id=target.net_id,
            quantity_kind=VoltageQuantityKind(str(self._quantity_combo.currentData())),
            value_v=Decimal(self._value_edit.text().strip()),
            method=VoltageEvidenceMethod(str(self._method_combo.currentData())),
            operating_condition=self._condition_edit.text().strip(),
            source_reference=self._source_edit.text().strip(),
            measurement_points=self._points_edit.text().strip(),
            tolerance_or_uncertainty=self._uncertainty_edit.text().strip(),
            recorded_at=datetime.now(UTC),
            approval_state=EvidenceApprovalState.DRAFT,
            notes=self._notes_edit.text().strip(),
        )

    # -- internals ---------------------------------------------------------------------

    def _entry(self, entry_id: UUID) -> VoltageEvidence:
        for item in self.project.voltage_evidence:
            if item.id == entry_id:
                return item
        raise LookupError(f"No voltage evidence {entry_id}")

    def _replaced(
        self, entry_id: UUID, replacement: VoltageEvidence
    ) -> tuple[VoltageEvidence, ...]:
        return tuple(
            replacement if item.id == entry_id else item for item in self.project.voltage_evidence
        )

    def _rebuilt(self, entry: VoltageEvidence, changes: dict[str, object]) -> VoltageEvidence:
        """Rebuild one entry through its own validation rather than through ``model_copy``.

        ``model_copy`` skips validation, so a measurement stripped of its measurement points or
        a supersession without a justification would be persisted rather than refused.
        """

        fields = dict(entry.model_dump(mode="python"))
        fields.update(changes)
        return VoltageEvidence.model_validate(fields)

    def _apply(self, entries: tuple[VoltageEvidence, ...]) -> None:
        self._project = self.project.model_copy(update={"voltage_evidence": entries})
        self._refresh()
        self.project_changed.emit(self._project)

    def _filter_combo(self, enum: type[StrEnum]) -> QComboBox:
        combo = QComboBox()
        combo.addItem(ANY_OPTION, None)
        for label, value in _options(enum):
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(lambda _index: self._refresh())
        return combo

    def _refresh_targets(self) -> None:
        """Re-offer the targets around whatever each combo was already showing."""

        self._targets = evidence_targets(self.project)
        for combo, blank in ((self._filter_target, ANY_OPTION), (self._target_combo, "")):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(blank, None)
            for label, target in self._targets:
                combo.addItem(label, target.model_dump_json())
            index = combo.findData(previous)
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)

    def _selected_target(self, combo: QComboBox) -> EvidenceTarget | None:
        data = combo.currentData()
        return None if data is None else EvidenceTarget.model_validate_json(str(data))

    def _selected_entry(self) -> VoltageEvidence | None:
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        if item is None:
            return None
        return self._entry(UUID(str(item.data(_ID_ROLE))))

    def _shown(self) -> tuple[VoltageEvidence, ...]:
        """The entries the filters leave visible. Filtering hides rows and decides nothing."""

        target = self._selected_target(self._filter_target)
        quantity = self._filter_quantity.currentData()
        method = self._filter_method.currentData()
        entries = self.project.voltage_evidence
        if target is not None:
            entries = tuple(item for item in entries if item.target == target)
        if quantity is not None:
            entries = tuple(item for item in entries if item.quantity_kind.value == quantity)
        if method is not None:
            entries = tuple(item for item in entries if item.method.value == method)
        if self._filter_unresolved.isChecked():
            entries = tuple(item for item in entries if self._result(item).unresolved_inputs)
        return entries

    def _result(self, entry: VoltageEvidence) -> GoverningEvidenceResult:
        """What governs the entry's own target and quantity, over every entry and not the shown ones."""

        return self._service.governing(self.project, entry.target, entry.quantity_kind)

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        if self._project is None:
            self._summary.setText("")
            self._notice.setText(NO_EVIDENCE_TEXT)
            self._notice.setVisible(True)
            self._update_buttons()
            return
        shown = self._shown()
        self._notice.setVisible(not self.project.voltage_evidence)
        self._table.setRowCount(len(shown))
        for row, entry in enumerate(shown):
            self._fill_row(row, entry)
        self._table.resizeColumnsToContents()
        self._summary.setText(self._summary_for(shown))
        self._update_buttons()

    def _fill_row(self, row: int, entry: VoltageEvidence) -> None:
        result = self._result(entry)
        cells = (
            target_label(self.project, entry.target),
            _words(entry.quantity_kind.value),
            _words(entry.method.value),
            f"{entry.value_v} V",
            entry.operating_condition,
            entry.source_reference,
            _words(entry.approval_state.value),
            measurement_text(entry),
            comparison_text(entry, result),
        )
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if column == _TARGET_COLUMN:
                item.setData(_ID_ROLE, str(entry.id))
            self._table.setItem(row, column, item)

    def _summary_for(self, shown: Iterable[VoltageEvidence]) -> str:
        """One governing line per target and quantity present among the shown rows."""

        seen: dict[tuple[str, str], GoverningEvidenceResult] = {}
        for entry in shown:
            key = (str(entry.target.model_dump_json()), entry.quantity_kind.value)
            if key not in seen:
                seen[key] = self._result(entry)
        return "\n".join(governing_summary(self.project, result) for result in seen.values())

    def _update_buttons(self) -> None:
        entry = None if self._project is None else self._selected_entry()
        for button in (
            self._edit_button,
            self._revise_button,
            self._approve_button,
            self._supersede_button,
            self._delete_button,
        ):
            button.setEnabled(entry is not None)
        if entry is not None:
            self._edit_button.setEnabled(entry.approval_state is EvidenceApprovalState.DRAFT)

    def _show_quantity_help(self) -> None:
        quantity = VoltageQuantityKind(str(self._quantity_combo.currentData()))
        self._quantity_help.set_guidance(_QUANTITY_GUIDANCE[quantity])

    def _on_row_changed(self, row: int, _column: int, _previous_row: int, _previous: int) -> None:
        self._update_buttons()
        entry = self._selected_entry()
        if entry is None:
            return
        self._target_combo.setCurrentIndex(
            max(self._target_combo.findData(entry.target.model_dump_json()), 0)
        )
        self._quantity_combo.setCurrentIndex(
            max(self._quantity_combo.findData(entry.quantity_kind.value), 0)
        )
        self._method_combo.setCurrentIndex(max(self._method_combo.findData(entry.method.value), 0))
        self._value_edit.setText(str(entry.value_v))
        self._condition_edit.setText(entry.operating_condition)
        self._source_edit.setText(entry.source_reference)
        self._points_edit.setText(entry.measurement_points)
        self._uncertainty_edit.setText(entry.tolerance_or_uncertainty)
        self._notes_edit.setText(entry.notes)

    def _on_add_clicked(self) -> None:
        self._guarded(lambda: self.add_evidence(self.build_entry()))

    def _on_edit_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        replacement = self._guarded(lambda: self.build_entry(entry.id))
        if replacement is not None:
            self._guarded(
                lambda: self.update_draft(
                    entry.id, **replacement.model_dump(mode="python", exclude={"id"})
                )
            )

    def _on_revise_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        justification, accepted = QInputDialog.getText(
            self, "Record revision", "Why does the recorded figure no longer hold?"
        )
        if not accepted:
            return
        self._guarded(lambda: self.revise_evidence(entry.id, self.build_entry(), justification))

    def _on_approve_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._guarded(
                lambda: self.set_approval(entry.id, EvidenceApprovalState.APPROVED_FOR_DESIGN)
            )

    def _on_supersede_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        justification, accepted = QInputDialog.getText(
            self, "Supersede entry", "Why does this figure no longer govern?"
        )
        if not accepted:
            return
        self._guarded(
            lambda: self.set_approval(
                entry.id,
                EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION,
                justification,
            )
        )

    def _on_delete_clicked(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete evidence",
            DELETE_CONFIRMATION,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self.remove_evidence(entry.id)

    def _guarded[T](self, action: object) -> T | None:
        """Run one action, showing whatever the model refused rather than raising into Qt."""

        assert callable(action)
        try:
            result: T = action()
        except (InvalidOperation, LookupError, ValueError) as error:
            QMessageBox.warning(self, "Voltage evidence", str(error))
            return None
        return result


__all__ = [
    "ABOVE_GOVERNING_TEXT",
    "ANY_OPTION",
    "COLUMN_LABELS",
    "DELETE_CONFIRMATION",
    "EDIT_APPROVED_REFUSAL",
    "EMPTY_CELL",
    "GOVERNING_PREFIX",
    "NOTHING_GOVERNS_TEXT",
    "NO_EVIDENCE_TEXT",
    "VoltageEvidencePanel",
    "comparison_text",
    "evidence_targets",
    "governing_summary",
    "measurement_text",
    "target_label",
]
