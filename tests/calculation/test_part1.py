from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.calculation.clearance import calculate_clearance_candidates
from insulation_coordination.calculation.creepage import calculate_creepage_candidates
from insulation_coordination.calculation.engine import (
    CALCULATION_ENGINE_VERSION,
    CalculationError,
    CalculationRangeError,
    RequiredStressError,
    RuleMappingError,
    RulePackageValidationError,
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
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.validation import validate_rule_package


def _seal_rules(rules: RulePackage, path: Path) -> RulePackage:
    write_rule_package(
        path,
        rules.model_copy(update={"checksums": {}, "package_sha256": None}),
    )
    return load_rule_package(path)


def _with_nonfinite_axis(rules: RulePackage, value: Decimal) -> RulePackage:
    table = rules.tables[0]
    axis = table.row_axis.model_copy(
        update={"values": (value, *table.row_axis.values[1:])}
    )
    return rules.model_copy(
        update={
            "tables": (
                table.model_copy(update={"row_axis": axis}),
                *rules.tables[1:],
            )
        }
    )


def _with_nonfinite_cell(rules: RulePackage, value: Decimal) -> RulePackage:
    table = rules.tables[0]
    cell = table.cells[0].model_copy(update={"value": value})
    return rules.model_copy(
        update={
            "tables": (
                table.model_copy(update={"cells": (cell, *table.cells[1:])}),
                *rules.tables[1:],
            )
        }
    )


def _with_nonfinite_range(rules: RulePackage, value: Decimal) -> RulePackage:
    table = rules.tables[0]
    supported = table.supported_ranges[0].model_copy(update={"minimum": value})
    return rules.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "supported_ranges": (
                            supported,
                            *table.supported_ranges[1:],
                        )
                    }
                ),
                *rules.tables[1:],
            )
        }
    )


def _with_nonfinite_formula_literal(
    rules: RulePackage,
    value: Decimal,
) -> RulePackage:
    formula = rules.formulas[0].model_copy(
        update={"expression": {"op": "literal", "value": value}}
    )
    return rules.model_copy(
        update={"formulas": (formula, *rules.formulas[1:])}
    )


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


