"""Create deterministic, synthetic files for packaged release smoke tests."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
from insulation_coordination.project.persistence import save_project_atomic
from insulation_coordination.rules.archive import (
    load_rule_package,
    write_rule_package,
)
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def build_demo_project(rules) -> Project:
    nets = tuple(
        NetClass(id=UUID(int=index + 1), name=name)
        for index, name in enumerate(("HV+", "HV-", "PE", "LV"))
    )
    pair_specs = (
        (1, 2, InsulationType.FUNCTIONAL, Decimal(50), Decimal(400), Decimal(283)),
        (1, 3, InsulationType.BASIC, Decimal(50), Decimal(400), Decimal(283)),
        (2, 3, InsulationType.REINFORCED, Decimal(50), Decimal(500), Decimal(354)),
        (1, 4, InsulationType.FUNCTIONAL, Decimal(50), Decimal(400), Decimal(283)),
        (2, 4, InsulationType.BASIC, Decimal(50), Decimal(500), Decimal(354)),
        (3, 4, InsulationType.REINFORCED, Decimal(50), Decimal(500), Decimal(354)),
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
            title="Synthetic Insulation Coordination Release Smoke Test",
            customer="Synthetic customer",
            document_number="RELEASE-SMOKE-001",
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
        net_classes=nets,
        pairs=reconcile_pairs(nets, pairs),
    )


def create_release_fixtures(destination: Path) -> tuple[Path, Path]:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rules_path = destination / "rules.icrules"
    project_path = destination / "project.icproj"
    write_rule_package(rules_path, synthetic_hf_rule_package())
    rules = load_rule_package(rules_path)
    save_project_atomic(project_path, build_demo_project(rules))
    return project_path, rules_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", default="release-smoke")
    args = parser.parse_args()
    create_release_fixtures(Path(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
