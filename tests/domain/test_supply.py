from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.supply import (
    DerivedSupplyScenario,
    EarthingArrangement,
    GoverningSupplyStress,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    ReductionVerificationMethod,
    SupplyConfiguration,
    SupplyConfigurationProblemCode,
    SupplyKind,
    VerifiedImpulseOverride,
    normalized_configuration_name,
    validate_supply_configurations,
)


def _configuration(**overrides: object) -> SupplyConfiguration:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": Decimal(123),
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.III,
        "input_topology": InputTopology.DIRECT_INPUT,
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _codes(*configurations: SupplyConfiguration) -> tuple[SupplyConfigurationProblemCode, ...]:
    return tuple(problem.code for problem in validate_supply_configurations(configurations))


def test_a_complete_mains_configuration_has_no_problems() -> None:
    assert _codes(_configuration()) == ()


@pytest.mark.parametrize(
    "kind",
    [SupplyKind.AC_MAINS, SupplyKind.RECTIFIED_DC_FROM_AC_MAINS],
)
def test_an_enabled_mains_row_needs_phase_earthing_and_category(kind: SupplyKind) -> None:
    incomplete = _configuration(
        supply_kind=kind,
        phase_system=None,
        earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
        overvoltage_category=None,
        input_topology=(
            InputTopology.DIRECT_INPUT
            if kind is SupplyKind.AC_MAINS
            else InputTopology.RECTIFIED_FROM_AC
        ),
    )

    assert _codes(incomplete) == (
        SupplyConfigurationProblemCode.MISSING_PHASE_SYSTEM,
        SupplyConfigurationProblemCode.MISSING_EARTHING_ARRANGEMENT,
        SupplyConfigurationProblemCode.MISSING_OVERVOLTAGE_CATEGORY,
    )


def test_every_problem_of_every_row_is_reported_not_only_the_first() -> None:
    first = _configuration(id=UUID(int=1), name="First", phase_system=None)
    second = _configuration(id=UUID(int=2), name="Second", overvoltage_category=None)

    problems = validate_supply_configurations((first, second))

    assert [(problem.configuration_id, problem.code) for problem in problems] == [
        (UUID(int=1), SupplyConfigurationProblemCode.MISSING_PHASE_SYSTEM),
        (UUID(int=2), SupplyConfigurationProblemCode.MISSING_OVERVOLTAGE_CATEGORY),
    ]


def test_a_non_mains_row_needs_no_phase_earthing_or_category() -> None:
    non_mains = _configuration(
        supply_kind=SupplyKind.NON_MAINS_AC,
        phase_system=None,
        earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
        overvoltage_category=None,
    )

    assert _codes(non_mains) == ()


def test_a_non_mains_row_still_needs_its_kind_and_voltage() -> None:
    complete: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic non-mains",
        "supply_kind": SupplyKind.NON_MAINS_DC,
        "nominal_voltage_v": Decimal(48),
        "phase_system": None,
        "earthing_arrangement": EarthingArrangement.NOT_APPLICABLE,
        "overvoltage_category": None,
        "input_topology": InputTopology.DIRECT_INPUT,
    }
    for omitted in ("supply_kind", "nominal_voltage_v"):
        with pytest.raises(ValidationError, match="[Mm]issing"):
            SupplyConfiguration(
                **{name: value for name, value in complete.items() if name != omitted}
            )


def test_a_dc_supply_voltage_is_accepted_across_the_supported_range() -> None:
    high_voltage_dc = _configuration(
        supply_kind=SupplyKind.NON_MAINS_DC,
        nominal_voltage_v=Decimal(1500),
        phase_system=None,
        earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
        overvoltage_category=None,
    )

    assert high_voltage_dc.nominal_voltage_v == Decimal(1500)
    assert _codes(high_voltage_dc) == ()


def test_series_connected_bridges_need_the_bridge_rms_voltage() -> None:
    bridges = _configuration(
        supply_kind=SupplyKind.RECTIFIED_DC_FROM_AC_MAINS,
        input_topology=InputTopology.SERIES_CONNECTED_RECTIFIER_BRIDGES,
    )

    assert _codes(bridges) == (SupplyConfigurationProblemCode.MISSING_BRIDGE_RMS_VOLTAGE,)
    assert _codes(bridges.model_copy(update={"rectifier_bridge_rms_v": Decimal(77)})) == ()


def test_a_bridge_rms_voltage_without_series_bridges_is_refused() -> None:
    with pytest.raises(ValidationError, match="series-connected rectifier bridges"):
        _configuration(
            input_topology=InputTopology.DIRECT_INPUT,
            rectifier_bridge_rms_v=Decimal(77),
        )


def test_a_dc_supply_cannot_carry_a_phase_system() -> None:
    with pytest.raises(ValidationError, match="no phase system"):
        _configuration(
            supply_kind=SupplyKind.NON_MAINS_DC,
            phase_system=PhaseSystem.SINGLE_PHASE,
            earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
            overvoltage_category=None,
        )


def test_a_rectified_mains_supply_keeps_the_phase_system_before_its_rectifier() -> None:
    rectified = _configuration(
        supply_kind=SupplyKind.RECTIFIED_DC_FROM_AC_MAINS,
        input_topology=InputTopology.RECTIFIED_FROM_AC,
        phase_system=PhaseSystem.THREE_PHASE,
    )

    assert _codes(rectified) == ()


@pytest.mark.parametrize("name", ["", "   "])
def test_a_configuration_needs_a_name(name: str) -> None:
    with pytest.raises(ValidationError):
        _configuration(name=name)