def test_result_and_trace_pin_exact_rule_and_engine_identity(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(case_factory(), synthetic_rules)
    expected = (
        synthetic_rules.manifest.package_id,
        synthetic_rules.manifest.version,
        synthetic_rules.package_sha256,
        CALCULATION_ENGINE_VERSION,
    )

    assert (
        result.rule_package_id,
        result.rule_package_version,
        result.rule_package_sha256,
        result.calculation_engine_version,
    ) == expected
    assert (
        result.trace.rule_package_id,
        result.trace.rule_package_version,
        result.trace.rule_package_sha256,
        result.trace.calculation_engine_version,
    ) == expected


def test_tampered_rule_content_blocks_before_any_distance_result(
    case_factory, synthetic_rules: RulePackage
) -> None:
    table = synthetic_rules.tables[-1]
    cell = table.cells[-1]
    tampered = synthetic_rules.model_copy(
        update={
            "tables": (
                *synthetic_rules.tables[:-1],
                table.model_copy(
                    update={
                        "cells": (
                            *table.cells[:-1],
                            cell.model_copy(update={"value": cell.value + Decimal(1)}),
                        )
                    }
                ),
            )
        }
    )

    case = case_factory()
    entries = (
        lambda: calculate_pair(case, tampered),
        lambda: calculate_clearance_candidates(case, tampered),
        lambda: calculate_creepage_candidates(case, Decimal(3), tampered),
    )
    for entry in entries:
        with pytest.raises(RulePackageValidationError) as caught:
            entry()

        assert {"checksums", "package_digest"} <= set(caught.value.issue_codes)
        assert all(issue.message for issue in caught.value.issues)


def test_dangling_unrelated_mapping_blocks_as_semantically_invalid(
    case_factory, synthetic_rules: RulePackage
) -> None:
    dangling = synthetic_rules.model_copy(
        update={
            "mappings": (
                *synthetic_rules.mappings[:-1],
                synthetic_rules.mappings[-1].model_copy(
                    update={"target_rule_id": "missing-formula"}
                ),
            )
        }
    )

    with pytest.raises(RulePackageValidationError) as caught:
        calculate_pair(case_factory(), dangling)

    assert "mapping_links" in caught.value.issue_codes


def test_duplicate_unrelated_mapping_route_blocks_as_semantically_ambiguous(
    case_factory, synthetic_rules: RulePackage
) -> None:
    original = synthetic_rules.mappings[-1]
    duplicate = original.model_copy(update={"id": "duplicate-unrelated-route"})
    ambiguous = synthetic_rules.model_copy(
        update={"mappings": (*synthetic_rules.mappings, duplicate)}
    )

    with pytest.raises(RulePackageValidationError) as caught:
        calculate_pair(case_factory(), ambiguous)

    assert "mapping_routes" in caught.value.issue_codes


def test_missing_approval_record_or_checksum_blocks_at_rule_trust_gate(
    case_factory, synthetic_rules: RulePackage
) -> None:
    no_approval = synthetic_rules.model_copy(
        update={"manifest": synthetic_rules.manifest.model_copy(update={"approval_records": ()})}
    )
    no_checksum = synthetic_rules.model_copy(update={"checksums": {}})

    with pytest.raises(RulePackageValidationError) as approval_error:
        calculate_pair(case_factory(), no_approval)
    with pytest.raises(RulePackageValidationError) as checksum_error:
        calculate_pair(case_factory(), no_checksum)

    assert "approval_record" in approval_error.value.issue_codes
    assert "checksums" in checksum_error.value.issue_codes


@pytest.mark.parametrize(
    "mutate",
    [
        _with_nonfinite_axis,
        _with_nonfinite_cell,
        _with_nonfinite_range,
        _with_nonfinite_formula_literal,
    ],
    ids=("axis", "cell", "range", "formula-literal"),
)
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_nonfinite_rule_values_are_total_validation_failures_at_all_entries(
    mutate,
    value: Decimal,
    case_factory,
    synthetic_rules: RulePackage,
) -> None:
    invalid = mutate(synthetic_rules, value)

    report = validate_rule_package(invalid)

    assert report.is_valid is False
    structure = next(
        result for result in report.results if result.code == "package_structure"
    )
    assert structure.passed is False
    assert "invalid structure" in structure.message

    case = case_factory()
    entries = (
        lambda: calculate_pair(case, invalid),
        lambda: calculate_clearance_candidates(case, invalid),
        lambda: calculate_creepage_candidates(case, Decimal(3), invalid),
    )
    for entry in entries:
        with pytest.raises(RulePackageValidationError) as caught:
            entry()
        assert "package_structure" in caught.value.issue_codes


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


def test_clearance_floor_candidate_has_evaluator_trace_before_final_maximum(
    case_factory, synthetic_rules: RulePackage
) -> None:
    result = calculate_pair(case_factory(kind=InsulationType.BASIC), synthetic_rules)
    floor = next(
        candidate
        for candidate in result.trace.creepage_candidates
        if candidate.candidate_id == "clearance_floor"
    )

    assert floor.distance_mm < result.creepage_mm
    assert len(floor.steps) == 1
    assert floor.steps[0].operation == "variable"
    assert floor.steps[0].output.value == result.clearance_mm
    assert floor.steps[0].output.unit == "mm"
    assert result.trace.steps[-2] == floor.steps[0]
    assert result.trace.steps[-1].operation == "maximum"


def test_unsupported_special_assumptions_block_with_actionable_error(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(UnsupportedCaseError, match="conventional construction assumption"):
        calculate_pair(
            case_factory(assumptions=("synthetic-unmapped-special-construction",)),
            synthetic_rules,
        )


def test_frequency_above_part1_scope_requires_an_approved_part4_mapping(
    case_factory, synthetic_rules: RulePackage
) -> None:
    with pytest.raises(RuleMappingError, match="part4_periodic_clearance mapping is missing"):
        calculate_pair(case_factory(frequency_hz="30001"), synthetic_rules)


def test_missing_or_unsupported_categorical_mapping_never_falls_back(
    case_factory, synthetic_rules: RulePackage, tmp_path: Path
) -> None:
    missing = _seal_rules(
        synthetic_rules.model_copy(update={"mappings": synthetic_rules.mappings[1:]}),
        tmp_path / "missing-route.icrules",
    )
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
    case_factory, synthetic_rules: RulePackage, tmp_path: Path
) -> None:
    table = synthetic_rules.tables[0]
    invalid_table = table.model_copy(
        update={
            "cells": tuple(cell.model_copy(update={"value": Decimal(-1)}) for cell in table.cells)
        }
    )
    invalid_rules = _seal_rules(
        synthetic_rules.model_copy(update={"tables": (invalid_table, *synthetic_rules.tables[1:])}),
        tmp_path / "negative-distance.icrules",
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
