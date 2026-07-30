from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.calculation.engine import (
    CalculationWarning,
    PairResult,
    VerificationRequirement,
    calculate_pair,
)
from insulation_coordination.calculation.grouping import (
    CalculationGroup,
    GroupingError,
    calculation_signature,
    group_results,
    merge_groups,
    split_group,
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
    GroupSplit,
    PairVoltage,
    PairVoltages,
)


@pytest.fixture
def result_factory(synthetic_rules):
    def make(*, pair_id: int, rms_v: str = "500"):
        result = calculate_pair(
            EffectiveCase(
                id=UUID(int=pair_id),
                key=f"pair-{pair_id}",
                net_a=UUID(int=100 + pair_id),
                net_b=UUID(int=200 + pair_id),
                voltages=PairVoltages(
                    long_term_rms_v=PairVoltage.applicable(Decimal(rms_v)),
                    steady_state_peak_v=PairVoltage.applicable(Decimal(300)),
                    recurring_peak_v=PairVoltage.applicable(Decimal(400)),
                    temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(600)),
                ),
                frequency_hz=EffectiveValue(
                    value=Decimal(30000), provenance=Provenance.PROJECT_DEFAULT
                ),
                impulse_v=EffectiveValue(
                    value=Decimal(1000), provenance=Provenance.PAIR_OVERRIDE
                ),
                insulation_type=EffectiveValue(
                    value=InsulationType.BASIC, provenance=Provenance.PAIR_OVERRIDE
                ),
                field_condition=EffectiveValue(
                    value=FieldCondition.INHOMOGENEOUS,
                    provenance=Provenance.PROJECT_DEFAULT,
                ),
                electrode_radius_mm=EffectiveValue(
                    value=None, provenance=Provenance.PROJECT_DEFAULT
                ),
                altitude_m=EffectiveValue(value=Decimal(0), provenance=Provenance.PROJECT_DEFAULT),
                pollution_degree=EffectiveValue(value=2, provenance=Provenance.PROJECT_DEFAULT),
                construction_type=EffectiveValue(
                    value=ConstructionType.OTHER, provenance=Provenance.PROJECT_DEFAULT
                ),
                cti_or_material_group=EffectiveValue(
                    value="I", provenance=Provenance.PROJECT_DEFAULT
                ),
                conventional_construction_assumptions=EffectiveValue(
                    value=(), provenance=Provenance.PROJECT_DEFAULT
                ),
            ),
            synthetic_rules,
        )
        return result

    return make


def _ids(*results) -> tuple[str, ...]:
    return tuple(str(result.pair_id) for result in results)


def test_identical_results_group_and_different_effective_inputs_do_not(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2)
    different = result_factory(pair_id=3, rms_v="499")

    groups = group_results((first, second, different), ())

    assert [group.pair_ids for group in groups] == [_ids(first, second), _ids(different)]


def test_signature_is_stable_and_excludes_pair_identity(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2)

    assert calculation_signature(first) == calculation_signature(second)
    assert len(calculation_signature(first)) == 64


def test_default_advisories_are_empty_and_immutable(result_factory) -> None:
    result = result_factory(pair_id=1)

    assert result.warnings == result.trace.warnings == ()
    assert result.verification_requirements == result.trace.verification_requirements == ()
    with pytest.raises(ValidationError):
        result.warnings = ()


def test_warning_only_difference_changes_signature(result_factory) -> None:
    result = result_factory(pair_id=1)
    changed = result.model_copy(
        update={
            "warnings": (
                CalculationWarning(code="TEST_WARNING", message="Synthetic warning."),
            )
        }
    )

    assert calculation_signature(changed) != calculation_signature(result)


def test_verification_only_difference_changes_signature(result_factory) -> None:
    result = result_factory(pair_id=1)
    changed = result.model_copy(
        update={
            "verification_requirements": (
                VerificationRequirement(code="TEST_VERIFICATION", message="Synthetic check."),
            )
        }
    )

    assert calculation_signature(changed) != calculation_signature(result)


def test_result_rejects_advisories_that_do_not_match_its_trace(result_factory) -> None:
    result = result_factory(pair_id=1)
    document = result.model_dump(mode="python")
    document["warnings"] = (CalculationWarning(code="TEST_WARNING", message="Synthetic warning."),)

    with pytest.raises(ValidationError, match="warnings must match"):
        PairResult.model_validate(document)


