from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import (
    CalculationError,
    RequiredStressError,
    calculate_pair,
)
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
from insulation_coordination.domain.rules import (
    Compare,
    LinearInterpolate,
    Literal,
    Lookup,
    Multiply,
    Parameter,
    RulePackage,
    Select,
    SupportedRange,
    Variable,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def _seal_rules(rules: RulePackage, path: Path) -> RulePackage:
    write_rule_package(path, rules.model_copy(update={"checksums": {}, "package_sha256": None}))
    return load_rule_package(path)


def _replace_formula(rules: RulePackage, formula_id: str, **updates: object) -> RulePackage:
    return rules.model_copy(
        update={
            "formulas": tuple(
                formula.model_copy(update=updates) if formula.id == formula_id else formula
                for formula in rules.formulas
            )
        }
    )


def _negative_mm_expression() -> Multiply:
    return Multiply(
        operands=(
            Lookup(
                table_id="synthetic-hf-iteration-tolerance",
                row=Literal(value=Decimal(1)),
                column=Literal(value=Decimal(1)),
            ),
            Literal(value=Decimal(-1)),
        )
    )


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


@pytest.mark.parametrize(
    ("selected_field", "steady", "temporary", "recurring"),
    (
        ("steady_state_peak_v", "600", "500", "400"),
        ("temporary_overvoltage_peak_v", "300", "600", "400"),
        ("recurring_peak_v", "300", "500", "600"),
    ),
)
def test_periodic_peak_selection_traces_each_possible_governing_source(
    selected_field: str,
    steady: str,
    temporary: str,
    recurring: str,
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="100000",
            steady_state_peak_v=PairVoltage.applicable(Decimal(steady)),
            temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(temporary)),
            recurring_peak_v=PairVoltage.applicable(Decimal(recurring)),
        ),
        synthetic_hf_rules,
    )
    candidate = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == "part4_periodic_clearance"
    )
    selection_index = next(
        index
        for index, step in enumerate(candidate.steps)
        if step.semantic_rule_id == "iec60664-4:periodic_peak.maximum"
    )

    assert candidate.stress.value == Decimal(600)
    assert selected_field in candidate.steps[selection_index].reason
    assert candidate.steps[selection_index].operation == "maximum"
    assert selection_index < next(
        index
        for index, step in enumerate(candidate.steps)
        if step.semantic_rule_id == candidate.formula_id
    )


def test_periodic_peak_tie_is_deterministic_and_names_all_tied_sources(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    result = calculate_pair(
        case_factory(
            frequency_hz="100000",
            steady_state_peak_v=PairVoltage.applicable(Decimal(600)),
            temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(600)),
            recurring_peak_v=PairVoltage.applicable(Decimal(400)),
        ),
        synthetic_hf_rules,
    )
    step = next(
        step
        for step in result.trace.steps
        if step.semantic_rule_id == "iec60664-4:periodic_peak.maximum"
    )

    assert "tie" in step.reason
    assert "steady_state_peak_v" in step.reason
    assert "temporary_overvoltage_peak_v" in step.reason


def test_periodic_peak_retains_not_applicable_omission_and_justification(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    case = case_factory(
        frequency_hz="100000",
        steady_state_peak_v=PairVoltage.not_applicable("Synthetic steady path absent."),
    )
    boundary = calculate_pair(case_factory(frequency_hz="30000"), synthetic_hf_rules)
    base = next(
        candidate
        for candidate in boundary.trace.clearance_candidates
        if candidate.candidate_id == boundary.trace.governing_clearance_candidate_id
    )

    high_frequency = calculate_high_frequency_candidates(case, base, synthetic_hf_rules)
    result = calculate_pair(case, synthetic_hf_rules)

    assert high_frequency.periodic_peak_omissions[0].stress_field == "steady_state_peak_v"
    assert high_frequency.periodic_peak_omissions[0].justification == (
        "Synthetic steady path absent."
    )
    assert (
        len(
            [
                omission
                for omission in result.trace.omissions
                if omission.stress_field == "steady_state_peak_v"
            ]
        )
        == 1
    )
    selection = next(
        step
        for step in result.trace.steps
        if step.semantic_rule_id == "iec60664-4:periodic_peak.maximum"
    )
    assert len(selection.inputs) == 2


def test_blank_periodic_peak_input_remains_blocking_above_30_khz(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    with pytest.raises(RequiredStressError, match="steady_state_peak_v"):
        calculate_pair(
            case_factory(
                frequency_hz="100000",
                steady_state_peak_v=PairVoltage.blank(),
            ),
            synthetic_hf_rules,
        )


@pytest.mark.parametrize(
    ("formula_id", "field_condition", "radius"),
    (
        ("synthetic-hf-inhomogeneous-clearance", FieldCondition.INHOMOGENEOUS, None),
        ("synthetic-hf-homogeneous-clearance", FieldCondition.HOMOGENEOUS, "10"),
        ("synthetic-hf-creepage", FieldCondition.INHOMOGENEOUS, None),
    ),
    ids=("direct", "iteration", "deterioration"),
)
def test_hf_distance_routes_reject_declared_non_mm_outputs(
    formula_id: str,
    field_condition: FieldCondition,
    radius: str | None,
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            formula_id,
            expression=Variable(name="periodic_peak_v"),
            unit="V",
            supported_ranges=(),
        ),
        tmp_path / f"{formula_id}-wrong-unit.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(
                frequency_hz="100000",
                field_condition=field_condition,
                electrode_radius_mm=radius,
            ),
            rules,
        )

    assert caught.value.code == "HF_DISTANCE_UNIT_INVALID"


