from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import CalculationError, calculate_pair
from insulation_coordination.calculation.high_frequency import (
    HighFrequencyCalculationError,
    calculate_high_frequency_candidates,
    iterate_field_clearance,
)
from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    PairVoltage,
    PairVoltages,
)
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def _seal_rules(rules: RulePackage, path: Path) -> RulePackage:
    write_rule_package(path, rules.model_copy(update={"checksums": {}, "package_sha256": None}))
    return load_rule_package(path)


@pytest.fixture
def synthetic_hf_rules(tmp_path: Path) -> RulePackage:
    return _seal_rules(synthetic_hf_rule_package(), tmp_path / "synthetic-hf.icrules")


@pytest.fixture
def case_factory():
    def make(
        *,
        kind: InsulationType = InsulationType.BASIC,
        frequency_hz: str = "30000",
        field_condition: FieldCondition = FieldCondition.INHOMOGENEOUS,
        electrode_radius_mm: str | None = None,
        altitude_m: str = "0",
    ) -> EffectiveCase:
        return EffectiveCase(
            id=UUID(int=7),
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            voltages=PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(500)),
                steady_state_peak_v=PairVoltage.applicable(Decimal(300)),
                recurring_peak_v=PairVoltage.applicable(Decimal(400)),
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(600)),
            ),
            frequency_hz=EffectiveValue(
                value=Decimal(frequency_hz),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            impulse_v=EffectiveValue(
                value=Decimal(1000),
                provenance=Provenance.PAIR_OVERRIDE,
            ),
            insulation_type=EffectiveValue(
                value=kind,
                provenance=Provenance.PAIR_OVERRIDE,
            ),
            field_condition=EffectiveValue(
                value=field_condition,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            electrode_radius_mm=EffectiveValue(
                value=(None if electrode_radius_mm is None else Decimal(electrode_radius_mm)),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            altitude_m=EffectiveValue(
                value=Decimal(altitude_m),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            pollution_degree=EffectiveValue(
                value=2,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            construction_type=EffectiveValue(
                value=ConstructionType.OTHER,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            cti_or_material_group=EffectiveValue(
                value="I",
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            conventional_construction_assumptions=EffectiveValue(
                value=(),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
        )

    return make


def test_part4_starts_only_above_30_khz(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    at_boundary = calculate_pair(case_factory(frequency_hz="30000"), synthetic_hf_rules)
    above = calculate_pair(case_factory(frequency_hz="30000.1"), synthetic_hf_rules)

    assert at_boundary.trace.used_part4 is False
    assert above.trace.used_part4 is True


def test_functional_hf_requires_explicit_approved_applicability_mapping(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    missing = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "mappings": tuple(
                    mapping
                    for mapping in synthetic_hf_rules.mappings
                    if mapping.id != "functional_hf_applicability"
                )
            }
        ),
        tmp_path / "missing-functional-applicability.icrules",
    )

    with pytest.raises(CalculationError) as caught:
        calculate_pair(
            case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="100000"),
            missing,
        )

    assert getattr(caught.value, "code", None) == "FUNCTIONAL_HF_MAPPING_MISSING"


def test_accepted_functional_hf_mapping_is_retained_in_trace(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="100000"),
        synthetic_hf_rules,
    )
    step = next(
        step
        for step in result.trace.steps
        if step.semantic_rule_id
        == ("iec60664-4:functional_applicability:stress=periodic_peak_v:frequency=frequency_hz")
    )

    assert "functional_hf_applicability" in step.reason
    assert step.source_reference is not None
    assert step.source_reference.standard == "SYNTHETIC-PART-4"


def test_inhomogeneous_route_uses_maximum_periodic_peak_and_frequency_mapping(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(case_factory(frequency_hz="100000"), synthetic_hf_rules)
    candidate = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == "part4_periodic_clearance"
    )

    assert candidate.stress.value == Decimal(600)
    assert candidate.stress.unit == "V"
    assert candidate.stress_field == "periodic_peak_v"
    assert candidate.mapping_id == "basic_hf_clearance_inhomogeneous"
    assert candidate.formula_id == "synthetic-hf-inhomogeneous-clearance"
    assert "field=inhomogeneous" in candidate.semantic_rule_id
    assert any(
        quantity.value == Decimal(100000) and quantity.unit == "Hz"
        for step in candidate.steps
        for quantity in step.inputs
    )
    assert result.trace.governing_clearance_candidate_id == candidate.candidate_id
    assert result.clearance_mm == Decimal(12)


def test_public_hf_candidate_api_is_empty_at_boundary_and_retains_part4_creepage(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    boundary_case = case_factory(frequency_hz="30000")
    boundary = calculate_pair(boundary_case, synthetic_hf_rules)
    base = next(
        candidate
        for candidate in boundary.trace.clearance_candidates
        if candidate.candidate_id == boundary.trace.governing_clearance_candidate_id
    )

    assert (
        calculate_high_frequency_candidates(
            boundary_case,
            base,
            synthetic_hf_rules,
        ).clearance_candidates
        == ()
    )

    high_frequency = calculate_high_frequency_candidates(
        case_factory(frequency_hz="100000"),
        base,
        synthetic_hf_rules,
    )
    assert high_frequency.creepage_candidates[0].candidate_id == "part4_deterioration"
    assert high_frequency.creepage_candidates[0].mapping_id == "basic_hf_creepage"
    assert high_frequency.creepage_candidates[0].distance_mm == Decimal(6)


def test_homogeneous_field_requires_geometry(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(
                frequency_hz="100000",
                field_condition=FieldCondition.HOMOGENEOUS,
            ),
            synthetic_hf_rules,
        )

    assert caught.value.code == "HF_GEOMETRY_REQUIRED"


def test_homogeneous_field_iteration_is_bounded_decimal_and_fully_recorded(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    effective = case_factory(
        frequency_hz="100000",
        field_condition=FieldCondition.HOMOGENEOUS,
        electrode_radius_mm="10",
    )
    boundary = calculate_pair(case_factory(frequency_hz="30000"), synthetic_hf_rules)
    base = next(
        candidate
        for candidate in boundary.trace.clearance_candidates
        if candidate.candidate_id == boundary.trace.governing_clearance_candidate_id
    )

    iteration = iterate_field_clearance(effective, base, synthetic_hf_rules)

    assert iteration.tolerance_mm == Decimal("0.2")
    assert iteration.max_iterations == 10
    assert len(iteration.iterations) == 6
    assert tuple(item.number for item in iteration.iterations) == (1, 2, 3, 4, 5, 6)
    assert iteration.iterations[0].previous_clearance_mm == Decimal(3)
    assert iteration.iterations[0].calculated_clearance_mm == Decimal("7.5")
    assert iteration.iterations[-1].delta_mm == Decimal("0.140625")
    assert all(item.selected_route == "homogeneous" for item in iteration.iterations)
    assert iteration.candidate.distance_mm == Decimal("11.859375")
    assert iteration.candidate.mapping_id == "basic_hf_clearance_homogeneous"
    assert "field=homogeneous" in iteration.candidate.semantic_rule_id
    assert all(item.steps for item in iteration.iterations)

    result = calculate_pair(effective, synthetic_hf_rules)
    assert result.trace.hf_iterations == iteration.iterations
    assert result.trace.hf_iteration_tolerance_mm == Decimal("0.2")
    assert result.trace.hf_iteration_max_iterations == 10
    assert {
        "iec60664-4:field_iteration:tolerance",
        "iec60664-4:field_iteration:max_iterations",
    } <= set(result.trace.semantic_rule_ids)
    assert result.trace.governing_clearance_candidate_id == "part4_periodic_clearance"


def test_failed_radius_criterion_routes_approximately_homogeneous_to_direct_path(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="100000",
            field_condition=FieldCondition.APPROXIMATELY_HOMOGENEOUS,
            electrode_radius_mm="1",
        ),
        synthetic_hf_rules,
    )
    candidate = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == "part4_periodic_clearance"
    )

    assert len(result.trace.hf_iterations) == 1
    assert result.trace.hf_iterations[0].selected_route == "inhomogeneous"
    assert candidate.distance_mm == Decimal(12)
    assert candidate.mapping_id == "basic_hf_clearance_inhomogeneous"
    assert "field=inhomogeneous" in candidate.semantic_rule_id


def test_iteration_non_convergence_blocks_with_stable_code(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    limit = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-hf-iteration-limit"
    )
    one_iteration = limit.model_copy(
        update={"cells": (limit.cells[0].model_copy(update={"value": Decimal(1)}),)}
    )
    rules = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "tables": tuple(
                    one_iteration if table.id == limit.id else table
                    for table in synthetic_hf_rules.tables
                )
            }
        ),
        tmp_path / "one-iteration.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(
                frequency_hz="100000",
                field_condition=FieldCondition.HOMOGENEOUS,
                electrode_radius_mm="10",
            ),
            rules,
        )

    assert caught.value.code == "HF_ITERATION_DID_NOT_CONVERGE"
    assert len(caught.value.iterations) == 1
    assert caught.value.iterations[0].number == 1