def test_a_configuration_is_immutable() -> None:
    with pytest.raises(ValidationError):
        _configuration().enabled = False


@pytest.mark.parametrize(
    ("first", "second"),
    [("Main AC", "main ac"), ("Main  AC", "Main AC"), ("Main AC ", " Main AC")],
)
def test_names_collide_after_normalized_comparison(first: str, second: str) -> None:
    assert normalized_configuration_name(first) == normalized_configuration_name(second)
    problems = validate_supply_configurations(
        (
            _configuration(id=UUID(int=1), name=first),
            _configuration(id=UUID(int=2), name=second),
        )
    )

    assert [(problem.configuration_id, problem.code) for problem in problems] == [
        (UUID(int=2), SupplyConfigurationProblemCode.DUPLICATE_NAME)
    ]


def test_a_disabled_row_still_collides_on_its_name() -> None:
    problems = validate_supply_configurations(
        (
            _configuration(id=UUID(int=1), name="Shared"),
            _configuration(id=UUID(int=2), name="Shared", enabled=False),
        )
    )

    assert [problem.code for problem in problems] == [SupplyConfigurationProblemCode.DUPLICATE_NAME]


def test_a_disabled_row_may_stay_incomplete() -> None:
    half_filled = _configuration(
        enabled=False,
        phase_system=None,
        earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
        overvoltage_category=None,
    )

    assert _codes(half_filled) == ()


def test_no_enabled_configuration_is_a_supported_state() -> None:
    assert validate_supply_configurations(()) == ()
    assert _codes(_configuration(enabled=False)) == ()


def _scenario(**overrides: object) -> DerivedSupplyScenario:
    fields: dict[str, object] = {
        "configuration_id": UUID(int=1),
        "configuration_name": "Synthetic mains",
        "system_voltage_for_impulse_v": Decimal(123),
        "system_voltage_for_tov_v": Decimal(123),
        "source_ovc": OvervoltageCategory.III,
        "rated_impulse_v": Decimal(456),
        "temporary_overvoltage_rms_v": Decimal(234),
        "temporary_overvoltage_peak_v": Decimal(345),
    }
    fields.update(overrides)
    return DerivedSupplyScenario(**fields)


def test_a_governing_stress_names_a_scenario_it_holds() -> None:
    scenario = _scenario()
    governing = GoverningSupplyStress(
        impulse_v=Decimal(456),
        impulse_configuration_id=UUID(int=1),
        scenarios=(scenario,),
    )

    assert governing.impulse_configuration_id == scenario.configuration_id
    assert governing.tov_peak_v is None


def test_a_governing_value_without_its_configuration_is_refused() -> None:
    with pytest.raises(ValidationError, match="recorded together"):
        GoverningSupplyStress(impulse_v=Decimal(456), scenarios=(_scenario(),))


def test_a_governing_configuration_with_no_scenario_is_refused() -> None:
    with pytest.raises(ValidationError, match="no scenario"):
        GoverningSupplyStress(
            tov_peak_v=Decimal(345),
            tov_configuration_id=UUID(int=9),
            scenarios=(_scenario(),),
        )


def test_impulse_and_temporary_overvoltage_may_be_governed_separately() -> None:
    first = _scenario(configuration_id=UUID(int=1))
    second = _scenario(configuration_id=UUID(int=2))
    governing = GoverningSupplyStress(
        impulse_v=Decimal(456),
        impulse_configuration_id=UUID(int=1),
        tov_peak_v=Decimal(345),
        tov_configuration_id=UUID(int=2),
        scenarios=(first, second),
    )

    assert governing.impulse_configuration_id != governing.tov_configuration_id


def _override(**overrides: object) -> VerifiedImpulseOverride:
    fields: dict[str, object] = {
        "value_v": Decimal(200),
        "basis": ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
        "verification_method": ReductionVerificationMethod.TEST,
        "justification": "Synthetic justification",
        "evidence_reference": "SYN-001",
        "affected_location": "pair A-B",
    }
    fields.update(overrides)
    return VerifiedImpulseOverride(**fields)


def test_a_reduction_needs_evidence_a_method_and_a_location() -> None:
    reduction = _override()

    assert reduction.is_reduction
    with pytest.raises(ValidationError, match="evidence reference"):
        _override(evidence_reference="  ")
    with pytest.raises(ValidationError, match="pair or location"):
        _override(affected_location="")
    with pytest.raises(ValidationError):
        _override(verification_method=None)


def test_a_conservative_increase_needs_no_evidence_but_still_records_why() -> None:
    increase = _override(
        basis=ImpulseOverrideBasis.CONSERVATIVE_INCREASE,
        evidence_reference="",
    )

    assert not increase.is_reduction
    with pytest.raises(ValidationError, match="records why"):
        _override(basis=ImpulseOverrideBasis.CONSERVATIVE_INCREASE, justification=" ")


def test_a_high_frequency_transformer_basis_needs_its_frequency() -> None:
    with pytest.raises(ValidationError, match="needs its frequency"):
        _override(basis=ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER)

    transformer = _override(
        basis=ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER,
        transformer_frequency_hz=Decimal(50000),
    )

    assert transformer.transformer_frequency_hz == Decimal(50000)


def test_only_a_transformer_basis_carries_a_transformer_frequency() -> None:
    with pytest.raises(ValidationError, match="Only a high-frequency"):
        _override(transformer_frequency_hz=Decimal(50000))


def test_an_override_value_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _override(value_v=Decimal(0))


def test_no_generic_basis_or_method_exists() -> None:
    assert "other" not in {member.value for member in ImpulseOverrideBasis}
    assert "other" not in {member.value for member in ReductionVerificationMethod}