@pytest.mark.parametrize(
    ("formula_id", "field_condition", "radius"),
    (
        ("synthetic-hf-inhomogeneous-clearance", FieldCondition.INHOMOGENEOUS, None),
        ("synthetic-hf-homogeneous-clearance", FieldCondition.HOMOGENEOUS, "10"),
        ("synthetic-hf-creepage", FieldCondition.INHOMOGENEOUS, None),
    ),
    ids=("direct", "iteration", "deterioration"),
)
def test_hf_distance_routes_reject_negative_outputs_without_model_validation_leak(
    formula_id: str,
    field_condition: FieldCondition,
    radius: str | None,
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            formula_id,
            expression=_negative_mm_expression(),
            unit="mm",
            supported_ranges=(),
        ),
        tmp_path / f"{formula_id}-negative.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(
                frequency_hz="100000",
                field_condition=field_condition,
                electrode_radius_mm=radius,
            ),
            rules,
        )

    assert caught.value.code == "HF_DISTANCE_NEGATIVE"


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


def test_public_iteration_blocks_at_part4_boundary(
    case_factory,
    synthetic_hf_rules: RulePackage,
) -> None:
    effective = case_factory(
        frequency_hz="30000",
        field_condition=FieldCondition.HOMOGENEOUS,
        electrode_radius_mm="10",
    )
    result = calculate_pair(case_factory(frequency_hz="30000"), synthetic_hf_rules)
    base = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == result.trace.governing_clearance_candidate_id
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        iterate_field_clearance(effective, base, synthetic_hf_rules)

    assert caught.value.code == "HF_FREQUENCY_NOT_APPLICABLE"


def test_public_iteration_requires_functional_hf_applicability(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "mappings": tuple(
                    mapping
                    for mapping in synthetic_hf_rules.mappings
                    if mapping.id != "functional_hf_applicability"
                )
            }
        ),
        tmp_path / "iteration-missing-functional-applicability.icrules",
    )
    effective = case_factory(
        kind=InsulationType.FUNCTIONAL,
        frequency_hz="100000",
        field_condition=FieldCondition.HOMOGENEOUS,
        electrode_radius_mm="10",
    )
    base_result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="30000"),
        synthetic_hf_rules,
    )
    base = next(
        candidate
        for candidate in base_result.trace.clearance_candidates
        if candidate.candidate_id == base_result.trace.governing_clearance_candidate_id
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        iterate_field_clearance(effective, base, rules)

    assert caught.value.code == "FUNCTIONAL_HF_MAPPING_MISSING"


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
    first_iteration_ids = tuple(step.semantic_rule_id for step in iteration.iterations[0].steps)
    assert first_iteration_ids.index(
        "iec60664-4:radius_criterion:field=homogeneous"
    ) < first_iteration_ids.index("iec60664-4:critical_frequency:field=homogeneous")

    result = calculate_pair(effective, synthetic_hf_rules)
    assert result.trace.hf_iterations == iteration.iterations
    assert result.trace.hf_iteration_tolerance_mm == Decimal("0.2")
    assert result.trace.hf_iteration_max_iterations == 10
    assert {
        "iec60664-4:field_iteration:tolerance",
        "iec60664-4:field_iteration:max_iterations",
    } <= set(result.trace.semantic_rule_ids)
    assert result.trace.governing_clearance_candidate_id == "part4_periodic_clearance"
    assert result.verification_requirements == result.trace.verification_requirements
    requirement = result.verification_requirements[0]
    assert requirement.code == "FIELD_CONDITION_CONFIRMATION"
    assert requirement.semantic_rule_id is not None
    assert "field=homogeneous" in requirement.semantic_rule_id
    assert requirement.source_reference is not None


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


def test_false_radius_criterion_skips_irrelevant_critical_frequency_range(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    critical = next(
        formula
        for formula in synthetic_hf_rules.formulas
        if formula.id == "synthetic-hf-critical-frequency"
    )
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            critical.id,
            supported_ranges=(
                SupportedRange(
                    variable="clearance_mm",
                    minimum=Decimal(0),
                    maximum=Decimal(2),
                    unit="mm",
                    source=critical.source,
                ),
            ),
        ),
        tmp_path / "critical-range-irrelevant.icrules",
    )

    result = calculate_pair(
        case_factory(
            frequency_hz="100000",
            field_condition=FieldCondition.APPROXIMATELY_HOMOGENEOUS,
            electrode_radius_mm="1",
        ),
        rules,
    )
    candidate = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == "part4_periodic_clearance"
    )

    assert candidate.mapping_id == "basic_hf_clearance_inhomogeneous"
    assert any(
        step.semantic_rule_id == "iec60664-4:radius_criterion:field=approximately_homogeneous"
        for step in candidate.steps
    )
    assert all("critical_frequency" not in step.semantic_rule_id for step in candidate.steps)