def test_part4_deterioration_is_included_only_when_mapped(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    without_deterioration = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "mappings": tuple(
                    mapping
                    for mapping in synthetic_hf_rules.mappings
                    if mapping.id != "basic_hf_creepage"
                )
            }
        ),
        tmp_path / "without-hf-deterioration.icrules",
    )

    result = calculate_pair(
        case_factory(frequency_hz="100000"),
        without_deterioration,
    )

    assert "part4_deterioration" not in {
        candidate.candidate_id for candidate in result.trace.creepage_candidates
    }
    assert result.creepage_mm == result.clearance_mm


def test_altitude_correction_starts_above_2000_m_and_is_monotonic(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    at_boundary = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="2000"),
        synthetic_hf_rules,
    )
    interpolated = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="3000"),
        synthetic_hf_rules,
    )
    upper = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="4000"),
        synthetic_hf_rules,
    )
    supported_limit = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="6000"),
        synthetic_hf_rules,
    )

    assert at_boundary.clearance_mm == Decimal(12)
    assert interpolated.clearance_mm == Decimal("13.2")
    assert upper.clearance_mm == Decimal("14.4")
    assert supported_limit.clearance_mm == Decimal(18)
    assert (
        at_boundary.clearance_mm
        <= interpolated.clearance_mm
        <= upper.clearance_mm
        <= supported_limit.clearance_mm
    )
    assert interpolated.trace.pre_altitude_clearance_mm == Decimal(12)
    assert interpolated.trace.altitude_correction_applied is True


