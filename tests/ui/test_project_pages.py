from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog

from insulation_coordination.domain.project import (
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.ui.app import create_application
from insulation_coordination.ui.main_window import MainWindow
from insulation_coordination.ui.project_pages import ProjectPage
from tests.fixtures.synthetic_rules import synthetic_rule_package


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


def test_project_default_dropdown_choices(qtbot, qtbot_project):
    page = qtbot_project
    assert [page._impulse_combo.itemText(i) for i in range(page._impulse_combo.count())] == [
        "",
        "0.33 kV",
        "0.40 kV",
        "0.50 kV",
        "0.60 kV",
        "0.80 kV",
        "1.0 kV",
        "1.2 kV",
        "1.5 kV",
        "2.0 kV",
        "2.5 kV",
        "3.0 kV",
        "4.0 kV",
        "5.0 kV",
        "6.0 kV",
        "8.0 kV",
        "10 kV",
        "12 kV",
        "15 kV",
        "20 kV",
        "25 kV",
        "30 kV",
        "40 kV",
        "50 kV",
        "60 kV",
        "80 kV",
        "100 kV",
    ]
    assert [page._pollution_combo.itemText(i) for i in range(page._pollution_combo.count())] == [
        "",
        "1",
        "2",
    ]
    assert [page._cti_combo.itemText(i) for i in range(page._cti_combo.count())] == [
        "",
        "I",
        "II",
        "IIIa",
        "IIIb",
    ]


def test_project_default_dropdowns_update_existing_model(qtbot, qtbot_project):
    page = qtbot_project
    page._impulse_combo.setCurrentText("2.5 kV")
    page._pollution_combo.setCurrentText("2")
    page._cti_combo.setCurrentText("IIIa")
    assert page.project.defaults.impulse_v == Decimal(2500)
    assert page.project.defaults.pollution_degree == 2
    assert page.project.defaults.cti_or_material_group == "IIIa"
    page._impulse_combo.setCurrentIndex(0)
    page._pollution_combo.setCurrentIndex(0)
    page._cti_combo.setCurrentIndex(0)
    assert page.project.defaults.impulse_v is None
    assert page.project.defaults.pollution_degree is None
    assert page.project.defaults.cti_or_material_group is None


def test_add_button_adds_net_class_through_dialog(qtbot, qtbot_project):
    page = qtbot_project

    def accept_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        dialog.setTextValue("HV+")
        dialog.accept()

    QTimer.singleShot(0, accept_dialog)
    qtbot.mouseClick(page._add_button, Qt.MouseButton.LeftButton)
    assert page.project.net_class_names == ("HV+",)
    assert page._net_list.count() == 1


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


def test_main_window_starts_with_new_project(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.project is not None
    assert window.project.metadata.title == "Untitled"
    window._project_page.add_net_class("HV")
    assert window.project.net_class_names == ("HV",)


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


def test_main_window_rules_label_and_add_flow(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    project = Project(
        id=UUID(int=1),
        metadata=ProjectMetadata(title="Window Test"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="project-required", version="2020.1", sha256="b" * 64
        ),
        defaults=ProjectDefaults(),
        net_classes=(),
        pairs=(),
    )
    window.open_project_from_project(project)
    rules = synthetic_rule_package()
    window.load_rules(rules)
    assert window._project_page._rules_label.text().startswith(
        f"{rules.manifest.package_id} v{rules.manifest.version}"
    )

    def accept_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("HVP")
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(0, accept_dialog)
    qtbot.mouseClick(window._project_page._add_button, Qt.MouseButton.LeftButton)
    assert window.project is not None
    assert window.project.net_class_names == ("HVP",)
    assert window._project_page._net_list.count() == 1


def test_main_window_reports_unsupported_pdf_without_crashing(qtbot, monkeypatch) -> None:
    from insulation_coordination.rules.importer.identify import UnsupportedStandardError

    window = MainWindow()
    qtbot.addWidget(window)
    messages: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "insulation_coordination.ui.main_window.QFileDialog.getOpenFileNames",
        lambda *_args, **_kwargs: (["unsupported.pdf"], "PDF files (*.pdf)"),
    )

    def reject(_paths):
        raise UnsupportedStandardError("PDF is not a recognized supported IEC edition")

    monkeypatch.setattr(
        "insulation_coordination.rules.importer.extract.extract_draft",
        reject,
    )
    monkeypatch.setattr(
        "insulation_coordination.ui.main_window.QMessageBox.critical",
        lambda _parent, title, message: messages.append((title, message)),
    )

    window._on_extract_pdf()

    assert messages == [("Extract Draft", "PDF is not a recognized supported IEC edition")]
