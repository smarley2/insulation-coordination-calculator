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
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.ui.report_page import ReportPage
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
