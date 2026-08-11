from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    NetClass,
    OverrideValue,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.pairs import reconcile_pairs
from insulation_coordination.project.persistence import load_project
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.ui.project_pages import ProjectPage
from insulation_coordination.ui.report_page import ReportPage
from tests.fixtures.images import png_bytes
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def _fake_tectonic(path: Path) -> tuple[str, str]:
    script = """from pathlib import Path
import sys
from pypdf import PdfWriter

outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
tex = Path(sys.argv[-1])
writer = PdfWriter()
writer.add_blank_page(width=612, height=792)
with (outdir / (tex.stem + ".pdf")).open("wb") as stream:
    writer.write(stream)
print("|".join(sys.argv[1:]))
"""
    script_path = path.with_suffix(".py")
    script_path.write_text(script, encoding="utf-8")
    return sys.executable, str(script_path)


@pytest.fixture
def complete_workspace(tmp_path: Path):
    rules_path = tmp_path / "synthetic.icrules"
    write_rule_package(rules_path, synthetic_hf_rule_package())
    rules = load_rule_package(rules_path)
    assert rules.package_sha256 is not None
    pairs = tuple(
        PairCase(
            id=__import__("uuid").UUID(int=10 + index),
            key=f"{net_a}::{net_b}",
            net_a=__import__("uuid").UUID(int=net_a),
            net_b=__import__("uuid").UUID(int=net_b),
            voltages=PairVoltages(
                long_term_rms_v=PairVoltage.applicable(rms),
                steady_state_peak_v=PairVoltage.applicable(peak),
                recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
                temporary_overvoltage_peak_v=PairVoltage.not_applicable(
                    "No temporary overvoltage."
                ),
            ),
            insulation_type=OverrideValue[InsulationType].override(kind),
        )
        for index, (net_a, net_b, kind, rms, peak) in enumerate(
            (
                (1, 2, InsulationType.BASIC, Decimal(500), Decimal(500)),
                (1, 3, InsulationType.BASIC, Decimal(500), Decimal(500)),
                (2, 3, InsulationType.BASIC, Decimal(500), Decimal(500)),
            )
        )
    )
    net_classes = (
        NetClass(id=__import__("uuid").UUID(int=1), name="HV+"),
        NetClass(id=__import__("uuid").UUID(int=2), name="HV-"),
        NetClass(id=__import__("uuid").UUID(int=3), name="PE"),
    )
    pairs = reconcile_pairs(net_classes, pairs)
    project = Project(
        id=__import__("uuid").UUID(int=9),
        metadata=ProjectMetadata(
            title="E2E Report",
            customer="Synthetic customer",
            document_number="SYN-001",
            revision="A",
        ),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id=str(rules.manifest.package_id),
            version=rules.manifest.version,
            sha256=rules.package_sha256,
        ),
        defaults=ProjectDefaults(
            frequency_hz=Decimal(50),
            impulse_v=Decimal(1000),
            insulation_type=InsulationType.BASIC,
            field_condition=FieldCondition.INHOMOGENEOUS,
            altitude_m=Decimal(0),
            pollution_degree=2,
            construction_type=ConstructionType.OTHER,
            cti_or_material_group="I",
        ),
        net_classes=net_classes,
        pairs=pairs,
    )
    report_page = ReportPage(tectonic=_fake_tectonic(tmp_path / "fake-tectonic"))
    report_page.load_project(project)
    report_page.load_rules(rules)
    return _Workspace(report_page, project, rules, tmp_path)


class _Workspace:
    def __init__(self, report_page: ReportPage, project, rules, tmp_path: Path) -> None:
        self.report_page = report_page
        self.project = project
        self.rules = rules
        self.tmp_path = tmp_path


def test_report_is_blocked_when_any_pair_is_incomplete(qtbot) -> None:
    page = ReportPage()
    qtbot.addWidget(page)
    assert page.generate_enabled is False


