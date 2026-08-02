from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.enums import ConstructionType, FieldCondition, InsulationType
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.project.persistence import (
    ProjectLoadError,
    load_project,
    save_project_atomic,
)
from insulation_coordination.rules.installation import install_rule_package
from insulation_coordination.startup import StartupKind, classify_startup_path
from insulation_coordination.ui.pair_editor import PairPage
from insulation_coordination.ui.project_pages import ProjectPage
from insulation_coordination.ui.report_page import ReportPage


class MainWindow(QMainWindow):
    """Main desktop shell with navigation between pages."""

    project_changed = Signal(object)

    _PAGES = ("Project", "Pairs", "Report")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Insulation Coordination Calculator")
        self.resize(1000, 700)

        self._project: Project | None = None
        self._rules: RulePackage | None = None
        self._dirty = False
        self._current_page = 0

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._nav_buttons: dict[str, QPushButton] = {}
        nav_layout = QHBoxLayout()
        for index, name in enumerate(self._PAGES):
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, i=index: self._show_page(i))
            nav_layout.addWidget(button)
            self._nav_buttons[name] = button
        layout.addLayout(nav_layout)

        self._stack = QStackedWidget()
        self._stack.setMinimumSize(0, 0)
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._stack)
        layout.setStretch(1, 1)

        self._project_page = ProjectPage()
        self._project_page.project_changed.connect(self._on_project_changed)
        self._stack.addWidget(self._project_page)

        self._pair_page = PairPage()
        self._pair_page.setMinimumSize(0, 0)
        self._pair_page.project_changed.connect(self._on_project_changed)
        self._pair_page.rules_changed.connect(self._on_rules_changed)
        self._stack.addWidget(self._pair_page)

        self._report_page = ReportPage()
        self._stack.addWidget(self._report_page)

        self.setStatusBar(QStatusBar())
        self.statusBar().addWidget(QLabel("Ready"))

        self._build_menu()
        self._show_page(0)
        self._update_actions()
        self._on_new()

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def rules(self) -> RulePackage | None:
        return self._rules

    def open_project(self, path: Path) -> None:
        try:
            project = load_project(Path(path))
        except ProjectLoadError as error:
            QMessageBox.critical(self, "Open Project", str(error))
            return
        self.open_project_from_project(project)

    def open_document(self, path: Path) -> bool:
        try:
            request = classify_startup_path(path)
            if request.path is None:
                raise ValueError("startup document path is missing")
            if request.kind is StartupKind.PROJECT:
                project = load_project(request.path)
                self.open_project_from_project(project)
            else:
                installed = install_rule_package(request.path)
                self.load_rules(installed.package)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Open Document", str(error))
            return False
        return True

    def open_project_from_project(self, project: Project) -> None:
        self._project = project
        self._dirty = False
        self._project_page.load_project(project)
        if self._rules is not None:
            self._project_page.set_rules_package(self._rules)
        self._pair_page.load_project(project)
        self._report_page.load_project(project)
        self.statusBar().showMessage(f"Project: {project.metadata.title}")
        self._update_actions()

    def load_rules(self, rules: RulePackage) -> None:
        self._rules = rules
        if self._project is not None and rules.package_sha256 is not None:
            from insulation_coordination.domain.project import RulePackageReference

            reference = RulePackageReference(
                package_id=str(rules.manifest.package_id),
                version=rules.manifest.version,
                sha256=rules.package_sha256,
            )
            if self._project.required_rules != reference:
                self._project = self._project.model_copy(update={"required_rules": reference})
                self._project_page.load_project(self._project)
                self._dirty = True
        self._project_page.set_rules_package(rules)
        self._pair_page.load_rules(rules)
        self._report_page.load_rules(rules)
        self.statusBar().showMessage("Rules package loaded")
        self._update_actions()

    def _on_rules_changed(self, rules: RulePackage) -> None:
        self.load_rules(rules)

    def save_project(self, path: Path) -> None:
        if self._project is None:
            raise RuntimeError("No project loaded")
        save_project_atomic(Path(path), self._project)
        self._dirty = False
        self._project_page.mark_saved()
        self._update_actions()

    def _on_project_changed(self, project: Project) -> None:
        self._project = project
        self._dirty = True
        self.statusBar().showMessage(f"Project: {project.metadata.title} *")
        self.project_changed.emit(project)
        self._pair_page.load_project(project)
        self._report_page.load_project(project)
        self._update_actions()

    def _show_page(self, index: int) -> None:
        was_maximized = self.isMaximized()
        was_full_screen = self.isFullScreen()
        normal_geometry = self.geometry()
        self._current_page = index
        self._stack.setCurrentIndex(index)
        for name, button in self._nav_buttons.items():
            button.setChecked(name == self._PAGES[index])
        if was_maximized and not self.isMaximized():
            self.showMaximized()
        elif was_full_screen and not self.isFullScreen():
            self.showFullScreen()
        elif not was_maximized and not was_full_screen:
            self.setGeometry(normal_geometry)

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

        rules_menu = self.menuBar().addMenu("&Rules")
        self._rules_manager_action = QAction("Rules &Manager…", self)
        self._rules_manager_action.triggered.connect(self._open_rules_manager)
        rules_menu.addAction(self._rules_manager_action)

        self._import_icrules_action = QAction("&Import approved .icrules…", self)
        self._import_icrules_action.triggered.connect(self._on_import_icrules)
        rules_menu.addAction(self._import_icrules_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _update_actions(self) -> None:
        has_project = self._project is not None
        self._save_action.setEnabled(has_project and self._dirty)
        self._save_as_action.setEnabled(has_project)
        self._close_action.setEnabled(has_project)

    def _open_rules_manager(self) -> None:
        from insulation_coordination.ui.rules_manager import RulesManagerWindow

        window = RulesManagerWindow()
        window.package_activated.connect(self._on_rules_changed)
        self._rules_manager_window = window
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()

    def _on_import_icrules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Approved Rules", "", "Rules Archive (*.icrules)"
        )
        if not path:
            return
        from insulation_coordination.domain.rules import RulePackageError
        from insulation_coordination.rules.archive import load_rule_package

        try:
            rules = load_rule_package(Path(path))
        except RulePackageError as error:
            QMessageBox.critical(self, "Import Rules", str(error))
            return
        self.load_rules(rules)
        QMessageBox.information(
            self,
            "Rules Imported",
            f"Rules package {rules.manifest.package_id} v{rules.manifest.version} loaded.",
        )

    def _on_new(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        from uuid import UUID

        from insulation_coordination.domain.project import ProjectDefaults, ProjectMetadata

        project = Project(
            id=UUID(int=0),
            metadata=ProjectMetadata(title="Untitled"),
            application_version="0.1.0",
            required_rules=None,
            defaults=ProjectDefaults(
                insulation_type=InsulationType.REINFORCED,
                field_condition=FieldCondition.INHOMOGENEOUS,
                pollution_degree=2,
                construction_type=ConstructionType.PRINTED_WIRING,
                cti_or_material_group="IIIb",
            ),
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
        self._rules = None
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
