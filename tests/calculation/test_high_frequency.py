from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.calculation.clearance import calculate_clearance_candidates
from insulation_coordination.calculation.engine import RequiredStressError, calculate_pair
from insulation_coordination.calculation.high_frequency import (
    HighFrequencyCalculationError,
    calculate_critical_frequency,
    calculate_high_frequency_candidates,
    select_frequency_factor,
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


@pytest.fixture
def case_factory():
    def make(
        *,
        kind: InsulationType = InsulationType.BASIC,
        frequency_hz: str = "30000",
        field_condition: FieldCondition = FieldCondition.INHOMOGENEOUS,
        electrode_radius_mm: str | None = None,
        altitude_m: str = "0",
        construction_type: ConstructionType = ConstructionType.OTHER,
        steady_state_peak_v: PairVoltage | None = None,
        temporary_overvoltage_peak_v: PairVoltage | None = None,
        recurring_peak_v: PairVoltage | None = None,
    ) -> EffectiveCase:
        return EffectiveCase(
            id=UUID(int=7),
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            voltages=PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(500)),
                steady_state_peak_v=steady_state_peak_v or PairVoltage.applicable(Decimal(300)),
                recurring_peak_v=recurring_peak_v or PairVoltage.applicable(Decimal(400)),
                temporary_overvoltage_peak_v=temporary_overvoltage_peak_v
                or PairVoltage.applicable(Decimal(600)),
            ),
            frequency_hz=EffectiveValue(
                value=Decimal(frequency_hz),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            impulse_v=EffectiveValue(
                value=Decimal(1000),
                provenance=Provenance.PAIR_OVERRIDE,
            ),
            insulation_type=EffectiveValue(value=kind, provenance=Provenance.PAIR_OVERRIDE),
            field_condition=EffectiveValue(
                value=field_condition,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            electrode_radius_mm=EffectiveValue(
                value=None if electrode_radius_mm is None else Decimal(electrode_radius_mm),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            altitude_m=EffectiveValue(
                value=Decimal(altitude_m),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            pollution_degree=EffectiveValue(value=2, provenance=Provenance.PROJECT_DEFAULT),
            construction_type=EffectiveValue(
                value=construction_type,
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


def _periodic_base(case: EffectiveCase, rules: RulePackage):
    return max(
        (
            candidate
            for candidate in calculate_clearance_candidates(case, rules)
            if candidate.candidate_id != "impulse"
        ),
        key=lambda candidate: candidate.distance_mm,
    )


def test_part4_starts_only_above_30_khz(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    at_boundary = calculate_pair(case_factory(frequency_hz="30000"), semantic_part4_rules)
    above = calculate_pair(case_factory(frequency_hz="30000.1"), semantic_part4_rules)

    assert at_boundary.trace.used_part4 is False
    assert above.trace.used_part4 is True


def test_critical_frequency_uses_each_pairs_clearance(
    semantic_part4_rules: RulePackage,
) -> None:
    one_mm = calculate_critical_frequency(Decimal(1), semantic_part4_rules)
    two_mm = calculate_critical_frequency(Decimal(2), semantic_part4_rules)

    assert (one_mm.value, one_mm.unit) == (Decimal(200000), "Hz")
    assert (two_mm.value, two_mm.unit) == (Decimal(100000), "Hz")
    assert one_mm.steps[-1].semantic_rule_id == "iec60664-4-equation-1-critical-frequency"


@pytest.mark.parametrize(
    ("frequency_hz", "expected_percent", "expected_branch"),
    (
        ("199999", "100", "below_critical"),
        ("200000", "100", "critical_to_minimum"),
        ("1600000", "112.5", "critical_to_minimum"),
        ("3000000", "125", "at_or_above_minimum"),
    ),
)
def test_frequency_factor_follows_iec_boundaries(
    frequency_hz: str,
    expected_percent: str,
    expected_branch: str,
    semantic_part4_rules: RulePackage,
) -> None:
    selected = select_frequency_factor(Decimal(frequency_hz), Decimal(200000), semantic_part4_rules)

    assert selected.percent == Decimal(expected_percent)
    assert selected.branch == expected_branch


@pytest.mark.parametrize(
    ("selected_field", "steady", "temporary", "recurring"),
    (
        ("steady_state_peak_v", "600", "500", "400"),
        ("temporary_overvoltage_peak_v", "300", "600", "400"),
        ("recurring_peak_v", "300", "500", "600"),
    ),
)
def test_periodic_peak_selects_and_traces_each_governing_source(
    selected_field: str,
    steady: str,
    temporary: str,
    recurring: str,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="60000",
        steady_state_peak_v=PairVoltage.applicable(Decimal(steady)),
        temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(temporary)),
        recurring_peak_v=PairVoltage.applicable(Decimal(recurring)),
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )
    step = next(
        item
        for item in result.clearance_candidates[0].steps
        if item.semantic_rule_id == "iec60664-4:periodic_peak.maximum"
    )

    assert selected_field in step.reason
    assert step.output.value == Decimal(600)


def test_periodic_peak_retains_omission_and_blank_blocks(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    omitted = case_factory(
        frequency_hz="60000",
        steady_state_peak_v=PairVoltage.not_applicable("No steady-state stress."),
    )
    result = calculate_high_frequency_candidates(
        omitted, _periodic_base(omitted, semantic_part4_rules), semantic_part4_rules
    )
    assert result.periodic_peak_omissions[0].justification == "No steady-state stress."

    blank = case_factory(frequency_hz="60000", steady_state_peak_v=PairVoltage.blank())
    with pytest.raises(RequiredStressError, match="steady_state_peak_v"):
        calculate_high_frequency_candidates(
            blank, _periodic_base(blank, semantic_part4_rules), semantic_part4_rules
        )


def test_inhomogeneous_table_1_activates_only_at_pair_critical_frequency(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    below = case_factory(frequency_hz="60000")
    above = case_factory(frequency_hz="100000")
    base = _periodic_base(below, semantic_part4_rules)

    below_result = calculate_high_frequency_candidates(below, base, semantic_part4_rules)
    above_result = calculate_high_frequency_candidates(above, base, semantic_part4_rules)

    assert below_result.clearance_candidates[0].distance_mm == base.distance_mm
    assert below_result.iterations[0].selected_route == "below_critical"
    assert above_result.clearance_candidates[0].formula_id == "iec60664-4:hf-clearance-table"
    assert above_result.iterations[-1].selected_route == "inhomogeneous_table_1"


def test_functional_insulation_uses_same_reviewed_part4_decision_without_fake_mapping(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="60000")
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert result.iterations[0].selected_route == "below_critical"
    assert all(
        "functional_applicability" not in step.semantic_rule_id
        for step in result.clearance_candidates[0].steps
    )


def test_homogeneous_field_requires_geometry(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(frequency_hz="100000", field_condition=FieldCondition.HOMOGENEOUS)

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_high_frequency_candidates(
            case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
        )

    assert caught.value.code == "HF_GEOMETRY_REQUIRED"


def test_radius_failure_routes_to_inhomogeneous_table_1(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="100000",
        field_condition=FieldCondition.APPROXIMATELY_HOMOGENEOUS,
        electrode_radius_mm="0.1",
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert result.iterations[-1].selected_route == "inhomogeneous_table_1"
    assert result.iterations[-1].radius_ratio < Decimal("0.2")


def test_homogeneous_clearance_stabilizes_on_source_rounded_second_pass(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="1600000",
        field_condition=FieldCondition.HOMOGENEOUS,
        electrode_radius_mm="10",
        temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(800)),
    )
    result = calculate_high_frequency_candidates(
        case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
    )

    assert len(result.iterations) == 2
    assert result.iterations[-1].stable is True
    assert result.clearance_candidates[0].distance_mm == Decimal("4.2")


def test_second_pass_instability_blocks_engineering_guess(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    case = case_factory(frequency_hz="90000")

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_high_frequency_candidates(
            case, _periodic_base(case, semantic_part4_rules), semantic_part4_rules
        )

    assert caught.value.code == "HF_SECOND_PASS_UNSTABLE"
    assert len(caught.value.iterations) == 2


def test_engine_trace_has_pair_decisions_and_no_fabricated_iteration_settings(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(case_factory(frequency_hz="60000"), semantic_part4_rules)
    iteration = result.trace.hf_iterations[0]

    assert iteration.critical_frequency_hz == Decimal(200000) / Decimal("3.1")
    assert iteration.actual_frequency_hz == Decimal(60000)
    assert iteration.factor_percent == Decimal(100)
    assert not hasattr(result.trace, "hf_iteration_tolerance_mm")
    assert not hasattr(result.trace, "hf_iteration_max_iterations")


@pytest.mark.parametrize(
    ("altitude_m", "factor", "applied"),
    (("0", "1", False), ("2000", "1", False), ("2500", "1.05", True), ("4000", "1.2", True)),
)
def test_a2_altitude_applies_after_clearance_maximum(
    altitude_m: str,
    factor: str,
    applied: bool,
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(frequency_hz="30000", altitude_m=altitude_m),
        semantic_part4_rules,
    )

    assert result.clearance_mm == result.trace.pre_altitude_clearance_mm * Decimal(factor)
    assert result.trace.altitude_correction_applied is applied
    if applied:
        step = next(
            item
            for item in result.trace.steps
            if item.semantic_rule_id == "iec60664-1:altitude_correction:base=2000m"
        )
        assert (
            step.source_cells == ("2000/clearance_factor", "3000/clearance_factor")
            or altitude_m == "4000"
        )
    else:
        step = next(
            item
            for item in result.trace.steps
            if item.semantic_rule_id == "iec60664-1:a2-altitude-not-applied"
        )
        assert "at or below 2000 m" in step.reason


def test_a2_altitude_outside_reviewed_range_blocks(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="30000", altitude_m="4000.1"),
            semantic_part4_rules,
        )

    assert caught.value.code == "ALTITUDE_OUT_OF_RANGE"


def test_f9_partial_discharge_is_source_backed_advice_not_clearance_candidate(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="30000",
            steady_state_peak_v=PairVoltage.applicable(Decimal(3000)),
            temporary_overvoltage_peak_v=PairVoltage.not_applicable("No TOV."),
            recurring_peak_v=PairVoltage.not_applicable("No recurring peak."),
        ),
        semantic_part4_rules,
    )
    warning = next(item for item in result.warnings if item.code == "PARTIAL_DISCHARGE_REVIEW")

    assert result.clearance_mm == result.trace.pre_altitude_clearance_mm
    assert all(
        candidate.formula_id != "iec60664-1-f9" for candidate in result.trace.clearance_candidates
    )
    assert warning.semantic_rule_id == "iec60664-1:f9-partial-discharge-advice"
    assert warning.source_reference is not None
    assert warning.source_reference.table == "F.9"


def test_homogeneous_case_b_requires_source_backed_withstand_test(
    case_factory,
    semantic_part4_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="30000",
            field_condition=FieldCondition.HOMOGENEOUS,
        ),
        semantic_part4_rules,
    )
    requirement = next(
        item for item in result.verification_requirements if item.code == "WITHSTAND_TEST_REQUIRED"
    )

    assert requirement.source_reference is not None
    assert requirement.source_reference.table == "F.8"
