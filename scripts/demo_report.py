"""Generate a synthetic demo report with realistic voltages and configurations.

Usage:
    uv run python scripts/demo_report.py [output_dir] [--online]

Writes .tex, PDF, and compile log. Without --online, compilation requires a
warm Tectonic cache (run once with --online to populate it).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

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
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.compiler import compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model
from insulation_coordination.rules.archive import (
    load_rule_package,
    write_rule_package,
)
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def build_demo_project(rules) -> Project:
    nets = tuple(
        NetClass(id=UUID(int=i + 1), name=name) for i, name in enumerate(("HV+", "HV-", "PE", "LV"))
    )
    pair_specs = (
        # (net_a, net_b, insulation, frequency Hz, steady peak V, rms V)
        (1, 2, InsulationType.FUNCTIONAL, Decimal(50), Decimal(400), Decimal(283)),
        (1, 3, InsulationType.BASIC, Decimal(50), Decimal(400), Decimal(283)),
        (2, 3, InsulationType.REINFORCED, Decimal(50), Decimal(500), Decimal(354)),
        (1, 4, InsulationType.FUNCTIONAL, Decimal(100_000), Decimal(400), Decimal(283)),
        (2, 4, InsulationType.BASIC, Decimal(100_000), Decimal(500), Decimal(354)),
        (3, 4, InsulationType.REINFORCED, Decimal(100_000), Decimal(500), Decimal(354)),
    )
    pairs = tuple(
        PairCase(
            id=UUID(int=10 + index),
            key=f"{net_a}::{net_b}",
            net_a=UUID(int=net_a),
            net_b=UUID(int=net_b),
            voltages=PairVoltages(
                long_term_rms_v=PairVoltage.applicable(rms),
                steady_state_peak_v=PairVoltage.applicable(peak),
                recurring_peak_v=PairVoltage.not_applicable("No recurring peak in this design."),
                temporary_overvoltage_peak_v=PairVoltage.not_applicable(
                    "No temporary overvoltage expected."
                ),
            ),
            frequency_hz=OverrideValue[Decimal].override(frequency),
            insulation_type=OverrideValue[InsulationType].override(insulation),
        )
        for index, (net_a, net_b, insulation, frequency, peak, rms) in enumerate(pair_specs)
    )
    return Project(
        id=UUID(int=99),
        metadata=ProjectMetadata(
            title="Synthetic Insulation Coordination Demo",
            customer="Demo Customer",
            document_number="DEMO-2026-001",
            revision="A",
            author="ICC Demo",
            checker="ICC Demo",
            approver="ICC Demo",
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
        net_classes=nets,
        pairs=reconcile_pairs(nets, pairs),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic demo report.")
    parser.add_argument("output_dir", nargs="?", default="generated-reports")
    parser.add_argument("--online", action="store_true", help="Allow network for first compile")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rules_path = out / "synthetic.icrules"
    write_rule_package(rules_path, synthetic_hf_rule_package())
    rules = load_rule_package(rules_path)
    assert rules.package_sha256 is not None

    project = build_demo_project(rules)
    results = tuple(
        calculate_pair(resolve_effective_case(project.defaults, pair), rules)
        for pair in project.pairs
    )
    groups = group_results(results, project.group_splits)
    model = build_report_model(project, results, groups, rules)

    tex = out / "demo-report.tex"
    tex.write_text(render_latex(model), encoding="utf-8")
    pdf = out / "demo-report.pdf"

    tectonic = shutil.which("tectonic")
    if tectonic is None:
        print(f"Wrote {tex}; no tectonic on PATH, PDF skipped.", file=sys.stderr)
        return 1

    result = compile_pdf(tex, pdf, Path(tectonic))
    print(f"tex:  {tex}")
    print(f"pdf:  {result.pdf_path}")
    print(f"log:  {result.log_path}")
    if result.pdf_path is None:
        if args.online:
            print(result.stderr[-500:], file=sys.stderr)
        else:
            print(
                "PDF compile failed offline; the Tectonic cache is incomplete. "
                "Run once with --online to download the full resource bundle.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
