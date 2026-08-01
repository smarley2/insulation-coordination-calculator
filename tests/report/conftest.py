import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import calculate_pair
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.archive import load_rule_package, write_rule_package

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.synthetic_rules import synthetic_part1_rule_package


@pytest.fixture
def report_inputs(tmp_path: Path):
    rules_path = tmp_path / "synthetic.icrules"
    write_rule_package(rules_path, synthetic_part1_rule_package())
    rules = load_rule_package(rules_path)
    high = UUID(int=1)
    low = UUID(int=2)
    pair = PairCase(
        id=UUID(int=3),
        key=f"{high}::{low}",
        net_a=high,
        net_b=low,
        voltages=PairVoltages(
            long_term_rms_v=PairVoltage.applicable(Decimal(150)),
            steady_state_peak_v=PairVoltage.applicable(Decimal(150)),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
            temporary_overvoltage_peak_v=PairVoltage.not_applicable("No temporary overvoltage."),
        ),
    )
    assert rules.package_sha256 is not None
    project = Project(
        id=UUID(int=4),
        metadata=ProjectMetadata(
            title=r"Synthetic report \input{unsafe}&",
            customer="Synthetic customer",
            document_number="SYN-001",
            revision="A",
            author="Author",
            checker="Checker",
            approver="Approver",
        ),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id=str(rules.manifest.package_id),
            version=rules.manifest.version,
            sha256=rules.package_sha256,
        ),
        defaults=ProjectDefaults(
            frequency_hz=Decimal(50),
            impulse_v=Decimal(150),
            insulation_type=InsulationType.BASIC,
            field_condition=FieldCondition.INHOMOGENEOUS,
            altitude_m=Decimal(0),
            pollution_degree=2,
            construction_type=ConstructionType.OTHER,
            cti_or_material_group="I",
            conventional_construction_assumptions=(),
        ),
        net_classes=(
            NetClass(id=high, name="HV_1", description="Synthetic high net"),
            NetClass(id=low, name="LV%2", description="Synthetic low net"),
        ),
        pairs=(pair,),
    )
    result = calculate_pair(resolve_effective_case(project.defaults, pair), rules)
    results = (result,)
    return project, results, group_results(results, ()), rules