def test_false_radius_criterion_skips_unused_homogeneous_clearance_mapping(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "mappings": tuple(
                    mapping
                    for mapping in synthetic_hf_rules.mappings
                    if mapping.id != "basic_hf_clearance_approximately_homogeneous"
                )
            }
        ),
        tmp_path / "homogeneous-clearance-unused.icrules",
    )

    result = calculate_pair(
        case_factory(
            frequency_hz="100000",
            field_condition=FieldCondition.APPROXIMATELY_HOMOGENEOUS,
            electrode_radius_mm="1",
        ),
        rules,
    )

    assert result.trace.hf_iterations[0].selected_route == "inhomogeneous"
    assert result.trace.governing_clearance_candidate_id == "part4_periodic_clearance"


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


def test_direct_altitude_interpolation_retains_selected_factor_column_sources(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    factor = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-altitude-factor"
    )
    expanded_factor = factor.model_copy(
        update={
            "column_axis": factor.column_axis.model_copy(
                update={"values": (Decimal(1), Decimal(2))}
            ),
            "cells": (
                *factor.cells,
                *(
                    cell.model_copy(
                        update={
                            "column": 1,
                            "value": Decimal(9),
                            "source": cell.source.model_copy(update={"column": "unused"}),
                        }
                    )
                    for cell in factor.cells
                ),
            ),
        }
    )
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules.model_copy(
                update={
                    "tables": tuple(
                        expanded_factor if table.id == factor.id else table
                        for table in synthetic_hf_rules.tables
                    )
                }
            ),
            "synthetic-altitude-correction",
            expression=LinearInterpolate(
                table_id=factor.id,
                x=Variable(name="altitude_m"),
                column=Literal(value=Decimal(1)),
            ),
        ),
        tmp_path / "explicit-altitude-factor-column.icrules",
    )

    result = calculate_pair(
        case_factory(frequency_hz="100000", altitude_m="3000"),
        rules,
    )
    step = next(
        step
        for step in result.trace.steps
        if step.semantic_rule_id == "iec60664-1:altitude_correction:base=2000m"
    )

    assert result.clearance_mm == Decimal("13.2")
    assert step.source_reference == expanded_factor.source
    assert step.source_cells == ("2000m/1", "4000m/1")
    assert step.cell_references == (
        expanded_factor.cells[0].source,
        expanded_factor.cells[1].source,
    )


