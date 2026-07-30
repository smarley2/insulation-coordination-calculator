from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Self
from typing import Literal as TypingLiteral
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic.config import ExtraValues

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue

RULE_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class RulePackageError(ValueError):
    """A rules package is malformed, unsafe, or unusable."""


class SourceReference(FrozenModel):
    standard: str = Field(min_length=1)
    edition: str = Field(min_length=1)
    clause: str | None = None
    table: str | None = None
    figure: str | None = None
    row: str | None = None
    column: str | None = None
    note: str | None = None


class SourceDocument(FrozenModel):
    standard: str = Field(min_length=1)
    edition: str = Field(min_length=1)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
        return value


class ApprovalRecord(FrozenModel):
    action: TypingLiteral["extraction", "correction", "approval"]
    actor: str = Field(min_length=1)
    recorded_at: datetime
    notes: str = ""

    @field_validator("recorded_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Approval timestamps must include a timezone")
        return value.astimezone(UTC)


class Manifest(FrozenModel):
    schema_version: int = Field(ge=1)
    package_id: UUID
    version: str = Field(min_length=1)
    importer_version: str = Field(min_length=1)
    created_at: datetime
    source_documents: tuple[SourceDocument, ...]
    approved: bool = False
    compatible: bool = False
    approval_records: tuple[ApprovalRecord, ...] = ()
    notes: str = ""

    @field_validator("created_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Creation timestamps must include a timezone")
        return value.astimezone(UTC)


class Literal(FrozenModel):
    op: TypingLiteral["literal"] = "literal"
    value: DecimalValue


class Variable(FrozenModel):
    op: TypingLiteral["variable"] = "variable"
    name: str = Field(min_length=1)


class Add(FrozenModel):
    op: TypingLiteral["add"] = "add"
    operands: tuple[Expression, ...] = Field(min_length=2)


class Multiply(FrozenModel):
    op: TypingLiteral["multiply"] = "multiply"
    operands: tuple[Expression, ...] = Field(min_length=2)


class Divide(FrozenModel):
    op: TypingLiteral["divide"] = "divide"
    numerator: Expression
    denominator: Expression


class Compare(FrozenModel):
    op: TypingLiteral["compare"] = "compare"
    comparison: TypingLiteral["lt", "le", "eq", "ne", "ge", "gt"]
    left: Expression
    right: Expression


class Select(FrozenModel):
    op: TypingLiteral["select"] = "select"
    condition: Expression
    if_true: Expression
    if_false: Expression


class Minimum(FrozenModel):
    op: TypingLiteral["minimum"] = "minimum"
    operands: tuple[Expression, ...] = Field(min_length=1)


class Maximum(FrozenModel):
    op: TypingLiteral["maximum"] = "maximum"
    operands: tuple[Expression, ...] = Field(min_length=1)


class Round(FrozenModel):
    op: TypingLiteral["round"] = "round"
    value: Expression
    places: int
    mode: TypingLiteral[
        "ROUND_CEILING",
        "ROUND_DOWN",
        "ROUND_FLOOR",
        "ROUND_HALF_DOWN",
        "ROUND_HALF_EVEN",
        "ROUND_HALF_UP",
        "ROUND_UP",
    ]


class Lookup(FrozenModel):
    op: TypingLiteral["lookup"] = "lookup"
    table_id: str = Field(min_length=1)
    row: Expression
    column: Expression


class LinearInterpolate(FrozenModel):
    op: TypingLiteral["linear_interpolate"] = "linear_interpolate"
    table_id: str = Field(min_length=1)
    x: Expression


Expression = Annotated[
    Literal
    | Variable
    | Add
    | Multiply
    | Divide
    | Compare
    | Select
    | Minimum
    | Maximum
    | Round
    | Lookup
    | LinearInterpolate,
    Field(discriminator="op"),
]

for _recursive_node in (
    Add,
    Multiply,
    Divide,
    Compare,
    Select,
    Minimum,
    Maximum,
    Round,
    Lookup,
    LinearInterpolate,
):
    _recursive_node.model_rebuild(_types_namespace={"Expression": Expression})


class Parameter(FrozenModel):
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Parameter minimum must not exceed maximum")
        return self


class ParameterSet(FrozenModel):
    id: str = Field(min_length=1)
    parameters: tuple[Parameter, ...]
    source: SourceReference | None = None


class SupportedRange(FrozenModel):
    variable: str = Field(min_length=1)
    minimum: DecimalValue
    maximum: DecimalValue
    unit: str = Field(min_length=1)
    source: SourceReference

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("Supported-range minimum must not exceed maximum")
        return self


class TableAxis(FrozenModel):
    id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    values: tuple[DecimalValue, ...] = Field(min_length=1)


class TableCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    value: DecimalValue
    unit: str = Field(min_length=1)
    source: SourceReference


class Table(FrozenModel):
    id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    row_axis: TableAxis
    column_axis: TableAxis
    cells: tuple[TableCell, ...]
    supported_ranges: tuple[SupportedRange, ...] = ()
    interpolation: TypingLiteral["none", "linear"] = "none"
    rounding_places: int | None = None
    source: SourceReference


class Formula(FrozenModel):
    id: str = Field(min_length=1)
    expression: Expression
    unit: str = Field(min_length=1)
    parameter_sets: tuple[ParameterSet, ...] = ()
    supported_ranges: tuple[SupportedRange, ...] = ()
    latex: str = ""
    applicability: str = ""
    source: SourceReference


class CompatibilityMapping(FrozenModel):
    id: str = Field(min_length=1)
    source_rule_id: str = Field(min_length=1)
    target_rule_id: str = Field(min_length=1)
    approved: bool = False
    source: SourceReference
    notes: str = ""


class RulePackage(FrozenModel):
    manifest: Manifest
    tables: tuple[Table, ...]
    formulas: tuple[Formula, ...]
    mappings: tuple[CompatibilityMapping, ...]
    checksums: dict[str, str] = Field(default_factory=dict)
    package_sha256: str | None = Field(default=None, exclude=True)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        try:
            return super().model_validate(
                obj,
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            if any(item["type"] == "union_tag_invalid" for item in error.errors()):
                raise RulePackageError(f"unknown operator: {error}") from error
            raise RulePackageError(f"invalid rule package: {error}") from error


class DraftRulePackage(RulePackage):
    @model_validator(mode="after")
    def _must_remain_unapproved(self) -> Self:
        if self.manifest.approved:
            raise ValueError("A draft rule package cannot be approved")
        return self