def test_signature_includes_effective_input_provenance_and_not_trace_reconstruction(result_factory) -> None:
    result = result_factory(pair_id=1)
    changed_provenance = result.model_copy(
        update={
            "effective_inputs": result.effective_inputs.model_copy(
                update={
                    "frequency_hz": result.effective_inputs.frequency_hz.model_copy(
                        update={"provenance": Provenance.PAIR_OVERRIDE}
                    )
                }
            )
        }
    )

    assert changed_provenance.trace == result.trace
    assert calculation_signature(changed_provenance) != calculation_signature(result)


def test_signature_normalizes_equivalent_decimal_input_text(result_factory) -> None:
    result = result_factory(pair_id=1)
    equivalent_decimal = result.model_copy(
        update={
            "effective_inputs": result.effective_inputs.model_copy(
                update={
                    "frequency_hz": result.effective_inputs.frequency_hz.model_copy(
                        update={"value": Decimal("30000.0")}
                    )
                }
            )
        }
    )

    assert calculation_signature(equivalent_decimal) == calculation_signature(result)


def test_signature_is_context_independent_for_distinct_high_precision_decimals(result_factory) -> None:
    result = result_factory(pair_id=1)
    values = (
        Decimal("1.123456789012345678901234567890123456789012345678901234567890123456789"),
        Decimal("1.123456789012345678901234567890123456789012345678901234567890123456780"),
    )
    signatures: list[tuple[str, str]] = []
    for precision in (28, 100):
        with localcontext() as context:
            context.prec = precision
            signatures.append(
                tuple(
                    calculation_signature(
                        result.model_copy(
                            update={
                                "effective_inputs": result.effective_inputs.model_copy(
                                    update={
                                        "frequency_hz": result.effective_inputs.frequency_hz.model_copy(
                                            update={"value": value}
                                        )
                                    }
                                )
                            }
                        )
                    )
                    for value in values
                )
            )

    assert signatures[0] == signatures[1]
    assert signatures[0][0] != signatures[0][1]


def test_saved_split_partitions_one_signature_in_result_display_order(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2)
    third = result_factory(pair_id=3)
    signature = calculation_signature(first)

    groups = group_results(
        (first, second, third),
        (GroupSplit(signature=signature, pair_ids=_ids(second)),),
    )

    assert [group.pair_ids for group in groups] == [_ids(first, third), _ids(second)]


def test_stale_saved_split_is_rejected(result_factory) -> None:
    result = result_factory(pair_id=1)

    with pytest.raises(GroupingError, match="stale"):
        group_results(
            (result,),
            (GroupSplit(signature=calculation_signature(result), pair_ids=(str(UUID(int=99)),)),),
        )


def test_manual_split_never_merges_different_signatures(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2, rms_v="499")
    groups = group_results((first, second), ())

    with pytest.raises(GroupingError, match="different calculation signatures"):
        merge_groups(groups, _ids(first, second))


def test_split_and_merge_keep_same_signature_groups_safe(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2)
    automatic = group_results((first, second), ())

    split = split_group(automatic, automatic[0].group_id, _ids(second))
    merged = merge_groups(split, _ids(first, second))

    assert [group.pair_ids for group in split] == [_ids(first), _ids(second)]
    assert [group.pair_ids for group in merged] == [_ids(first, second)]
    assert all(isinstance(group, CalculationGroup) for group in merged)


def test_split_and_merge_keep_interleaved_result_display_order(result_factory) -> None:
    first = result_factory(pair_id=1)
    second = result_factory(pair_id=2, rms_v="499")
    third = result_factory(pair_id=3)
    fourth = result_factory(pair_id=4, rms_v="499")
    automatic = group_results((first, second, third, fourth), ())
    first_group = next(group for group in automatic if str(third.pair_id) in group.pair_ids)

    split = split_group(automatic, first_group.group_id, _ids(third))
    merged = merge_groups(split, _ids(second, fourth))

    assert [group.pair_ids for group in split] == [_ids(first), _ids(second, fourth), _ids(third)]
    assert [group.pair_ids for group in merged] == [_ids(first), _ids(second, fourth), _ids(third)]
