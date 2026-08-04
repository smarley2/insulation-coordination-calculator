from __future__ import annotations

from uuid import UUID

import pytest
from PySide6.QtWidgets import QApplication

from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.project.pairs import reconcile_pairs
from insulation_coordination.rules.archive import write_rule_package
from insulation_coordination.rules.installation import InstalledRulePackage
from insulation_coordination.ui.main_window import MainWindow
from tests.fixtures.synthetic_rules import synthetic_rule_package


def _project() -> Project:
    net_classes = (
        NetClass(id=UUID(int=1), name="HV+"),
        NetClass(id=UUID(int=2), name="HV-"),
    )
    return Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Geometry test"),
        application_version="test",
        defaults=ProjectDefaults(),
        net_classes=net_classes,
        pairs=reconcile_pairs(net_classes, ()),
    )


def test_project_load_pairs_navigation_preserves_maximized_geometry(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.showMaximized()
    QApplication.processEvents()
    before = window.frameGeometry()

    window.open_project_from_project(_project())
    window._show_page(1)
    QApplication.processEvents()
    window._show_page(0)
    QApplication.processEvents()
    window._show_page(1)
    QApplication.processEvents()

    assert window.isMaximized()
    assert window.frameGeometry() == before


def test_open_document_loads_project(qtbot, tmp_path) -> None:
    from insulation_coordination.project.persistence import save_project_atomic

    path = tmp_path / "design.icproj"
    save_project_atomic(path, _project())
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.open_document(path) is True
    assert window.project is not None
    assert window.project.id == _project().id
    assert window.project.metadata.title == "Geometry test"


def test_open_document_installs_and_loads_rules(qtbot, tmp_path, monkeypatch) -> None:
    from insulation_coordination.ui import main_window as main_window_module

    source = tmp_path / "rules.icrules"
    package = synthetic_rule_package()
    write_rule_package(source, package)
    installed = InstalledRulePackage(tmp_path / "installed.icrules", package)
    monkeypatch.setattr(main_window_module, "install_rule_package", lambda path: installed)
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.open_document(source) is True
    assert window.rules == package


def test_help_menu_offers_about_with_version_and_repository(qtbot) -> None:
    from insulation_coordination import __version__
    from insulation_coordination.ui.main_window import REPOSITORY_URL

    window = MainWindow()
    qtbot.addWidget(window)

    menus = [action.text() for action in window.menuBar().actions()]
    assert "&Help" in menus
    assert window._about_action.text() == "&About…"
    assert __version__ in window.about_text()
    assert REPOSITORY_URL in window.about_text()


def test_new_project_records_the_application_version(qtbot) -> None:
    from insulation_coordination import __version__

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.project is not None
    assert window.project.application_version == __version__


def test_help_menu_offers_an_update_check(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window._update_action.text() == "Check for &Updates…"


def test_update_message_reports_a_newer_release(qtbot) -> None:
    from insulation_coordination.update_check import UpdateStatus

    window = MainWindow()
    qtbot.addWidget(window)
    message = window.update_message(
        UpdateStatus(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://github.com/smarley2/insulation-coordination-calculator/releases",
            update_available=True,
        )
    )
    assert "0.2.0 is available" in message
    assert "releases" in message


def test_update_message_reports_up_to_date(qtbot) -> None:
    from insulation_coordination.update_check import UpdateStatus

    window = MainWindow()
    qtbot.addWidget(window)
    message = window.update_message(
        UpdateStatus(
            current_version="0.1.0",
            latest_version="0.1.0",
            release_url="https://github.com/smarley2/insulation-coordination-calculator/releases",
            update_available=False,
        )
    )
    assert "up to date" in message


def test_failed_update_check_warns_without_raising(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from insulation_coordination.ui import main_window as main_window_module

    window = MainWindow()
    qtbot.addWidget(window)
    captured: list[str] = []

    def fail() -> None:
        raise main_window_module.UpdateCheckError("offline")

    monkeypatch.setattr(main_window_module, "check_for_update", fail)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda _parent, _title, message: captured.append(message)),
    )

    window.check_for_updates()

    assert captured == ["offline"]


def _file_settings(monkeypatch, tmp_path):
    """Keep preference reads and writes out of the real user settings store."""
    from PySide6.QtCore import QSettings

    from insulation_coordination.ui import main_window as main_window_module

    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        main_window_module,
        "_settings",
        lambda: QSettings(path, QSettings.Format.IniFormat),
    )


def test_help_menu_offers_a_bug_report_link(qtbot, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices

    from insulation_coordination.update_check import NEW_ISSUE_URL, REPOSITORY_URL

    window = MainWindow()
    qtbot.addWidget(window)
    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()))
    )

    window._report_issue_action.trigger()

    assert window._report_issue_action.text() == "&Report a Bug or Request a Feature…"
    assert opened == [NEW_ISSUE_URL]
    assert NEW_ISSUE_URL == f"{REPOSITORY_URL}/issues/new/choose"


