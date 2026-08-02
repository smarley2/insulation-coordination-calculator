from __future__ import annotations

import re
from itertools import combinations
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.quantities import DecimalValue, PositiveDecimal


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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
        elif self.applicability is Applicability.BLANK and (
            self.value is not None or self.justification
        ):
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


class RulePackageReference(FrozenModel):
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: str

    @field_validator("package_id", "version", mode="before")
    @classmethod
    def _strip_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _requires_sha256(self) -> Self:
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("Rule-package SHA-256 must be 64 lowercase hexadecimal characters")
        return self


class ProjectMetadata(FrozenModel):
    title: str
    customer: str = ""
    document_number: str = ""
    revision: str = ""
    author: str = ""
    checker: str = ""
    approver: str = ""


class GroupSplit(FrozenModel):
    """Presentation-only partition of one calculated signature."""

    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("pair_ids")
    @classmethod
    def _requires_unique_pair_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not pair_id.strip() for pair_id in value):
            raise ValueError("Group split pair IDs must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("Group split pair IDs must be unique")
        return value


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


class Project(FrozenModel):
    id: UUID
    metadata: ProjectMetadata
    application_version: str
    required_rules: RulePackageReference | None = None
    defaults: ProjectDefaults
    net_classes: tuple[NetClass, ...]
    pairs: tuple[PairCase, ...]
    group_splits: tuple[GroupSplit, ...] = ()

    @model_validator(mode="after")
    def _requires_consistent_pairs(self) -> Self:
        net_ids = [net_class.id for net_class in self.net_classes]
        net_names = [net_class.name for net_class in self.net_classes]
        if len(net_ids) != len(set(net_ids)):
            raise ValueError("Net-class IDs must be unique")
        if len(net_names) != len(set(net_names)):
            raise ValueError("Net-class names must be unique")
        pair_ids = [pair.id for pair in self.pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("Pair IDs must be unique")

        expected = {_canonical_pair_key(left, right) for left, right in combinations(net_ids, 2)}
        actual = {_canonical_pair_key(pair.net_a, pair.net_b) for pair in self.pairs}
        if any(pair.key != _canonical_pair_key(pair.net_a, pair.net_b) for pair in self.pairs):
            raise ValueError("Pair keys must be canonical")
        if len(actual) != len(self.pairs) or actual != expected:
            raise ValueError("Pairs must reconcile exactly to the net classes")
        return self

    @property
    def net_class_names(self) -> tuple[str, ...]:
        return tuple(net_class.name for net_class in self.net_classes)

    def pair_by_id(self, pair_id: UUID) -> PairCase | None:
        for pair in self.pairs:
            if pair.id == pair_id:
                return pair
        return None


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


def _canonical_pair_key(left: UUID, right: UUID) -> str:
    first, second = sorted((str(left), str(right)))
    return f"{first}::{second}"
