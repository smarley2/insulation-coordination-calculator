from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.project import Project
from insulation_coordination.project.persistence import (
    ProjectLoadError,
    load_project,
    save_project_atomic,
)
from insulation_coordination.ui.project_pages import ProjectPage


class MainWindow(QMainWindow):
    """Main desktop shell with navigation between pages."""

    project_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Insulation Coordination Calculator")
        self.resize(900, 600)

        self._project: Project | None = None
        self._dirty = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._project_page = ProjectPage()
        self._project_page.project_changed.connect(self._on_project_page_changed)
        self._stack.addWidget(self._project_page)

        self.setStatusBar(QStatusBar())
        self.statusBar().addWidget(QLabel("Ready"))

        self._build_menu()
        self._update_actions()

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def open_project(self, path: Path) -> None:
        try:
            project = load_project(Path(path))
        except ProjectLoadError as error:
            QMessageBox.critical(self, "Open Project", str(error))
            return
        self.open_project_from_project(project)

    def open_project_from_project(self, project: Project) -> None:
        self._project = project
        self._dirty = False
        self._project_page.load_project(project)
        self.statusBar().showMessage(f"Project: {project.metadata.title}")
        self._update_actions()

    def save_project(self, path: Path) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        save_project_atomic(Path(path), self._project)
        self._dirty = False
        self._project_page.mark_saved()
        self._update_actions()

    def _on_project_page_changed(self, project: Project) -> None:
        self._project = project
        self._dirty = True
        self.statusBar().showMessage(f"Project: {project.metadata.title} *")
        self.project_changed.emit(project)
        self._update_actions()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        self._new_action = QAction("&New", self)
        self._new_action.triggered.connect(self._on_new)
        file_menu.addAction(self._new_action)

        self._open_action = QAction("&Open…", self)
        self._open_action.triggered.connect(self._on_open)
        file_menu.addAction(self._open_action)

        self._save_action = QAction("&Save", self)
        self._save_action.triggered.connect(self._on_save)
        file_menu.addAction(self._save_action)

        self._save_as_action = QAction("Save &As…", self)
        self._save_as_action.triggered.connect(self._on_save_as)
        file_menu.addAction(self._save_as_action)

        file_menu.addSeparator()

        self._close_action = QAction("&Close", self)
        self._close_action.triggered.connect(self._on_close_project)
        file_menu.addAction(self._close_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _update_actions(self) -> None:
        has_project = self._project is not None
        self._save_action.setEnabled(has_project and self._dirty)
        self._save_as_action.setEnabled(has_project)
        self._close_action.setEnabled(has_project)

    def _on_new(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        from uuid import UUID

        from insulation_coordination.domain.project import (
            ProjectDefaults,
            ProjectMetadata,
            RulePackageReference,
        )

        project = Project(
            id=UUID(int=0),
            metadata=ProjectMetadata(title="Untitled"),
            application_version="0.1.0",
            required_rules=RulePackageReference(
                package_id="iec-60664",
                version="2020.1",
                sha256="0" * 64,
            ),
            defaults=ProjectDefaults(),
            net_classes=(),
            pairs=(),
        )
        self.open_project_from_project(project)
        self._dirty = True
        self._update_actions()

    def _on_open(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Insulation Coordination Project (*.icproj)"
        )
        if path:
            self.open_project(Path(path))

    def _on_save(self) -> None:
        if self._project is None:
            return
        path = getattr(self, "_last_save_path", None)
        if path is None:
            self._on_save_as()
            return
        self.save_project(Path(path))

    def _on_save_as(self) -> None:
        if self._project is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "Insulation Coordination Project (*.icproj)"
        )
        if path:
            self._last_save_path = path
            self.save_project(Path(path))

    def _on_close_project(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        self._project = None
        self._dirty = False
        self.statusBar().showMessage("Ready")
        self._update_actions()

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Discard Changes",
            "The current project has unsaved changes. Discard?",
        )
        return reply == QMessageBox.StandardButton.Yes