def test_startup_update_check_is_on_by_default_and_can_be_turned_off(
    qtbot, monkeypatch, tmp_path
) -> None:
    _file_settings(monkeypatch, tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.update_check_on_startup() is True

    window.set_update_check_on_startup(False)

    assert window.update_check_on_startup() is False


def test_startup_update_check_is_skipped_when_turned_off(qtbot, monkeypatch, tmp_path) -> None:
    from insulation_coordination.ui import main_window as main_window_module

    _file_settings(monkeypatch, tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_update_check_on_startup(False)
    monkeypatch.setattr(
        main_window_module, "check_for_update", lambda: pytest.fail("network was contacted")
    )

    window.start_startup_update_check()


def test_startup_update_check_stays_silent_without_internet(qtbot, monkeypatch) -> None:
    from insulation_coordination.ui import main_window as main_window_module

    window = MainWindow()
    qtbot.addWidget(window)
    shown: list[object] = []

    def fail() -> None:
        raise main_window_module.UpdateCheckError("Could not reach GitHub: no route to host")

    monkeypatch.setattr(main_window_module, "check_for_update", fail)
    monkeypatch.setattr(window, "_show_update_message", shown.append)

    window._run_startup_update_check()

    assert shown == []


def _status(update_available: bool, latest: str = "0.2.0"):
    from insulation_coordination.update_check import UpdateStatus

    return UpdateStatus(
        current_version="0.1.0",
        latest_version=latest if update_available else "0.1.0",
        release_url="https://github.com/smarley2/insulation-coordination-calculator/releases",
        update_available=update_available,
    )


def test_startup_update_check_reports_only_a_newer_release(qtbot, monkeypatch) -> None:
    from insulation_coordination.ui import main_window as main_window_module

    window = MainWindow()
    qtbot.addWidget(window)
    shown: list[object] = []
    monkeypatch.setattr(window, "_show_update_message", lambda status, **_: shown.append(status))

    monkeypatch.setattr(main_window_module, "check_for_update", lambda: _status(False))
    window._run_startup_update_check()
    assert shown == []

    newer = _status(True)
    monkeypatch.setattr(main_window_module, "check_for_update", lambda: newer)
    window._run_startup_update_check()
    assert shown == [newer]


def test_skipped_version_is_not_announced_again_at_startup(qtbot, monkeypatch, tmp_path) -> None:
    _file_settings(monkeypatch, tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    shown: list[object] = []
    monkeypatch.setattr(window, "_show_update_message", lambda status, **_: shown.append(status))
    assert window.skipped_version() == ""

    window.set_skipped_version("0.2.0")
    window._on_startup_update_ready(_status(True, latest="0.2.0"))
    assert shown == []

    # A release after the skipped one still gets announced.
    later = _status(True, latest="0.3.0")
    window._on_startup_update_ready(later)
    assert shown == [later]


def test_manual_update_check_ignores_a_skipped_version(qtbot, monkeypatch, tmp_path) -> None:
    from insulation_coordination.ui import main_window as main_window_module

    _file_settings(monkeypatch, tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_skipped_version("0.2.0")
    shown: list[object] = []
    monkeypatch.setattr(window, "_show_update_message", lambda status, **_: shown.append(status))
    skipped = _status(True, latest="0.2.0")
    monkeypatch.setattr(main_window_module, "check_for_update", lambda: skipped)

    window.check_for_updates()

    assert shown == [skipped]


def _project_with_metadata() -> Project:
    base = _project()
    return base.model_copy(
        update={
            "metadata": base.metadata.model_copy(
                update={"document_number": "DOC-1", "revision": "01"}
            )
        }
    )


def test_report_metadata_edit_reaches_the_project_page(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project_from_project(_project_with_metadata())

    window._report_page._document_number_edit.setText("DOC-2")
    window._report_page._revision_edit.setText("02")

    assert window.project is not None
    assert window.project.metadata.document_number == "DOC-2"
    assert window.project.metadata.revision == "02"
    assert window._project_page._doc_edit.text() == "DOC-2"
    assert window._project_page._revision_edit.text() == "02"
    assert window.is_dirty is True


def test_project_metadata_edit_reaches_the_report_page(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project_from_project(_project_with_metadata())

    window._project_page._doc_edit.setText("DOC-9")
    window._project_page._revision_edit.setText("07")

    assert window._report_page._document_number_edit.text() == "DOC-9"
    assert window._report_page._revision_edit.text() == "07"
    assert window.project is not None
    assert window.project.metadata.document_number == "DOC-9"


def test_report_metadata_edit_keeps_the_caret_in_place(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project_from_project(_project_with_metadata())
    edit = window._report_page._document_number_edit

    edit.setCursorPosition(0)
    qtbot.keyClicks(edit, "X")

    assert edit.text() == "XDOC-1"
    assert edit.cursorPosition() == 1
