from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.calculation.engine import (
    CalculationError,
    CalculationRangeError,
    RequiredStressError,
    RuleMappingError,
    UnsupportedCaseError,
    calculate_pair,
)
from insulation_coordination.domain.enums import (
    Applicability,
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
        impulse_v: str = "1000",
        long_term_rms_v: PairVoltage | None = None,
        steady_state_peak_v: PairVoltage | None = None,
        recurring_peak_v: PairVoltage | None = None,
        temporary_overvoltage_peak_v: PairVoltage | None = None,
        field_condition: FieldCondition = FieldCondition.INHOMOGENEOUS,
        construction_type: ConstructionType = ConstructionType.OTHER,
        pollution_degree: int = 2,
        material: str = "I",
        assumptions: tuple[str, ...] = (),
    ) -> EffectiveCase:
        return EffectiveCase(
            id=UUID(int=6),
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            voltages=PairVoltages(
                long_term_rms_v=long_term_rms_v or PairVoltage.applicable(Decimal(500)),
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
                value=Decimal(impulse_v),
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
                value=None,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            altitude_m=EffectiveValue(
                value=Decimal(0),
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            pollution_degree=EffectiveValue(
                value=pollution_degree,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            construction_type=EffectiveValue(
                value=construction_type,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            cti_or_material_group=EffectiveValue(
                value=material,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
            conventional_construction_assumptions=EffectiveValue(
                value=assumptions,
                provenance=Provenance.PROJECT_DEFAULT,
            ),
        )

    return make


@pytest.mark.parametrize(
    ("kind", "clearance", "creepage"),
    [
        (InsulationType.FUNCTIONAL, Decimal("2.0"), Decimal("3.0")),
        (InsulationType.BASIC, Decimal("3.0"), Decimal("4.0")),
        (InsulationType.REINFORCED, Decimal("5.5"), Decimal("8.0")),
    ],
)
def test_part1_paths_are_distinct(
    kind: InsulationType,
    clearance: Decimal,
    creepage: Decimal,
    case_factory,
    synthetic_rules: RulePackage,
) -> None:
    result = calculate_pair(case_factory(kind=kind, frequency_hz="30000"), synthetic_rules)

    assert result.clearance_mm == clearance
    assert result.creepage_mm == creepage
    assert result.trace.insulation_type is kind


def test_functional_path_does_not_apply_reinforced_scaling(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="30000"),
        synthetic_rules,
    )

    assert "reinforced_scale" not in result.trace.semantic_rule_ids
    assert all("reinforced" not in rule_id for rule_id in result.trace.semantic_rule_ids)


def test_clearance_retains_all_stress_candidates_and_governing_reason(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(case_factory(), synthetic_rules)

    assert tuple(candidate.candidate_id for candidate in result.trace.clearance_candidates) == (
        "impulse",
        "steady_state_peak",
        "temporary_overvoltage_peak",
        "recurring_peak",
    )
    assert result.trace.governing_clearance_candidate_id == "impulse"
    assert "impulse" in result.trace.governing_clearance_reason
    assert result.trace.clearance_candidates[0].stress.value == Decimal(1000)
    assert result.trace.clearance_candidates[0].stress.unit == "V"


def test_clearance_routes_impulse_and_periodic_stresses_independently(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL),
        synthetic_rules,
    )

    assert tuple(candidate.mapping_id for candidate in result.trace.clearance_candidates) == (
        "functional_clearance_impulse",
        "functional_clearance_periodic",
        "functional_clearance_periodic",
        "functional_clearance_periodic",
    )
    assert (
        result.trace.clearance_candidates[0].formula_id
        != result.trace.clearance_candidates[1].formula_id
    )


def test_clearance_pollution_branch_requires_an_exact_approved_mapping(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(RuleMappingError, match="pollution=3"):
        calculate_pair(
            case_factory(
                pollution_degree=3,
                long_term_rms_v=PairVoltage.not_applicable(
                    "Exclude creepage mapping from this clearance routing test."
                ),
            ),
            synthetic_rules,
        )


def test_blank_stress_blocks_instead_of_silently_omitting_candidate(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(RequiredStressError, match="steady_state_peak_v"):
        calculate_pair(
            case_factory(steady_state_peak_v=PairVoltage.blank()),
            synthetic_rules,
        )


def test_justified_not_applicable_omits_only_that_candidate_and_is_traced(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(
        case_factory(
            steady_state_peak_v=PairVoltage.not_applicable(
                "Synthetic source has no steady-state path."
            )
        ),
        synthetic_rules,
    )

    assert {candidate.candidate_id for candidate in result.trace.clearance_candidates} == {
        "impulse",
        "temporary_overvoltage_peak",
        "recurring_peak",
    }
    assert result.trace.omissions[0].candidate_id == "steady_state_peak"
    assert result.trace.omissions[0].justification == ("Synthetic source has no steady-state path.")


def test_creepage_clearance_floor_is_an_explicit_governing_step(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(
        case_factory(
            kind=InsulationType.REINFORCED,
            long_term_rms_v=PairVoltage.applicable(Decimal(100)),
        ),
        synthetic_rules,
    )

    assert result.clearance_mm == Decimal("5.50")
    assert result.creepage_mm == result.clearance_mm
    assert result.trace.steps[-1].semantic_rule_id == "part1.creepage.clearance_floor"
    assert result.trace.steps[-1].operation == "maximum"
    assert result.trace.steps[-1].reason == "final clearance governs creepage"


def test_unsupported_special_assumptions_block_with_actionable_error(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(UnsupportedCaseError, match="conventional construction assumption"):
        calculate_pair(
            case_factory(assumptions=("synthetic-unmapped-special-construction",)),
            synthetic_rules,
        )


def test_frequency_above_part1_scope_blocks_at_extension_seam(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(UnsupportedCaseError, match="through 30000 Hz"):
        calculate_pair(case_factory(frequency_hz="30001"), synthetic_rules)


def test_missing_or_unsupported_categorical_mapping_never_falls_back(
    case_factory, synthetic_rules: RulePackage
) -> None:
    missing = synthetic_rules.model_copy(update={"mappings": synthetic_rules.mappings[1:]})
    with pytest.raises(RuleMappingError, match="functional_clearance"):
        calculate_pair(
            case_factory(kind=InsulationType.FUNCTIONAL),
            missing,
        )

    with pytest.raises(RuleMappingError, match="field=homogeneous"):
        calculate_pair(
            case_factory(field_condition=FieldCondition.HOMOGENEOUS),
            synthetic_rules,
        )


def test_formula_range_error_names_candidate_and_rule(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(CalculationRangeError, match="impulse.*supported range"):
        calculate_pair(case_factory(impulse_v="1001"), synthetic_rules)


def test_invalid_rule_distance_is_normalized_to_typed_calculation_error(
    case_factory, synthetic_rules: RulePackage
) -> None:
    table = synthetic_rules.tables[0]
    invalid_table = table.model_copy(
        update={
            "cells": tuple(cell.model_copy(update={"value": Decimal(-1)}) for cell in table.cells)
        }
    )
    invalid_rules = synthetic_rules.model_copy(
        update={"tables": (invalid_table, *synthetic_rules.tables[1:])}
    )

    with pytest.raises(CalculationError, match="negative distance"):
        calculate_pair(
            case_factory(kind=InsulationType.FUNCTIONAL),
            invalid_rules,
        )


def test_reinforced_is_not_less_than_basic_for_same_effective_case(
    case_factory, synthetic_rules: RulePackage
) -> None:
    basic = calculate_pair(case_factory(kind=InsulationType.BASIC), synthetic_rules)
    reinforced = calculate_pair(
        case_factory(kind=InsulationType.REINFORCED),
        synthetic_rules,
    )

    assert reinforced.clearance_mm >= basic.clearance_mm
    assert reinforced.creepage_mm >= basic.creepage_mm
    assert basic.creepage_mm >= basic.clearance_mm
    assert reinforced.creepage_mm >= reinforced.clearance_mm


def test_result_is_deterministic_and_immutable(case_factory, synthetic_rules: RulePackage) -> None:
    first = calculate_pair(case_factory(), synthetic_rules)
    second = calculate_pair(case_factory(), synthetic_rules)

    assert first == second
    with pytest.raises(ValidationError, match="frozen"):
        first.clearance_mm = Decimal(99)  # type: ignore[misc]


def test_not_applicable_long_term_tracking_uses_only_clearance_floor(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(
        case_factory(
            long_term_rms_v=PairVoltage.not_applicable("No long-term tracking stress exists.")
        ),
        synthetic_rules,
    )

    assert result.creepage_mm == result.clearance_mm
    assert tuple(candidate.candidate_id for candidate in result.trace.creepage_candidates) == (
        "clearance_floor",
    )
    assert any(
        omission.stress_field == "long_term_rms_v"
        and omission.applicability is Applicability.NOT_APPLICABLE
        for omission in result.trace.omissions
    )