def test_altitude_applies_after_part1_governing_even_without_part4(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(frequency_hz="30000", altitude_m="3000"),
        synthetic_hf_rules,
    )

    assert result.trace.used_part4 is False
    assert result.trace.pre_altitude_clearance_mm == Decimal(3)
    assert result.clearance_mm == Decimal("3.3")


@pytest.mark.parametrize("altitude_m", ("-1", "6000.1"))
def test_unsupported_altitude_range_blocks(
    altitude_m: str,
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m=altitude_m),
            synthetic_hf_rules,
        )

    assert caught.value.code == "ALTITUDE_OUT_OF_RANGE"


def test_altitude_corrected_clearance_is_reapplied_as_creepage_floor(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="3000"),
        synthetic_hf_rules,
    )
    candidate_ids = tuple(candidate.candidate_id for candidate in result.trace.creepage_candidates)
    floor = next(
        candidate
        for candidate in result.trace.creepage_candidates
        if candidate.candidate_id == "clearance_floor"
    )

    assert candidate_ids == (
        "long_term_rms_tracking",
        "clearance_floor",
        "part4_deterioration",
    )
    assert floor.distance_mm == result.clearance_mm == Decimal("13.2")
    assert result.creepage_mm == result.clearance_mm
    assert result.trace.governing_creepage_candidate_id == "clearance_floor"

    semantic_ids = tuple(step.semantic_rule_id for step in result.trace.steps)
    assert semantic_ids.index("clearance.maximum") < semantic_ids.index(
        "iec60664-1:altitude_correction:base=2000m"
    )
    assert semantic_ids.index("iec60664-1:altitude_correction:base=2000m") < semantic_ids.index(
        "part1.creepage.clearance_floor.candidate"
    )
