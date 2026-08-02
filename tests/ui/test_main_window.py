from __future__ import annotations

from uuid import UUID

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
