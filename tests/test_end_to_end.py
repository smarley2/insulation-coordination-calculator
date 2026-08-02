from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader

from insulation_coordination.calculation.engine import calculate_pair
from insulation_coordination.calculation.grouping import group_results
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
from insulation_coordination.project.persistence import load_project, save_project_atomic
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model
from tests.calculation.conftest import semantic_annex_g_rules, semantic_part4_rules


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
"""
    script_path = path.with_suffix(".py")
    script_path.write_text(script, encoding="utf-8")
    return sys.executable, str(script_path)


def _uuid(seed: int) -> UUID:
    return UUID(int=seed)


def test_end_to_end_desktop_report_workflow(
    tmp_path: Path,
) -> None:
    part1_rules = semantic_annex_g_rules.__wrapped__(tmp_path)
    rules = semantic_part4_rules.__wrapped__(tmp_path, part1_rules)
    assert rules.package_sha256 is not None

    net_classes = tuple(
        NetClass(id=_uuid(i + 1), name=name) for i, name in enumerate(("HV+", "HV-", "PE", "LV"))
    )
    pair_specs = (
        (1, 2, InsulationType.FUNCTIONAL, Decimal(150), Decimal(300)),
        (1, 3, InsulationType.BASIC, Decimal(300), Decimal(300)),
        (2, 3, InsulationType.REINFORCED, Decimal(500), Decimal(500)),
        (1, 4, InsulationType.FUNCTIONAL, Decimal(60000), Decimal(300)),
        (2, 4, InsulationType.BASIC, Decimal(60000), Decimal(300)),
        (3, 4, InsulationType.REINFORCED, Decimal(60000), Decimal(500)),
    )
    pairs = tuple(
        PairCase(
            id=_uuid(10 + index),
            key=f"{a}::{b}",
            net_a=_uuid(a),
            net_b=_uuid(b),
            voltages=PairVoltages(
                long_term_rms_v=PairVoltage.applicable(peak),
                steady_state_peak_v=PairVoltage.applicable(peak),
                recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
                temporary_overvoltage_peak_v=PairVoltage.not_applicable(
                    "No temporary overvoltage."
                ),
            ),
            frequency_hz=OverrideValue[Decimal].override(frequency),
            insulation_type=OverrideValue[InsulationType].override(kind),
        )
        for index, (a, b, kind, frequency, peak) in enumerate(pair_specs)
    )
    project = Project(
        id=_uuid(100),
        metadata=ProjectMetadata(
            title="End-to-End Synthetic",
            customer="Synthetic customer",
            document_number="E2E-001",
            revision="B",
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
            construction_type=ConstructionType.PRINTED_WIRING,
            cti_or_material_group="I",
        ),
        net_classes=net_classes,
        pairs=reconcile_pairs(net_classes, pairs),
    )

    project_path = tmp_path / "project.icproj"
    save_project_atomic(project_path, project)
    reloaded = load_project(project_path)
    assert reloaded.pairs == project.pairs

    results = tuple(
        calculate_pair(resolve_effective_case(reloaded.defaults, pair), rules)
        for pair in reloaded.pairs
    )
    assert len(results) == 6
    assert any(result.trace.used_part4 for result in results)
    groups = group_results(results, reloaded.group_splits)
    model = build_report_model(reloaded, results, groups, rules)
    tex = render_latex(model)

    assert "E2E-001" in tex
    assert "SYNTHETIC-PART-1 (1)" in tex
    assert "iec60664-4-equation-1-critical-frequency" in {
        semantic_id for result in results for semantic_id in result.trace.semantic_rule_ids
    }
    assert "HV+ ↔ LV" in tex
    assert "Authoritative Pair Matrix" not in tex
    assert "Pair ID" not in tex
    assert "Approval Records" not in tex

    tectonic = _fake_tectonic(tmp_path / "fake-tectonic")
    from insulation_coordination.report.compiler import compile_pdf

    output = tmp_path / "report.pdf"
    tex_path = tmp_path / "report.tex"
    tex_path.write_text(tex, encoding="utf-8")
    compiled = compile_pdf(tex_path, output, tectonic)
    assert compiled.success is True
    assert compiled.pdf_path is not None
    assert len(PdfReader(compiled.pdf_path).pages) == 1
    assert compiled.pdf_path.exists()
    assert compiled.log_path.exists()