def test_complete_project_generates_tex_and_pdf(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    assert page.generate_enabled is True
    result = page.generate(complete_workspace.tmp_path)
    assert result.tex_path.exists()
    assert result.pdf_path.exists()
    tex = result.tex_path.read_text(encoding="utf-8")
    assert "SYNTHETIC-PART-1 (1)" in tex
    assert len(PdfReader(result.pdf_path).pages) == 1
    assert "SYN-001" in tex


def test_blocked_when_one_pair_missing_stress(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    pair = complete_workspace.project.pairs[0]
    blank = pair.model_copy(
        update={
            "voltages": pair.voltages.model_copy(update={"long_term_rms_v": PairVoltage.blank()})
        }
    )
    project = complete_workspace.project.model_copy(
        update={"pairs": (blank, *complete_workspace.project.pairs[1:])}
    )
    page.load_project(project)
    assert page.generate_enabled is False
    assert "long_term_rms_v is blank" in page.blocking_summary


def test_groups_and_validation_summary_visible(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    assert page.group_count >= 1
    assert page.validation_summary == "All pairs calculated"


def test_attached_diagram_survives_moving_the_project_and_losing_the_original(
    qtbot, complete_workspace
) -> None:
    """Attach, save, delete the source image, reopen elsewhere, still report it."""
    workspace = complete_workspace
    project_page = ProjectPage()
    qtbot.addWidget(project_page)
    project_page.load_project(workspace.project)
    source_image = workspace.tmp_path / "topology.png"
    source_image.write_bytes(png_bytes(40, 20))
    project_page._diagram_box.attach_path(source_image)
    saved = workspace.tmp_path / "portable.icproj"
    project_page.save_project(saved)

    source_image.unlink()
    moved = workspace.tmp_path / "elsewhere" / "portable.icproj"
    moved.parent.mkdir()
    moved.write_bytes(saved.read_bytes())
    saved.unlink()
    reopened = ProjectPage()
    qtbot.addWidget(reopened)
    reopened.open_project(moved)

    page = workspace.report_page
    qtbot.addWidget(page)
    page.load_project(reopened.project)
    destination = workspace.tmp_path / "portable-report"
    result = page.generate(destination)

    attachment = reopened.project.circuit_diagram
    assert attachment is not None
    staged = destination / attachment.staged_filename
    assert staged.read_bytes() == attachment.decoded_bytes()
    tex = result.tex_path.read_text(encoding="utf-8")
    assert f"{{{attachment.staged_filename}}}" in tex
    assert "topology.png" not in tex
    assert str(workspace.tmp_path) not in tex
    assert result.pdf_path is not None


def test_removing_the_diagram_leaves_the_report_unchanged(qtbot, complete_workspace) -> None:
    workspace = complete_workspace
    project_page = ProjectPage()
    qtbot.addWidget(project_page)
    project_page.load_project(workspace.project)
    page = workspace.report_page
    qtbot.addWidget(page)
    without = page.generate(workspace.tmp_path / "without").tex_path.read_text(encoding="utf-8")

    image = workspace.tmp_path / "topology.png"
    image.write_bytes(png_bytes(40, 20))
    project_page._diagram_box.attach_path(image)
    project_page._diagram_box.remove()
    saved = workspace.tmp_path / "removed.icproj"
    project_page.save_project(saved)
    page.load_project(load_project(saved))
    again = page.generate(workspace.tmp_path / "again").tex_path.read_text(encoding="utf-8")

    assert load_project(saved).circuit_diagram is None
    assert "Circuit Diagram" not in again
    assert again == without


def test_export_writes_tex_and_pdf_with_log(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    result = page.export(complete_workspace.tmp_path / "report-export")
    assert result.tex_path.exists()
    assert result.pdf_path.exists()
    assert result.log_path.exists()


def test_split_group_persists_split(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    before = page.group_count
    page.split_selected_group()
    assert page.group_count >= before + 1
    assert page._project is not None and page._project.group_splits
    assert page._split_button.isEnabled() is True


def test_groups_are_listed_with_human_labels(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    assert page.group_count >= 1
    labels = [page._groups_list.item(row).text() for row in range(page._groups_list.count())]
    assert labels
    assert all(label.startswith("Group ") for label in labels)
    assert any("↔" in label for label in labels)
    for group in page._groups:
        assert group.group_id[:8] not in " ".join(labels)


def test_blocking_summary_names_the_pair_not_its_uuid(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    pair = complete_workspace.project.pairs[0]
    blank = pair.model_copy(
        update={
            "voltages": pair.voltages.model_copy(update={"long_term_rms_v": PairVoltage.blank()})
        }
    )
    page.load_project(
        complete_workspace.project.model_copy(
            update={"pairs": (blank, *complete_workspace.project.pairs[1:])}
        )
    )
    assert str(pair.id) not in page.blocking_summary
    assert "↔" in page.blocking_summary


def test_groups_list_height_follows_the_row_count(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    assert page.group_count >= 1
    rows = page._groups_list.count()
    row_height = page._groups_list.sizeHintForRow(0)
    assert page._groups_list.maximumHeight() <= rows * row_height + 16


def test_selected_earlier_revision_generates_a_difference_only_pdf(
    qtbot, complete_workspace
) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    destination = complete_workspace.tmp_path / "revisions"

    first = page.generate(destination)
    assert first.diff_pdf_path is None
    archived = complete_workspace.tmp_path / "revision-A.tex"
    archived.write_text(first.tex_path.read_text(encoding="utf-8"), encoding="utf-8")

    revised = complete_workspace.project.model_copy(
        update={
            "metadata": complete_workspace.project.metadata.model_copy(update={"revision": "B"})
        }
    )
    page.load_project(revised)
    second = page.generate(destination, archived)

    assert second.diff_pdf_path is not None
    assert second.diff_pdf_path.exists()
    assert second.diff_pdf_path.name == "icc-report-SYN-001-diff-revA-revB.pdf"
    diff_tex = second.diff_pdf_path.with_suffix(".tex").read_text(encoding="utf-8")
    assert "revision A to revision B" in diff_tex


def test_baseline_may_be_the_file_that_is_overwritten(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    destination = complete_workspace.tmp_path / "in-place"
    first = page.generate(destination)

    revised = complete_workspace.project.model_copy(
        update={
            "metadata": complete_workspace.project.metadata.model_copy(update={"revision": "C"})
        }
    )
    page.load_project(revised)
    second = page.generate(destination, first.tex_path)

    assert second.diff_pdf_path is not None
    assert "revision A to revision C" in second.diff_pdf_path.with_suffix(".tex").read_text(
        encoding="utf-8"
    )


def test_regenerating_without_a_baseline_produces_no_diff(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    destination = complete_workspace.tmp_path / "no-baseline"
    page.generate(destination)
    assert page.generate(destination).diff_pdf_path is None


def test_unreadable_baseline_is_reported(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    with pytest.raises(RuntimeError, match="earlier revision"):
        page.generate(complete_workspace.tmp_path / "missing", Path("does-not-exist.tex"))


def test_load_project_defers_calculation_until_shown(
    qtbot, monkeypatch, complete_workspace
) -> None:
    from insulation_coordination.ui import report_page as report_page_module

    calls = 0
    real = report_page_module.calculate_pair

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(report_page_module, "calculate_pair", counting)

    page = ReportPage()
    qtbot.addWidget(page)
    calls = 0
    page.load_project(complete_workspace.project)
    page.load_rules(complete_workspace.rules)
    assert calls == 0

    page.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert calls > 0


def test_generate_forces_calculation_when_never_shown(
    qtbot, monkeypatch, complete_workspace
) -> None:
    from insulation_coordination.ui import report_page as report_page_module

    calls = 0
    real = report_page_module.calculate_pair

    def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(report_page_module, "calculate_pair", counting)

    tectonic = _fake_tectonic(complete_workspace.tmp_path / "lazy-generate-tectonic")
    page = ReportPage(tectonic=tectonic)
    qtbot.addWidget(page)
    calls = 0
    page.load_project(complete_workspace.project)
    page.load_rules(complete_workspace.rules)
    assert calls == 0

    result = page.generate(complete_workspace.tmp_path / "lazy-generate")
    assert calls > 0
    assert result.tex_path.exists()


def test_generate_button_sits_above_the_validation_summary(qtbot, complete_workspace) -> None:
    page = complete_workspace.report_page
    qtbot.addWidget(page)
    page.resize(900, 700)
    page.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    button_bottom = page._generate_button.mapTo(page, page._generate_button.rect().bottomLeft()).y()
    summary_top = page._summary_label.mapTo(page, page._summary_label.rect().topLeft()).y()
    assert button_bottom <= summary_top