def test_composed_altitude_hump_matching_table_rows_is_rejected(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    direct = LinearInterpolate(
        table_id="synthetic-altitude-factor",
        x=Variable(name="altitude_m"),
    )
    hump = Select(
        condition=Compare(
            comparison="eq",
            left=direct,
            right=Literal(value=Decimal("1.1")),
        ),
        if_true=Literal(value=Decimal("0.5")),
        if_false=Literal(value=Decimal(1)),
    )
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            "synthetic-altitude-correction",
            expression=Multiply(operands=(direct, hump)),
        ),
        tmp_path / "composed-altitude-hump.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_altitude_interpolation_requires_direct_altitude_variable(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            "synthetic-altitude-correction",
            expression=LinearInterpolate(
                table_id="synthetic-altitude-factor",
                x=Multiply(
                    operands=(
                        Variable(name="altitude_m"),
                        Literal(value=Decimal(1)),
                    )
                ),
            ),
        ),
        tmp_path / "composed-altitude-variable.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_altitude_interpolation_rejects_non_altitude_variable(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    factor = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-altitude-factor"
    )
    height_factor = factor.model_copy(
        update={
            "row_axis": factor.row_axis.model_copy(update={"id": "height_m"}),
            "supported_ranges": tuple(
                supported.model_copy(update={"variable": "height_m"})
                for supported in factor.supported_ranges
            ),
        }
    )
    altitude = next(
        formula
        for formula in synthetic_hf_rules.formulas
        if formula.id == "synthetic-altitude-correction"
    )
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules.model_copy(
                update={
                    "tables": tuple(
                        height_factor if table.id == factor.id else table
                        for table in synthetic_hf_rules.tables
                    )
                }
            ),
            altitude.id,
            expression=LinearInterpolate(
                table_id=height_factor.id,
                x=Variable(name="height_m"),
            ),
            parameter_sets=(
                altitude.parameter_sets[0].model_copy(
                    update={
                        "parameters": (
                            *altitude.parameter_sets[0].parameters,
                            Parameter(name="height_m", unit="m"),
                        )
                    }
                ),
            ),
        ),
        tmp_path / "wrong-altitude-variable.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_altitude_interpolation_rejects_non_altitude_table(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    frequency_factor = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-hf-frequency-factor"
    )
    wrong_table = frequency_factor.model_copy(
        update={
            "id": "synthetic-wrong-altitude-factor",
            "row_axis": frequency_factor.row_axis.model_copy(update={"id": "altitude_m"}),
            "supported_ranges": tuple(
                supported.model_copy(update={"variable": "altitude_m"})
                for supported in frequency_factor.supported_ranges
            ),
        }
    )
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules.model_copy(
                update={"tables": (*synthetic_hf_rules.tables, wrong_table)}
            ),
            "synthetic-altitude-correction",
            expression=LinearInterpolate(
                table_id=wrong_table.id,
                x=Variable(name="altitude_m"),
            ),
        ),
        tmp_path / "wrong-altitude-table.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_altitude_interpolation_rejects_composed_column_selector(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    rules = _seal_rules(
        _replace_formula(
            synthetic_hf_rules,
            "synthetic-altitude-correction",
            expression=LinearInterpolate(
                table_id="synthetic-altitude-factor",
                x=Variable(name="altitude_m"),
                column=Select(
                    condition=Compare(
                        comparison="eq",
                        left=Variable(name="altitude_m"),
                        right=Variable(name="altitude_m"),
                    ),
                    if_true=Literal(value=Decimal(1)),
                    if_false=Literal(value=Decimal(1)),
                ),
            ),
        ),
        tmp_path / "composed-altitude-column.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_nonmonotonic_approved_altitude_curve_is_rejected_across_supported_domain(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    factor = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-altitude-factor"
    )
    nonmonotonic = factor.model_copy(
        update={
            "cells": (
                factor.cells[0],
                factor.cells[1].model_copy(update={"value": Decimal("1.4")}),
                factor.cells[2].model_copy(update={"value": Decimal("1.3")}),
            )
        }
    )
    rules = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "tables": tuple(
                    nonmonotonic if table.id == factor.id else table
                    for table in synthetic_hf_rules.tables
                )
            }
        ),
        tmp_path / "nonmonotonic-altitude.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


def test_altitude_curve_must_equal_uncorrected_clearance_at_boundary(
    case_factory,
    synthetic_hf_rules: RulePackage,
    tmp_path: Path,
) -> None:
    factor = next(
        table for table in synthetic_hf_rules.tables if table.id == "synthetic-altitude-factor"
    )
    shifted_boundary = factor.model_copy(
        update={
            "cells": (
                factor.cells[0].model_copy(update={"value": Decimal("1.1")}),
                *factor.cells[1:],
            )
        }
    )
    rules = _seal_rules(
        synthetic_hf_rules.model_copy(
            update={
                "tables": tuple(
                    shifted_boundary if table.id == factor.id else table
                    for table in synthetic_hf_rules.tables
                )
            }
        ),
        tmp_path / "shifted-altitude-boundary.icrules",
    )

    with pytest.raises(HighFrequencyCalculationError) as caught:
        calculate_pair(
            case_factory(frequency_hz="100000", altitude_m="3000"),
            rules,
        )

    assert caught.value.code == "ALTITUDE_RULE_INVALID"


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
