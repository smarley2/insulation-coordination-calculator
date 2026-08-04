from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import calculate_pair
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
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.synthetic_rules import synthetic_part1_rule_package


@pytest.fixture
def project() -> Project:
    nets = tuple(NetClass(id=UUID(int=i + 1), name=n) for i, n in enumerate(("HV+", "HV-")))
    pair = PairCase(
        id=UUID(int=10),
        key="0",
        net_a=UUID(int=1),
        net_b=UUID(int=2),
        voltages=PairVoltages(
            long_term_rms_v=PairVoltage.applicable(Decimal(500)),
            steady_state_peak_v=PairVoltage.applicable(Decimal(500)),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
            temporary_overvoltage_peak_v=PairVoltage.not_applicable("No temporary overvoltage."),
        ),
        insulation_type=OverrideValue[InsulationType].override(InsulationType.BASIC),
    )
    pairs = reconcile_pairs(nets, (pair,))
    for index, p in enumerate(pairs):
        if p.net_a == pair.net_a and p.net_b == pair.net_b:
            pair = p.model_copy(update={"id": UUID(int=10)})
            pairs = (pair,)
            break
    return Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Review"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="iec-60664", version="2020.1", sha256="a" * 64
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
        pairs=pairs,
    )


@pytest.fixture
def rules(tmp_path: Path):
    path = tmp_path / "synthetic.icrules"
    write_rule_package(path, synthetic_part1_rule_package())
    return load_rule_package(path)


def test_review_shows_candidates_traces_warnings(qtbot, project, rules) -> None:
    from insulation_coordination.ui.calculation_review import CalculationReviewPage

    result = calculate_pair(resolve_effective_case(project.defaults, project.pairs[0]), rules)
    page = CalculationReviewPage()
    qtbot.addWidget(page)
    page.update_results((result,), project)

    item = page._results_list.item(0)
    assert item is not None
    detail = item.toolTip()
    assert "Final clearance" in detail
    assert "Clearance candidates" in detail
    assert "Creepage candidates" in detail
    assert "Trace steps" in detail
    assert result.trace.governing_clearance_candidate_id in detail
    assert page.groups


def test_review_reports_inner_layer_distances_per_pair(qtbot, project, rules) -> None:
    from insulation_coordination.ui.calculation_review import CalculationReviewPage

    result = calculate_pair(resolve_effective_case(project.defaults, project.pairs[0]), rules)
    page = CalculationReviewPage()
    qtbot.addWidget(page)
    page.update_results((result,), project)

    item = page._results_list.item(0)
    assert item is not None
    assert f"inner clearance={result.inner_clearance_mm} mm" in item.text()
    assert f"inner creepage={result.inner_creepage_mm} mm" in item.text()
    assert (
        f"Inner-layer clearance (pollution degree 1): {result.inner_clearance_mm} mm"
        in item.toolTip()
    )
    assert (
        f"Inner-layer creepage (pollution degree 1): {result.inner_creepage_mm} mm"
        in item.toolTip()
    )


def test_invalid_change_clears_stale_results(qtbot, project, rules) -> None:
    from insulation_coordination.ui.calculation_review import CalculationReviewPage

    result = calculate_pair(resolve_effective_case(project.defaults, project.pairs[0]), rules)
    page = CalculationReviewPage()
    qtbot.addWidget(page)
    page.update_results((result,), project)
    assert page._results_list.count() == 1
    # clear without rules -> no stale results
    page.recalculate_after_change(project)
    assert page._results_list.count() == 0
