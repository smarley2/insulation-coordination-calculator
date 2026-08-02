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
from insulation_coordination.ui.main_window import MainWindow


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
