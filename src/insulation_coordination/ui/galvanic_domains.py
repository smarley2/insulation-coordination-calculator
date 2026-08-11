"""The galvanic domain editor: what domains a project's nets group into.

A domain records a name, a description, and whether it is the direct/source side of the
equipment - nothing about isolation itself. Isolation is a property of a *pair* of domains
and belongs to the barrier editor (a sibling panel on the same page), not to this one.

The actual project edits - adding, renaming, describing, promoting, and remap-and-deleting
a domain - are pure functions in
:mod:`insulation_coordination.project.topology_edits`, reusable outside this panel. This
module is a thin Qt wrapper around them: every action method reads the current project,
calls the matching function, and emits the complete replacement; the rule tests exercise
those functions directly and need no event loop.
"""

from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.enums import BarrierVerificationStatus
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.topology import GalvanicDomain
from insulation_coordination.project.topology_edits import (
    DomainDeletionPreview,
    add_domain,
    preview_domain_deletion,
    remap_and_delete_domain,
    rename_domain,
    set_direct_domain,
    set_domain_description,
)

_DOMAIN_ID_ROLE = Qt.ItemDataRole.UserRole

# --- Qt widget -------------------------------------------------------------------------


class GalvanicDomainsPanel(QWidget):
    """Lists a project's galvanic domains and edits them through the functions above.

    Every action method here reads the whole current project, calls the matching pure
    function, and emits the complete replacement project - it holds no editing logic of
    its own, only the list/description widgets and the dialogs that gather a name or a
    replacement domain from the user.
    """

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None

        group = QGroupBox("Galvanic domains")
        row = QHBoxLayout(group)

        self._list = QListWidget()
        row.addWidget(self._list, 1)

        controls = QVBoxLayout()
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("Selected domain description")
        self._description_edit.editingFinished.connect(self._on_description_changed)
        controls.addWidget(self._description_edit)

        self._add_button = QPushButton("Add")
        self._add_button.clicked.connect(self._on_add_clicked)
        controls.addWidget(self._add_button)

        self._rename_button = QPushButton("Rename")
        self._rename_button.clicked.connect(self._on_rename_clicked)
        controls.addWidget(self._rename_button)

        self._set_direct_button = QPushButton("Set as Direct Source")
        self._set_direct_button.clicked.connect(self._on_set_direct_clicked)
        controls.addWidget(self._set_direct_button)

        self._delete_button = QPushButton("Delete…")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        controls.addWidget(self._delete_button)
        controls.addStretch(1)
        row.addLayout(controls)

        outer = QVBoxLayout(self)
        outer.addWidget(group)

        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._on_selection_changed(-1)

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    def set_project(self, project: Project) -> None:
        self._project = project
        self._refresh_list()

    def _refresh_list(self) -> None:
        """Rebuild the list, keeping whichever domain was selected selected."""
        selected = self._list.currentItem()
        selected_id = None if selected is None else selected.data(_DOMAIN_ID_ROLE)
        self._list.clear()
        if self._project is None:
            return
        for domain in self._project.galvanic_domains:
            label = f"{domain.name} (direct)" if domain.is_direct_source_domain else domain.name
            item = QListWidgetItem(label)
            item.setData(_DOMAIN_ID_ROLE, str(domain.id))
            self._list.addItem(item)
        if selected_id is not None:
            restored = next(
                (
                    index
                    for index, domain in enumerate(self._project.galvanic_domains)
                    if str(domain.id) == selected_id
                ),
                None,
            )
            if restored is not None:
                self._list.setCurrentRow(restored)
        self._on_selection_changed(self._list.currentRow())

    def _domain_at(self, row: int) -> GalvanicDomain | None:
        if self._project is None or row < 0 or row >= len(self._project.galvanic_domains):
            return None
        return self._project.galvanic_domains[row]

    def _on_selection_changed(self, row: int) -> None:
        domain = self._domain_at(row)
        self._description_edit.blockSignals(True)
        self._description_edit.setText("" if domain is None else domain.description)
        self._description_edit.blockSignals(False)
        enabled = domain is not None
        for widget in (
            self._description_edit,
            self._rename_button,
            self._set_direct_button,
            self._delete_button,
        ):
            widget.setEnabled(enabled)

    # -- actions: usable directly (by tests and by the dialog handlers below) -------

    def add_domain(self, name: str, description: str = "") -> None:
        self._apply(add_domain(self.project, name, description))

    def rename_domain(self, domain_id: UUID, new_name: str) -> None:
        self._apply(rename_domain(self.project, domain_id, new_name))

    def set_description(self, domain_id: UUID, description: str) -> None:
        self._apply(set_domain_description(self.project, domain_id, description))

    def set_direct_domain(self, domain_id: UUID) -> None:
        self._apply(set_direct_domain(self.project, domain_id))

    def remap_and_delete_domain(self, domain_id: UUID, replacement_id: UUID | None) -> None:
        self._apply(remap_and_delete_domain(self.project, domain_id, replacement_id))

    def _apply(self, project: Project) -> None:
        self._project = project
        self._refresh_list()
        self.project_changed.emit(self._project)

    # -- Qt glue: gather input, then delegate to the actions above -------------------

    def _on_add_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Galvanic Domain", "Name:")
        if ok and name.strip():
            try:
                self.add_domain(name.strip())
            except ValueError as error:
                QMessageBox.warning(self, "Add Galvanic Domain", str(error))

    def _on_rename_clicked(self) -> None:
        domain = self._domain_at(self._list.currentRow())
        if domain is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Domain", "Name:", text=domain.name)
        if ok and name.strip():
            try:
                self.rename_domain(domain.id, name.strip())
            except ValueError as error:
                QMessageBox.warning(self, "Rename Domain", str(error))

    def _on_set_direct_clicked(self) -> None:
        domain = self._domain_at(self._list.currentRow())
        if domain is None:
            return
        self.set_direct_domain(domain.id)

    def _on_description_changed(self) -> None:
        domain = self._domain_at(self._list.currentRow())
        if domain is None:
            return
        try:
            self.set_description(domain.id, self._description_edit.text())
        except ValueError as error:
            QMessageBox.warning(self, "Domain Description", str(error))

    def _on_delete_clicked(self) -> None:
        if self._project is None:
            return
        domain = self._domain_at(self._list.currentRow())
        if domain is None:
            return

        others = tuple(d for d in self._project.galvanic_domains if d.id != domain.id)
        replacement_id: UUID | None = None
        if others:
            names = [d.name for d in others]
            choice, ok = QInputDialog.getItem(
                self, "Delete Domain", f"Replace '{domain.name}' with:", names, 0, False
            )
            if not ok:
                return
            replacement_id = next(d.id for d in others if d.name == choice)

        try:
            preview = preview_domain_deletion(self._project, domain.id, replacement_id)
        except ValueError as error:
            QMessageBox.warning(self, "Delete Domain", str(error))
            return

        reply = QMessageBox.question(
            self, "Confirm Domain Deletion", _describe_preview(preview, self._project)
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.remap_and_delete_domain(domain.id, replacement_id)
        except ValueError as error:
            QMessageBox.warning(self, "Delete Domain", str(error))


def _describe_preview(preview: DomainDeletionPreview, project: Project) -> str:
    """Explain what a remap-and-delete will do, naming every barrier it drops.

    A dropped barrier is not moved anywhere - its verification record, if any, is gone.
    That is worth stating for every dropped barrier, not just their count, and worth
    calling out specifically when the lost record was a verified isolation: that is the
    one status this application treats as evidence, and losing it silently would be the
    kind of thing a reviewer needs to have been told about, not discover later.
    """
    lines = [f"Delete '{preview.domain.name}'?"]
    if preview.replacement is not None:
        lines.append(f"{len(preview.nets)} net(s) will move to '{preview.replacement.name}'.")
        lines.append(f"{len(preview.remapped_barriers)} barrier(s) will move to the replacement.")
    else:
        lines.append(f"{len(preview.nets)} net(s) will be left without a domain.")
    if preview.dropped_barriers:
        names_by_id = {domain.id: domain.name for domain in project.galvanic_domains}
        lines.append(f"{len(preview.dropped_barriers)} barrier(s) will be dropped, not moved:")
        for barrier in preview.dropped_barriers:
            other_id = (
                barrier.domain_b_id
                if barrier.domain_a_id == preview.domain.id
                else barrier.domain_a_id
            )
            other_name = names_by_id.get(other_id, "?")
            if barrier.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
                lines.append(
                    f"  - vs '{other_name}': verified galvanic isolation record will be lost"
                )
            else:
                lines.append(f"  - vs '{other_name}'")
    return "\n".join(lines)
