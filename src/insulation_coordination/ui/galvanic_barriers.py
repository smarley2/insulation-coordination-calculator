"""The verified-barrier editor: what stands between two galvanic domains.

A barrier records the verification status of the element between a pair of domains -
not evaluated, no galvanic isolation, or verified galvanic isolation - and, only for the
verified case, the method and evidence reference that back the claim. ``domain_key`` on
:class:`GalvanicBarrier` (``insulation_coordination.domain.topology``) is the one place
that decides A-B and B-A are the same barrier; every transformation below refuses a
second barrier for a pair that already has one, matching that identity.

Every transformation is a pure, module-level function: it takes a :class:`Project` and
returns a replacement one. A barrier is rebuilt through :class:`GalvanicBarrier`'s own
constructor rather than ``model_copy`` whenever its verification fields change, because
``model_copy`` skips model validation - only the constructor actually runs
``_requires_consistent_verification`` and refuses a missing method or a blank evidence
reference with the domain model's own message. The panel at the bottom is a thin Qt
wrapper around these functions; the rule tests exercise the functions directly and need
no event loop.

Verified isolation recorded here grants no attenuation and no protection claim - it is a
recorded fact about the barrier, nothing more. A rule package deciding what that fact is
worth is out of scope for this editor.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.enums import BarrierVerificationStatus, VerificationMethod
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    barrier_between,
    domain_by_id,
)
from insulation_coordination.ui.help_indicator import HelpIndicator
from insulation_coordination.ui.topology_guidance import (
    TopologyGuidanceId,
    guidance_id_for_barrier_status,
)

# --- pure project transformations ----------------------------------------------------


def _barrier_by_id(project: Project, barrier_id: UUID) -> GalvanicBarrier:
    barrier = next((b for b in project.galvanic_barriers if b.id == barrier_id), None)
    if barrier is None:
        raise ValueError("Unknown galvanic barrier")
    return barrier


def _replace_barrier(project: Project, barrier_id: UUID, **updates: object) -> Project:
    """Rebuild one barrier through its constructor, so its own validator actually runs.

    ``model_copy`` would apply ``updates`` without checking the result, letting a
    verified status through with no evidence or a non-verified one with a stray method -
    both are exactly the states ``GalvanicBarrier`` exists to refuse.
    """
    barrier = _barrier_by_id(project, barrier_id)
    data = barrier.model_dump()
    data.update(updates)
    replacement = GalvanicBarrier(**data)
    barriers = tuple(
        replacement if existing.id == barrier_id else existing
        for existing in project.galvanic_barriers
    )
    return project.model_copy(update={"galvanic_barriers": barriers})


def add_barrier(
    project: Project, domain_a_id: UUID, domain_b_id: UUID, description: str = ""
) -> Project:
    """Record a new, not-yet-evaluated barrier between two domains.

    A-B and B-A are the same barrier: adding a second one for a pair that already has
    one recorded is refused rather than silently replacing or duplicating it.
    """
    domain_by_id(project, domain_a_id)
    domain_by_id(project, domain_b_id)
    if barrier_between(project, domain_a_id, domain_b_id) is not None:
        raise ValueError("A barrier already exists between these two domains")
    barrier = GalvanicBarrier(
        id=uuid4(),
        domain_a_id=domain_a_id,
        domain_b_id=domain_b_id,
        status=BarrierVerificationStatus.NOT_EVALUATED,
        description=description.strip(),
    )
    return project.model_copy(update={"galvanic_barriers": (*project.galvanic_barriers, barrier)})


def set_barrier_description(project: Project, barrier_id: UUID, description: str) -> Project:
    return _replace_barrier(project, barrier_id, description=description.strip())


def mark_verified(
    project: Project,
    barrier_id: UUID,
    verification_method: VerificationMethod | None,
    evidence_reference: str,
) -> Project:
    """Select verified galvanic isolation for a barrier, keeping its id.

    A missing method or a blank evidence reference is refused by
    ``GalvanicBarrier._requires_consistent_verification`` itself, with its own message -
    this function does not duplicate that check.
    """
    stripped = evidence_reference.strip()
    return _replace_barrier(
        project,
        barrier_id,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        verification_method=verification_method,
        evidence_reference=stripped or None,
    )


def unmark_verified(
    project: Project, barrier_id: UUID, new_status: BarrierVerificationStatus
) -> Project:
    """Move a barrier off verified isolation, clearing the fields only that status may carry.

    Restricted to the two non-verified statuses - the caller (the panel's uncheck dialog)
    always resolves to one of them, and this refuses anything else rather than silently
    accepting a wrong one.
    """
    if new_status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
        raise ValueError("Use mark_verified to select verified isolation")
    return _replace_barrier(
        project,
        barrier_id,
        status=new_status,
        verification_method=None,
        evidence_reference=None,
    )


def delete_barrier(project: Project, barrier_id: UUID) -> Project:
    """Remove one barrier record, leaving every domain, net, and pair untouched.

    Deleting is not a remap: unlike a domain delete, a barrier has nothing on either
    side to reassign the record to. This exists for the barrier recorded against the
    wrong pair - the fix there is to remove it and add the correct one, not to have no
    way back short of deleting an entire domain.
    """
    _barrier_by_id(project, barrier_id)
    barriers = tuple(b for b in project.galvanic_barriers if b.id != barrier_id)
    return project.model_copy(update={"galvanic_barriers": barriers})


def _describe_barrier_deletion(barrier: GalvanicBarrier, project: Project) -> str:
    """Name the two domains and call out a lost verified-isolation record explicitly.

    Mirrors ``ui.galvanic_domains._describe_preview``, which singles out a dropped
    verified barrier the same way: that is the one status this application treats as
    evidence, so discarding it is worth stating outright rather than leaving the user
    to notice it is gone afterwards.
    """
    names_by_id = {domain.id: domain.name for domain in project.galvanic_domains}
    domain_a = names_by_id.get(barrier.domain_a_id, "?")
    domain_b = names_by_id.get(barrier.domain_b_id, "?")
    lines = [f"Delete the barrier between '{domain_a}' and '{domain_b}'?"]
    if barrier.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
        lines.append("Its verified galvanic isolation record will be lost, not moved.")
    return "\n".join(lines)


# --- Qt widget -------------------------------------------------------------------------

_COLUMN_LABELS = (
    "Domain A",
    "Domain B",
    "Status",
    "Verification method",
    "Evidence / reference",
    "Description",
)
_STATUS_LABELS: dict[BarrierVerificationStatus, str] = {
    BarrierVerificationStatus.NOT_EVALUATED: "Not evaluated",
    BarrierVerificationStatus.NO_GALVANIC_ISOLATION: "No galvanic isolation",
    BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION: "Verified galvanic isolation",
}


class GalvanicBarriersPanel(QWidget):
    """Lists a project's galvanic barriers and edits them through the functions above.

    Every action method here reads the whole current project, calls the matching pure
    function, and emits the complete replacement project - it holds no editing logic of
    its own, only the table and the controls that gather input from the user.
    """

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None

        group = QGroupBox("Galvanic barriers")
        row = QHBoxLayout(group)

        self._table = QTableWidget(0, len(_COLUMN_LABELS))
        self._table.setHorizontalHeaderLabels(_COLUMN_LABELS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        row.addWidget(self._table, 2)

        controls = QVBoxLayout()
        self._add_button = QPushButton("Add…")
        self._add_button.clicked.connect(self._on_add_clicked)
        controls.addWidget(self._add_button)

        self._delete_button = QPushButton("Delete…")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        controls.addWidget(self._delete_button)

        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("Selected barrier description")
        self._description_edit.editingFinished.connect(self._on_description_changed)
        controls.addWidget(self._description_edit)

        verified_row = QHBoxLayout()
        self._verified_checkbox = QCheckBox("Verified galvanic isolation")
        self._verified_checkbox.toggled.connect(self._on_verified_toggled)
        verified_row.addWidget(self._verified_checkbox)
        self._verified_help = HelpIndicator(TopologyGuidanceId.BARRIER_NOT_EVALUATED)
        verified_row.addWidget(self._verified_help)
        verified_row.addStretch(1)
        controls.addLayout(verified_row)

        self._method_combo = QComboBox()
        self._method_combo.addItem("", None)
        for method in VerificationMethod:
            self._method_combo.addItem(method.value, method.value)
        self._method_combo.currentIndexChanged.connect(self._on_method_or_evidence_changed)
        controls.addWidget(self._method_combo)

        self._evidence_edit = QLineEdit()
        self._evidence_edit.setPlaceholderText("Evidence reference")
        self._evidence_edit.editingFinished.connect(self._on_method_or_evidence_changed)
        controls.addWidget(self._evidence_edit)

        controls.addStretch(1)
        row.addLayout(controls)

        outer = QVBoxLayout(self)
        outer.addWidget(group)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._populate_fields(None)

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    def set_project(self, project: Project) -> None:
        self._project = project
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Rebuild the table, keeping whichever barrier was selected selected."""
        selected = self._barrier_at(self._table.currentRow())
        selected_id = None if selected is None else selected.id
        self._table.setRowCount(0)
        if self._project is None:
            return
        domain_names = {domain.id: domain.name for domain in self._project.galvanic_domains}
        for barrier in self._project.galvanic_barriers:
            position = self._table.rowCount()
            self._table.insertRow(position)
            values = (
                domain_names.get(barrier.domain_a_id, "?"),
                domain_names.get(barrier.domain_b_id, "?"),
                _STATUS_LABELS[barrier.status],
                "" if barrier.verification_method is None else barrier.verification_method.value,
                barrier.evidence_reference or "",
                barrier.description,
            )
            for column, value in enumerate(values):
                self._table.setItem(position, column, QTableWidgetItem(value))
        if selected_id is not None:
            restored = next(
                (
                    index
                    for index, barrier in enumerate(self._project.galvanic_barriers)
                    if barrier.id == selected_id
                ),
                None,
            )
            if restored is not None:
                self._table.setCurrentCell(restored, 0)
                return
        self._populate_fields(self._barrier_at(self._table.currentRow()))

    def _barrier_at(self, row: int) -> GalvanicBarrier | None:
        if self._project is None or row < 0 or row >= len(self._project.galvanic_barriers):
            return None
        return self._project.galvanic_barriers[row]

    def _on_selection_changed(self) -> None:
        self._populate_fields(self._barrier_at(self._table.currentRow()))

    def _populate_fields(self, barrier: GalvanicBarrier | None) -> None:
        widgets = (
            self._description_edit,
            self._verified_checkbox,
            self._method_combo,
            self._evidence_edit,
        )
        for widget in widgets:
            widget.blockSignals(True)
        if barrier is None:
            self._description_edit.clear()
            self._verified_checkbox.setChecked(False)
            self._method_combo.setCurrentIndex(0)
            self._evidence_edit.clear()
        else:
            self._description_edit.setText(barrier.description)
            verified = barrier.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
            self._verified_checkbox.setChecked(verified)
            method_index = 0
            if barrier.verification_method is not None:
                found = self._method_combo.findData(barrier.verification_method.value)
                method_index = max(found, 0)
            self._method_combo.setCurrentIndex(method_index)
            self._evidence_edit.setText(barrier.evidence_reference or "")
            self._verified_help.set_guidance(guidance_id_for_barrier_status(barrier.status))
        # The method and evidence fields stay enabled whether or not the barrier is
        # currently verified: a user must be able to type the evidence reference
        # *before* checking the box, not only after - the box is what applies the
        # change, not what unlocks entering it.
        enabled = barrier is not None
        for widget in widgets:
            widget.setEnabled(enabled)
        for widget in widgets:
            widget.blockSignals(False)

    # -- actions: usable directly (by tests and by the dialog handlers below) -------

    def add_barrier(self, domain_a_id: UUID, domain_b_id: UUID, description: str = "") -> None:
        self._apply(add_barrier(self.project, domain_a_id, domain_b_id, description))

    def set_description(self, barrier_id: UUID, description: str) -> None:
        self._apply(set_barrier_description(self.project, barrier_id, description))

    def mark_verified(
        self,
        barrier_id: UUID,
        verification_method: VerificationMethod | None,
        evidence_reference: str,
    ) -> None:
        self._apply(mark_verified(self.project, barrier_id, verification_method, evidence_reference))

    def unmark_verified(self, barrier_id: UUID, new_status: BarrierVerificationStatus) -> None:
        self._apply(unmark_verified(self.project, barrier_id, new_status))

    def delete_barrier(self, barrier_id: UUID) -> None:
        self._apply(delete_barrier(self.project, barrier_id))

    def _apply(self, project: Project) -> None:
        self._project = project
        self._refresh_table()
        self.project_changed.emit(self._project)

    # -- Qt glue: gather input, then delegate to the actions above -------------------

    def _on_add_clicked(self) -> None:
        if self._project is None:
            return
        domains = self._project.galvanic_domains
        if len(domains) < 2:
            QMessageBox.warning(
                self, "Add Barrier", "At least two galvanic domains are required."
            )
            return
        names = [domain.name for domain in domains]
        name_a, ok = QInputDialog.getItem(self, "Add Barrier", "Domain A:", names, 0, False)
        if not ok:
            return
        name_b, ok = QInputDialog.getItem(self, "Add Barrier", "Domain B:", names, 0, False)
        if not ok:
            return
        domain_a = next(d for d in domains if d.name == name_a)
        domain_b = next(d for d in domains if d.name == name_b)
        try:
            self.add_barrier(domain_a.id, domain_b.id)
        except ValueError as error:
            QMessageBox.warning(self, "Add Barrier", str(error))

    def _on_delete_clicked(self) -> None:
        if self._project is None:
            return
        barrier = self._barrier_at(self._table.currentRow())
        if barrier is None:
            return
        reply = QMessageBox.question(
            self, "Delete Barrier", _describe_barrier_deletion(barrier, self._project)
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.delete_barrier(barrier.id)
        except ValueError as error:
            QMessageBox.warning(self, "Delete Barrier", str(error))

    def _on_description_changed(self) -> None:
        barrier = self._barrier_at(self._table.currentRow())
        if barrier is None:
            return
        try:
            self.set_description(barrier.id, self._description_edit.text())
        except ValueError as error:
            QMessageBox.warning(self, "Barrier Description", str(error))

    def _current_method(self) -> VerificationMethod | None:
        value = self._method_combo.currentData()
        return VerificationMethod(value) if value else None

    def _on_method_or_evidence_changed(self) -> None:
        """Apply a method or evidence edit while the barrier is already verified.

        Disabled (and thus unreachable) while the checkbox is unchecked, since a
        non-verified barrier must carry neither field.
        """
        barrier = self._barrier_at(self._table.currentRow())
        if barrier is None or not self._verified_checkbox.isChecked():
            return
        try:
            self.mark_verified(barrier.id, self._current_method(), self._evidence_edit.text())
        except ValueError as error:
            QMessageBox.warning(self, "Verified Galvanic Isolation", str(error))
            self._populate_fields(self._barrier_at(self._table.currentRow()))

    def _on_verified_toggled(self, checked: bool) -> None:
        barrier = self._barrier_at(self._table.currentRow())
        if barrier is None:
            return
        if checked:
            try:
                self.mark_verified(
                    barrier.id, self._current_method(), self._evidence_edit.text()
                )
            except ValueError as error:
                QMessageBox.warning(self, "Verified Galvanic Isolation", str(error))
                self._populate_fields(self._barrier_at(self._table.currentRow()))
            return
        choice = self._ask_unverified_state(barrier)
        if choice is None:
            self._populate_fields(self._barrier_at(self._table.currentRow()))
            return
        self.unmark_verified(barrier.id, choice)

    def _ask_unverified_state(
        self, barrier: GalvanicBarrier
    ) -> BarrierVerificationStatus | None:
        """Ask which state now holds; never silently pick one. ``None`` means cancelled."""
        box = QMessageBox(self)
        box.setWindowTitle("Unselect Verified Isolation")
        box.setText("Which state now holds between these two domains?")
        not_evaluated = box.addButton(
            _STATUS_LABELS[BarrierVerificationStatus.NOT_EVALUATED],
            QMessageBox.ButtonRole.AcceptRole,
        )
        no_isolation = box.addButton(
            _STATUS_LABELS[BarrierVerificationStatus.NO_GALVANIC_ISOLATION],
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is not_evaluated:
            return BarrierVerificationStatus.NOT_EVALUATED
        if clicked is no_isolation:
            return BarrierVerificationStatus.NO_GALVANIC_ISOLATION
        return None
