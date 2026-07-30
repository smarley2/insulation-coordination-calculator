from __future__ import annotations

from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.quantities import DecimalValue, PositiveDecimal


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class NetClass(FrozenModel):
    id: UUID
    name: str = Field(min_length=1)
    description: str | None = None
    notes: str | None = None


class OverrideValue[T](FrozenModel):
    value: T | None = None
    is_override: bool = False

    @classmethod
    def inherit(cls) -> Self:
        return cls()

    @classmethod
    def override(cls, value: T) -> Self:
        return cls(value=value, is_override=True)

    @model_validator(mode="after")
    def _requires_value_when_overridden(self) -> Self:
        if self.is_override and self.value is None:
            raise ValueError("An override requires a value")
        if not self.is_override and self.value is not None:
            raise ValueError("A value requires is_override=True")
        return self


class EffectiveValue[T](FrozenModel):
    value: T
    provenance: Provenance


class PairVoltage(FrozenModel):
    applicability: Applicability = Applicability.BLANK
    value: PositiveDecimal | None = None
    justification: str | None = None

    @classmethod
    def blank(cls) -> Self:
        return cls()

    @classmethod
    def applicable(cls, value: PositiveDecimal) -> Self:
        return cls(applicability=Applicability.APPLICABLE, value=value)

    @classmethod
    def not_applicable(cls, justification: str) -> Self:
        return cls(applicability=Applicability.NOT_APPLICABLE, justification=justification)

    @model_validator(mode="after")
    def _validate_state(self) -> Self:
        if self.applicability is Applicability.APPLICABLE and self.value is None:
            raise ValueError("An applicable voltage requires a value")
        elif self.applicability is Applicability.NOT_APPLICABLE:
            if self.value is not None or not self.justification or not self.justification.strip():
                raise ValueError("A not-applicable voltage requires a justification and no value")
        elif self.applicability is Applicability.BLANK and (self.value is not None or self.justification):
            raise ValueError("Only applicable or not-applicable voltages may carry data")
        return self


class PairVoltages(FrozenModel):
    long_term_rms_v: PairVoltage = Field(default_factory=PairVoltage.blank)
    steady_state_peak_v: PairVoltage = Field(default_factory=PairVoltage.blank)
    recurring_peak_v: PairVoltage = Field(default_factory=PairVoltage.blank)
    temporary_overvoltage_peak_v: PairVoltage = Field(default_factory=PairVoltage.blank)


class ProjectDefaults(FrozenModel):
    frequency_hz: PositiveDecimal | None = None
    impulse_v: PositiveDecimal | None = None
    insulation_type: InsulationType | None = None
    field_condition: FieldCondition | None = None
    electrode_radius_mm: PositiveDecimal | None = None
    altitude_m: DecimalValue | None = None
    pollution_degree: int | None = None
    construction_type: ConstructionType | None = None
    cti_or_material_group: str | None = None
    conventional_construction_assumptions: tuple[str, ...] | None = None


class PairCase(FrozenModel):
    id: UUID = Field(default_factory=uuid4)
    key: str = Field(min_length=1)
    net_a: UUID
    net_b: UUID
    voltages: PairVoltages = Field(default_factory=PairVoltages)
    frequency_hz: OverrideValue[PositiveDecimal] = Field(default_factory=OverrideValue.inherit)
    impulse_v: OverrideValue[PositiveDecimal] = Field(default_factory=OverrideValue.inherit)
    insulation_type: OverrideValue[InsulationType] = Field(default_factory=OverrideValue.inherit)
    field_condition: OverrideValue[FieldCondition] = Field(default_factory=OverrideValue.inherit)
    electrode_radius_mm: OverrideValue[PositiveDecimal] = Field(
        default_factory=OverrideValue.inherit
    )
    altitude_m: OverrideValue[DecimalValue] = Field(default_factory=OverrideValue.inherit)
    pollution_degree: OverrideValue[int] = Field(default_factory=OverrideValue.inherit)
    construction_type: OverrideValue[ConstructionType] = Field(
        default_factory=OverrideValue.inherit
    )
    cti_or_material_group: OverrideValue[str] = Field(default_factory=OverrideValue.inherit)
    conventional_construction_assumptions: OverrideValue[tuple[str, ...]] = Field(
        default_factory=OverrideValue.inherit
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _requires_distinct_nets(self) -> Self:
        if self.net_a == self.net_b:
            raise ValueError("A pair requires two different net classes")
        return self


class EffectiveCase(FrozenModel):
    id: UUID
    key: str
    net_a: UUID
    net_b: UUID
    voltages: PairVoltages
    frequency_hz: EffectiveValue[PositiveDecimal | None]
    impulse_v: EffectiveValue[PositiveDecimal | None]
    insulation_type: EffectiveValue[InsulationType | None]
    field_condition: EffectiveValue[FieldCondition | None]
    electrode_radius_mm: EffectiveValue[PositiveDecimal | None]
    altitude_m: EffectiveValue[DecimalValue | None]
    pollution_degree: EffectiveValue[int | None]
    construction_type: EffectiveValue[ConstructionType | None]
    cti_or_material_group: EffectiveValue[str | None]
    conventional_construction_assumptions: EffectiveValue[tuple[str, ...] | None]
