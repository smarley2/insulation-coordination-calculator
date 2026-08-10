"""The galvanic domain editor: what domains a project's nets group into.

A domain records a name, a description, and whether it is the direct/source side of the
equipment - nothing about isolation itself. Isolation is a property of a *pair* of domains
and belongs to the barrier editor (a sibling panel on the same page), not to this one.

Every transformation below is a pure, module-level function: it takes a :class:`Project`
and returns a replacement one, built with a single ``model_copy`` so the result is never
assembled through intermediate states that would each have to satisfy the project
validator on their own. The panel at the bottom of this module is a thin Qt wrapper around
them; the rule tests exercise the functions directly and need no event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

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
from insulation_coordination.domain.project import NetClass, Project
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain

_DOMAIN_ID_ROLE = Qt.ItemDataRole.UserRole

# --- pure project transformations ----------------------------------------------------


def _domain_by_id(project: Project, domain_id: UUID) -> GalvanicDomain:
    domain = next((d for d in project.galvanic_domains if d.id == domain_id), None)
    if domain is None:
        raise ValueError("Unknown galvanic domain")
    return domain


def _normalised(name: str) -> str:
    return name.strip().casefold()


def _requires_unique_name(project: Project, name: str, *, except_id: UUID | None = None) -> None:
    normalised = _normalised(name)
    for domain in project.galvanic_domains:
        if domain.id == except_id:
            continue
        if _normalised(domain.name) == normalised:
            raise ValueError(f"A galvanic domain named '{name.strip()}' already exists")


def add_domain(project: Project, name: str, description: str = "") -> Project:
    """Append a new domain, becoming the direct source domain if it is the first one.

    A project with any domains must have exactly one direct source domain, so the very
    first domain added has nothing to inherit that flag from and must carry it itself.
    """
    name = name.strip()
    if not name:
        raise ValueError("Domain name must not be empty")
    _requires_unique_name(project, name)
    domain = GalvanicDomain(
        id=uuid4(),
        name=name,
        description=description.strip(),
        is_direct_source_domain=not project.galvanic_domains,
    )
    return project.model_copy(update={"galvanic_domains": (*project.galvanic_domains, domain)})


def rename_domain(project: Project, domain_id: UUID, new_name: str) -> Project:
    """Rename a domain, keeping its id - renaming is never a delete-and-recreate."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Domain name must not be empty")
    _domain_by_id(project, domain_id)
    _requires_unique_name(project, new_name, except_id=domain_id)
    domains = tuple(
        domain.model_copy(update={"name": new_name}) if domain.id == domain_id else domain
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def set_domain_description(project: Project, domain_id: UUID, description: str) -> Project:
    _domain_by_id(project, domain_id)
    domains = tuple(
        domain.model_copy(update={"description": description.strip()})
        if domain.id == domain_id
        else domain
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def set_direct_domain(project: Project, domain_id: UUID) -> Project:
    """Make ``domain_id`` the direct source domain, clearing whichever one held it before.

    Both edits land in the one ``model_copy`` call, so the project is never left - even
    transiently - holding two direct source domains or none.
    """
    _domain_by_id(project, domain_id)
    domains = tuple(
        domain.model_copy(update={"is_direct_source_domain": domain.id == domain_id})
        for domain in project.galvanic_domains
    )
    return project.model_copy(update={"galvanic_domains": domains})


def referencing_nets(project: Project, domain_id: UUID) -> tuple[NetClass, ...]:
    """Every net currently assigned to ``domain_id``, in project order."""
    return tuple(net for net in project.net_classes if net.galvanic_domain_id == domain_id)


def referencing_barriers(project: Project, domain_id: UUID) -> tuple[GalvanicBarrier, ...]:
    """Every barrier that names ``domain_id`` on either side, in project order."""
    return tuple(
        barrier
        for barrier in project.galvanic_barriers
        if domain_id in (barrier.domain_a_id, barrier.domain_b_id)
    )


@dataclass(frozen=True)
class DomainDeletionPreview:
    """Everything a remap-and-delete would touch, computed before it is applied.

    ``dropped_barriers`` are referencing barriers that a remap would turn into either a
    self-loop (the other side was the replacement itself) or a duplicate of a barrier the
    replacement already has recorded against that same domain; neither can survive the
    project validator, so they are dropped rather than merged or reported as an error.
    """

    domain: GalvanicDomain
    replacement: GalvanicDomain | None
    nets: tuple[NetClass, ...]
    remapped_barriers: tuple[GalvanicBarrier, ...]
    dropped_barriers: tuple[GalvanicBarrier, ...]


def _resolve_replacement(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> GalvanicDomain | None:
    if replacement_id is None:
        if len(project.galvanic_domains) > 1:
            raise ValueError("A replacement domain is required while other domains remain")
        return None
    if replacement_id == domain_id:
        raise ValueError("Replacement domain must differ from the domain being deleted")
    return _domain_by_id(project, replacement_id)


def preview_domain_deletion(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> DomainDeletionPreview:
    domain = _domain_by_id(project, domain_id)
    replacement = _resolve_replacement(project, domain_id, replacement_id)
    barriers = referencing_barriers(project, domain_id)

    remapped: list[GalvanicBarrier] = []
    dropped: list[GalvanicBarrier] = []
    for barrier in barriers:
        other_id = barrier.domain_b_id if barrier.domain_a_id == domain_id else barrier.domain_a_id
        if replacement is None or other_id == replacement.id:
            # No replacement to move to, or the barrier is against the replacement itself -
            # remapping either side onto the other would self-loop, which is not a barrier.
            dropped.append(barrier)
            continue
        collides = any(
            b.id != barrier.id and {b.domain_a_id, b.domain_b_id} == {replacement.id, other_id}
            for b in project.galvanic_barriers
        )
        if collides:
            # The replacement already has a barrier recorded against this same domain.
            dropped.append(barrier)
        else:
            remapped.append(barrier)

    return DomainDeletionPreview(
        domain=domain,
        replacement=replacement,
        nets=referencing_nets(project, domain_id),
        remapped_barriers=tuple(remapped),
        dropped_barriers=tuple(dropped),
    )


def remap_and_delete_domain(
    project: Project, domain_id: UUID, replacement_id: UUID | None
) -> Project:
    """Delete ``domain_id``, moving every net and non-colliding barrier to the replacement.

    Applies as a single ``model_copy`` so the project only ever holds the fully-remapped
    state; pairs are untouched because a domain edit never changes which net classes exist.
    """
    preview = preview_domain_deletion(project, domain_id, replacement_id)
    replacement = preview.replacement
    replacement_domain_id = None if replacement is None else replacement.id

    net_classes = tuple(
        net.model_copy(update={"galvanic_domain_id": replacement_domain_id})
        if net.galvanic_domain_id == domain_id
        else net
        for net in project.net_classes
    )

    dropped_ids = {barrier.id for barrier in preview.dropped_barriers}
    remapped_ids = {barrier.id for barrier in preview.remapped_barriers}
    barriers = tuple(
        _remap_barrier(barrier, domain_id, replacement_domain_id)
        if barrier.id in remapped_ids
        else barrier
        for barrier in project.galvanic_barriers
        if barrier.id not in dropped_ids
    )

    domains: list[GalvanicDomain] = []
    for existing in project.galvanic_domains:
        if existing.id == domain_id:
            continue
        if (
            replacement is not None
            and existing.id == replacement.id
            and preview.domain.is_direct_source_domain
            and not existing.is_direct_source_domain
        ):
            existing = existing.model_copy(update={"is_direct_source_domain": True})
        domains.append(existing)

    return project.model_copy(
        update={
            "net_classes": net_classes,
            "galvanic_barriers": barriers,
            "galvanic_domains": tuple(domains),
        }
    )


def _remap_barrier(barrier: GalvanicBarrier, old_id: UUID, new_id: UUID | None) -> GalvanicBarrier:
    if new_id is None:
        raise AssertionError("a remapped barrier always has a replacement domain")
    if barrier.domain_a_id == old_id:
        return barrier.model_copy(update={"domain_a_id": new_id})
    return barrier.model_copy(update={"domain_b_id": new_id})


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
