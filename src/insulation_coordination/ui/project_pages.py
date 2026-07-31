from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.project import (
    NetClass,
    Project,
)
from insulation_coordination.project.pairs import reconcile_pairs
from insulation_coordination.project.persistence import (
    ProjectLoadError,
    load_project,
    save_project_atomic,
)


class ProjectPage(QWidget):
    """Project defaults and net-class editing page."""

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._dirty = False

        layout = QVBoxLayout(self)

        title_label = QLabel("Project")
        title_label.setStyleSheet("font-weight: bold; font-size: 14pt;")
        layout.addWidget(title_label)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Project title")
        self._title_edit.textChanged.connect(self._on_title_changed)
        layout.addWidget(QLabel("Title:"))
        layout.addWidget(self._title_edit)

        rules_layout = QHBoxLayout()
        rules_layout.addWidget(QLabel("Rules package:"))
        self._rules_label = QLabel("(none)")
        rules_layout.addWidget(self._rules_label)
        layout.addLayout(rules_layout)

        layout.addWidget(QLabel("Net classes:"))
        self._net_list = QListWidget()
        layout.addWidget(self._net_list)

        button_layout = QHBoxLayout()
        self._add_button = QPushButton("Add")
        self._add_button.clicked.connect(self._on_add_clicked)
        button_layout.addWidget(self._add_button)

        self._rename_button = QPushButton("Rename")
        self._rename_button.clicked.connect(self._on_rename_clicked)
        button_layout.addWidget(self._rename_button)

        self._delete_button = QPushButton("Delete")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        button_layout.addWidget(self._delete_button)

        layout.addLayout(button_layout)

    @property
    def project(self) -> Project:
        if self._project is None:
            raise RuntimeError("No project loaded")
        return self._project

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_saved(self) -> None:
        self._dirty = False

    def load_project(self, project: Project) -> None:
        self._project = project
        self._dirty = False
        self._title_edit.blockSignals(True)
        self._title_edit.setText(project.metadata.title)
        self._title_edit.blockSignals(False)
        rules = project.required_rules
        self._rules_label.setText(f"{rules.package_id} v{rules.version}")
        self._refresh_net_list()

    def open_project(self, path: Path) -> None:
        try:
            project = load_project(Path(path))
        except ProjectLoadError as error:
            QMessageBox.critical(self, "Open Project", str(error))
            return
        self.load_project(project)

    def save_project(self, path: Path) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        save_project_atomic(Path(path), self._project)
        self._dirty = False

    def add_net_class(self, name: str) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        name = name.strip()
        if not name:
            raise ValueError("Net-class name must not be empty")
        existing_names = self._project.net_class_names
        if name in existing_names:
            raise ValueError(f"Net-class name '{name}' already exists")
        net_class = NetClass(id=uuid4(), name=name)
        net_classes = (*self._project.net_classes, net_class)
        pairs = reconcile_pairs(net_classes, self._project.pairs)
        self._update_project(net_classes=net_classes, pairs=pairs)

    def rename_net_class(self, index: int, new_name: str) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Net-class name must not be empty")
        net_classes = list(self._project.net_classes)
        if index < 0 or index >= len(net_classes):
            raise IndexError("Net-class index out of range")
        other_names = [nc.name for i, nc in enumerate(net_classes) if i != index]
        if new_name in other_names:
            raise ValueError(f"Net-class name '{new_name}' already exists")
        old = net_classes[index]
        net_classes[index] = old.model_copy(update={"name": new_name})
        self._update_project(net_classes=tuple(net_classes))

    def delete_net_class(self, index: int) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        net_classes = list(self._project.net_classes)
        if index < 0 or index >= len(net_classes):
            raise IndexError("Net-class index out of range")
        del net_classes[index]
        pairs = reconcile_pairs(tuple(net_classes), self._project.pairs)
        self._update_project(net_classes=tuple(net_classes), pairs=pairs)

    def _update_project(self, **updates: object) -> None:
        self._project = self._project.model_copy(update=updates)  # type: ignore[union-attr]
        self._dirty = True
        self._refresh_net_list()
        self.project_changed.emit(self._project)

    def _refresh_net_list(self) -> None:
        self._net_list.clear()
        if self._project is None:
            return
        for net_class in self._project.net_classes:
            item = QListWidgetItem(net_class.name)
            self._net_list.addItem(item)

    def _on_title_changed(self, text: str) -> None:
        if self._project is None:
            return
        metadata = self._project.metadata.model_copy(update={"title": text})
        self._update_project(metadata=metadata)

    def _on_add_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Add Net Class", "Name:")
        if ok and name.strip():
            try:
                self.add_net_class(name.strip())
            except ValueError as error:
                QMessageBox.warning(self, "Add Net Class", str(error))

    def _on_rename_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        row = self._net_list.currentRow()
        if row < 0:
            return
        current_name = self._net_list.item(row).text()
        name, ok = QInputDialog.getText(
            self, "Rename Net Class", "Name:", text=current_name
        )
        if ok and name.strip():
            try:
                self.rename_net_class(row, name.strip())
            except (ValueError, IndexError) as error:
                QMessageBox.warning(self, "Rename Net Class", str(error))

    def _on_delete_clicked(self) -> None:
        row = self._net_list.currentRow()
        if row < 0:
            return
        name = self._net_list.item(row).text()
        reply = QMessageBox.question(
            self,
            "Delete Net Class",
            f"Delete '{name}'? This removes all pairs involving it.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_net_class(row)
