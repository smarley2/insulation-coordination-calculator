from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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

from insulation_coordination import __version__
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
from insulation_coordination.update_check import (
    NEW_ISSUE_URL,
    REPOSITORY_URL,
    UpdateCheckError,
    UpdateStatus,
    check_for_update,
)

_STARTUP_CHECK_KEY = "updates/check_on_startup"


def _settings() -> QSettings:
    """User preferences, stored wherever Qt keeps them for this platform."""
    return QSettings("insulation-coordination-calculator", "icc")


class MainWindow(QMainWindow):
    """Main desktop shell with navigation between pages."""

    project_changed = Signal(object)
    _startup_update_ready = Signal(object)

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
        self._report_page.project_changed.connect(self._on_project_changed)
        self._stack.addWidget(self._report_page)

        self.setStatusBar(QStatusBar())
        self.statusBar().addWidget(QLabel("Ready"))

        self._startup_update_ready.connect(self._on_startup_update_ready)

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
        # Every page but the one that raised the edit: reloading the origin would
        # reset the caret in the field being typed into.
        origin = self.sender()
        for page in (self._project_page, self._pair_page, self._report_page):
            if page is not origin:
                page.load_project(project)
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

        help_menu = self.menuBar().addMenu("&Help")
        self._about_action = QAction("&About…", self)
        self._about_action.triggered.connect(self._on_about)
        help_menu.addAction(self._about_action)

        self._update_action = QAction("Check for &Updates…", self)
        self._update_action.triggered.connect(self.check_for_updates)
        help_menu.addAction(self._update_action)

        self._startup_check_action = QAction("Check for Updates at &Startup", self)
        self._startup_check_action.setCheckable(True)
        self._startup_check_action.setChecked(self.update_check_on_startup())
        self._startup_check_action.toggled.connect(self.set_update_check_on_startup)
        help_menu.addAction(self._startup_check_action)

        help_menu.addSeparator()

        self._report_issue_action = QAction("&Report a Bug or Request a Feature…", self)
        self._report_issue_action.triggered.connect(self.report_issue)
        help_menu.addAction(self._report_issue_action)

    def about_text(self) -> str:
        """Version and provenance shown by Help → About."""
        return (
            f"<b>Insulation Coordination Calculator</b><br>Version {__version__}<br><br>"
            f'Repository: <a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a><br><br>'
            "Calculates clearance and creepage requirements from an approved "
            "rules package. The rules package, not this application, carries the "
            "standard content."
        )

    def _on_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("About Insulation Coordination Calculator")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(self.about_text())
        update_button = box.addButton("Check for Updates…", QMessageBox.ButtonRole.ActionRole)
        issue_button = box.addButton("Report a Bug…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is update_button:
            self.check_for_updates()
        elif box.clickedButton() is issue_button:
            self.report_issue()

    def report_issue(self) -> None:
        """Open the GitHub new-issue form for bug reports and feature requests."""
        QDesktopServices.openUrl(QUrl(NEW_ISSUE_URL))

    @staticmethod
    def update_message(status: UpdateStatus) -> str:
        """Wording shown after an update check."""
        if status.update_available:
            return (
                f"Version {status.latest_version} is available "
                f"(this build is {status.current_version}).<br><br>"
                f'Download: <a href="{status.release_url}">{status.release_url}</a>'
            )
        return (
            f"This build ({status.current_version}) is up to date. "
            f"The newest published release is {status.latest_version}."
        )

    def check_for_updates(self) -> None:
        """Compare this build against the newest published GitHub release."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            status = check_for_update()
        except UpdateCheckError as error:
            QMessageBox.warning(self, "Check for Updates", str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._show_update_message(status)

    def _show_update_message(self, status: UpdateStatus) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Check for Updates")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(self.update_message(status))
        box.exec()

    def update_check_on_startup(self) -> bool:
        """Whether startup asks GitHub for a newer release. On by default."""
        return bool(_settings().value(_STARTUP_CHECK_KEY, True, type=bool))

    def set_update_check_on_startup(self, enabled: bool) -> None:
        _settings().setValue(_STARTUP_CHECK_KEY, enabled)

    def start_startup_update_check(self) -> None:
        """Check for a newer release without blocking the window, unless turned off."""
        if not self.update_check_on_startup():
            return
        QThreadPool.globalInstance().start(self._run_startup_update_check)

    def _run_startup_update_check(self) -> None:
        try:
            status = check_for_update()
        except UpdateCheckError:
            # ponytail: no network at startup stays silent; Help → Check for Updates explains why.
            return
        try:
            self._startup_update_ready.emit(status)
        except RuntimeError:
            pass  # Window closed while the check was still running.

    def _on_startup_update_ready(self, status: UpdateStatus) -> None:
        """Only interrupt the user when there is actually a newer release."""
        if status.update_available:
            self._show_update_message(status)

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
            application_version=__version__,
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
