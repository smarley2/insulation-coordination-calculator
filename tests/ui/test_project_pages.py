from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtWidgets import QApplication

from insulation_coordination.domain.project import (
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.ui.app import create_application
from insulation_coordination.ui.main_window import MainWindow
from insulation_coordination.ui.project_pages import ProjectPage


@pytest.fixture
def qtbot_project(qtbot):
    """Provide a ProjectPage wired to a minimal project."""
    required_rules = RulePackageReference(
        package_id="iec-60664",
        version="2020.1",
        sha256="a" * 64,
    )
    project = Project(
        id=UUID(int=1),
        metadata=ProjectMetadata(title="Test Drive"),
        application_version="0.1.0",
        required_rules=required_rules,
        defaults=ProjectDefaults(),
        net_classes=(),
        pairs=(),
    )
    page = ProjectPage()
    page.load_project(project)
    qtbot.addWidget(page)
    return page


def test_adding_three_net_classes_creates_three_pairs(qtbot, qtbot_project):
    page = qtbot_project
    page.add_net_class("HV+")
    page.add_net_class("HV-")
    page.add_net_class("PE")
    assert page.project.net_class_names == ("HV+", "HV-", "PE")
    assert len(page.project.pairs) == 3


def test_rename_preserves_stable_ids_and_pairs(qtbot, qtbot_project):
    page = qtbot_project
    page.add_net_class("HV")
    page.add_net_class("LV")
    original_ids = [nc.id for nc in page.project.net_classes]
    original_pair_count = len(page.project.pairs)
    page.rename_net_class(0, "HV+")
    assert page.project.net_class_names == ("HV+", "LV")
    assert [nc.id for nc in page.project.net_classes] == original_ids
    assert len(page.project.pairs) == original_pair_count


def test_delete_net_class_removes_orphaned_pairs(qtbot, qtbot_project):
    page = qtbot_project
    page.add_net_class("HV")
    page.add_net_class("LV")
    page.add_net_class("PE")
    assert len(page.project.pairs) == 3
    page.delete_net_class(2)  # delete PE
    assert page.project.net_class_names == ("HV", "LV")
    assert len(page.project.pairs) == 1


def test_project_changed_signal_emitted(qtbot, qtbot_project):
    page = qtbot_project
    with qtbot.waitSignal(page.project_changed, timeout=1000):
        page.add_net_class("HV")


def test_dirty_state_tracking(qtbot, qtbot_project):
    page = qtbot_project
    assert not page.is_dirty
    page.add_net_class("HV")
    assert page.is_dirty
    page.mark_saved()
    assert not page.is_dirty


def test_save_and_open_round_trip(qtbot, tmp_path, qtbot_project):
    page = qtbot_project
    page.add_net_class("HV")
    page.add_net_class("LV")
    path = tmp_path / "test.icproj"
    page.save_project(path)
    assert path.exists()

    page2 = ProjectPage()
    page2.open_project(path)
    qtbot.addWidget(page2)
    assert page2.project.net_class_names == ("HV", "LV")
    assert len(page2.project.pairs) == 1


def test_save_failure_preserves_dirty_state(qtbot, qtbot_project, monkeypatch):
    page = qtbot_project
    page.add_net_class("HV")
    assert page.is_dirty

    def fail_save(path, project):
        raise OSError("disk full")

    monkeypatch.setattr("insulation_coordination.ui.project_pages.save_project_atomic", fail_save)
    with pytest.raises(OSError):
        page.save_project(Path("/nonexistent/dir/test.icproj"))
    assert page.is_dirty


def test_create_application_returns_qapplication():
    app = create_application(["test"])
    assert isinstance(app, QApplication)


def test_main_window_open_save(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    required_rules = RulePackageReference(
        package_id="iec-60664",
        version="2020.1",
        sha256="b" * 64,
    )
    project = Project(
        id=UUID(int=1),
        metadata=ProjectMetadata(title="Window Test"),
        application_version="0.1.0",
        required_rules=required_rules,
        defaults=ProjectDefaults(frequency_hz=Decimal(50000)),
        net_classes=(),
        pairs=(),
    )
    window.open_project_from_project(project)
    assert window.project is not None

    path = tmp_path / "window.icproj"
    window.save_project(path)
    assert path.exists()
