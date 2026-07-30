# ruff: noqa: FURB157

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.enums import Applicability, Provenance
from insulation_coordination.domain.project import (
    OverrideValue,
    PairCase,
    PairVoltage,
    PairVoltages,
    ProjectDefaults,
)
from insulation_coordination.project.resolver import resolve_effective_case


def test_pair_frequency_and_impulse_override_project_defaults() -> None:
    effective = resolve_effective_case(
        ProjectDefaults(frequency_hz=Decimal("50000"), impulse_v=Decimal("4000")),
        PairCase(
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            frequency_hz=OverrideValue.override(Decimal("100000")),
            impulse_v=OverrideValue.override(Decimal("6000")),
        ),
    )

    assert effective.frequency_hz.value == Decimal("100000")
    assert effective.frequency_hz.provenance is Provenance.PAIR_OVERRIDE
    assert effective.impulse_v.value == Decimal("6000")
    assert effective.impulse_v.provenance is Provenance.PAIR_OVERRIDE


def test_inherited_defaults_keep_project_default_provenance() -> None:
    effective = resolve_effective_case(
        ProjectDefaults(frequency_hz=Decimal("50000"), impulse_v=Decimal("4000")),
        PairCase(key="a::b", net_a=UUID(int=1), net_b=UUID(int=2)),
    )

    assert effective.frequency_hz.value == Decimal("50000")
    assert effective.frequency_hz.provenance is Provenance.PROJECT_DEFAULT
    assert effective.impulse_v.value == Decimal("4000")
    assert effective.impulse_v.provenance is Provenance.PROJECT_DEFAULT


def test_blank_and_justified_not_applicable_voltages_are_distinct() -> None:
    voltages = PairVoltages(
        long_term_rms_v=PairVoltage.blank(),
        steady_state_peak_v=PairVoltage.not_applicable("No steady-state path exists."),
    )

    assert voltages.long_term_rms_v.applicability is Applicability.BLANK
    assert voltages.steady_state_peak_v.applicability is Applicability.NOT_APPLICABLE
    assert voltages.steady_state_peak_v.justification == "No steady-state path exists."


def test_applicable_voltage_keeps_its_positive_value() -> None:
    voltage = PairVoltage.applicable(Decimal("560.00"))

    assert voltage.applicability is Applicability.APPLICABLE
    assert voltage.value == Decimal("560.00")


def test_applicable_voltage_and_frequency_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="greater than zero"):
        PairVoltage.applicable(Decimal("0"))
    with pytest.raises(ValidationError, match="greater than zero"):
        ProjectDefaults(frequency_hz=Decimal("0"))


def test_binary_float_engineering_inputs_raise_validation_errors() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        ProjectDefaults(frequency_hz=50.0)
    with pytest.raises(ValidationError, match="Decimal"):
        PairCase(
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            frequency_hz=OverrideValue.override(50.0),
        )
    with pytest.raises(ValidationError, match="Decimal"):
        PairVoltage.applicable(50.0)
