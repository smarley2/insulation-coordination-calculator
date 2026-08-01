from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import pairwise
from typing import Annotated, Any, Self
from typing import Literal as TypingLiteral
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic.config import ExtraValues

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue

RULE_SCHEMA_VERSION = 2
IEC_IMPORTER_VERSION = "iec-pdf-2"
MAX_IDENTIFIER_LENGTH = 160
MAX_REFERENCE_TEXT_LENGTH = 500
MAX_NOTES_LENGTH = 2_000
MAX_LATEX_LENGTH = 4_000
MAX_APPLICABILITY_LENGTH = 1_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=MAX_IDENTIFIER_LENGTH, pattern=r"\S"),
]
ReferenceText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REFERENCE_TEXT_LENGTH, pattern=r"\S"),
]
NotesText = Annotated[str, Field(max_length=MAX_NOTES_LENGTH)]
LatexText = Annotated[str, Field(max_length=MAX_LATEX_LENGTH)]
ApplicabilityText = Annotated[str, Field(max_length=MAX_APPLICABILITY_LENGTH)]


class RulePackageError(ValueError):
    """A rules package is malformed, unsafe, or unusable."""


class SourceReference(FrozenModel):
    standard: Identifier
    edition: Identifier
    clause: ReferenceText | None = None
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    row: ReferenceText | None = None
    column: ReferenceText | None = None
    note: ReferenceText | None = None


class SourceDocument(FrozenModel):
    standard: Identifier
    edition: Identifier
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
        return value


class ApprovalRecord(FrozenModel):
    action: TypingLiteral["extraction", "correction", "approval"]
    actor: Identifier
    recorded_at: datetime
    notes: NotesText = ""

    @field_validator("recorded_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Approval timestamps must include a timezone")
        return value.astimezone(UTC)


class Manifest(FrozenModel):
    schema_version: int = Field(ge=1)
    package_id: UUID
    version: Identifier
    importer_version: Identifier
    created_at: datetime
    source_documents: tuple[SourceDocument, ...]
    approved: bool = False
    compatible: bool = False
    approval_records: tuple[ApprovalRecord, ...] = ()
    notes: NotesText = ""

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
    name: Identifier


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


RoundingMode = TypingLiteral[
    "ROUND_CEILING",
    "ROUND_DOWN",
    "ROUND_FLOOR",
    "ROUND_HALF_DOWN",
    "ROUND_HALF_EVEN",
    "ROUND_HALF_UP",
    "ROUND_UP",
]


class Round(FrozenModel):
    op: TypingLiteral["round"] = "round"
    value: Expression
    places: int = Field(strict=True)
    mode: RoundingMode


class Lookup(FrozenModel):
    op: TypingLiteral["lookup"] = "lookup"
    table_id: Identifier
    row: Expression
    column: Expression


class LinearInterpolate(FrozenModel):
    op: TypingLiteral["linear_interpolate"] = "linear_interpolate"
    table_id: Identifier
    x: Expression
    column: Expression | None = None


AxisSelectionMode = TypingLiteral["exact", "ceiling", "linear"]


class TableSelect(FrozenModel):
    op: TypingLiteral["table_select"] = "table_select"
    table_id: Identifier
    row: Expression
    column: Expression
    row_mode: AxisSelectionMode = "exact"
    column_mode: AxisSelectionMode = "exact"


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
    | LinearInterpolate
    | TableSelect,
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
    TableSelect,
):
    _recursive_node.model_rebuild(_types_namespace={"Expression": Expression})


class Parameter(FrozenModel):
    name: Identifier
    unit: Identifier
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Parameter minimum must not exceed maximum")
        return self


class ParameterSet(FrozenModel):
    id: Identifier
    parameters: tuple[Parameter, ...]
    source: SourceReference


class SupportedRange(FrozenModel):
    variable: Identifier
    minimum: DecimalValue
    maximum: DecimalValue
    unit: Identifier
    source: SourceReference

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("Supported-range minimum must not exceed maximum")
        return self


class TableAxis(FrozenModel):
    id: Identifier
    unit: Identifier
    values: tuple[DecimalValue, ...] = Field(min_length=1)
    labels: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _labels_match_ordered_values(self) -> Self:
        if len(self.labels) != len(self.values):
            raise ValueError("Axis labels must match axis values")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("Axis labels must be unique")
        if any(left >= right for left, right in pairwise(self.values)):
            raise ValueError("Axis values must be strictly increasing")
        return self


class TableCell(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    value: DecimalValue
    unit: Identifier
    source: SourceReference


class Table(FrozenModel):
    id: Identifier
    unit: Identifier
    row_axis: TableAxis
    column_axis: TableAxis
    cells: tuple[TableCell, ...] = Field(min_length=1)
    supported_ranges: tuple[SupportedRange, ...] = ()
    interpolation: TypingLiteral["none", "linear"] = "none"
    rounding_places: int | None = Field(default=None, strict=True)
    rounding_mode: RoundingMode | None = None
    source: SourceReference

    @model_validator(mode="after")
    def _complete_rounding_declaration(self) -> Self:
        if (self.rounding_places is None) != (self.rounding_mode is None):
            raise ValueError("Table rounding places and mode must be declared together")
        coordinates = {(cell.row, cell.column) for cell in self.cells}
        if len(coordinates) != len(self.cells):
            raise ValueError("Table cell coordinates must be unique")
        if any(
            cell.row >= len(self.row_axis.values) or cell.column >= len(self.column_axis.values)
            for cell in self.cells
        ):
            raise ValueError("Table cell coordinates must be inside the declared axes")
        if any(cell.unit != self.unit for cell in self.cells):
            raise ValueError("Table cell units must match the table unit")
        return self


class Formula(FrozenModel):
    id: Identifier
    expression: Expression
    unit: Identifier
    precision: int = Field(default=34, ge=16, le=100, strict=True)
    parameter_sets: tuple[ParameterSet, ...] = ()
    supported_ranges: tuple[SupportedRange, ...] = ()
    latex: LatexText = ""
    applicability: ApplicabilityText = ""
    source: SourceReference


class CompatibilityMapping(FrozenModel):
    id: Identifier
    source_rule_id: Identifier
    target_rule_id: Identifier
    approved: bool = False
    source: SourceReference
    notes: NotesText = ""


class RulePackage(FrozenModel):
    manifest: Manifest
    tables: tuple[Table, ...]
    formulas: tuple[Formula, ...]
    mappings: tuple[CompatibilityMapping, ...]
    checksums: dict[str, str] = Field(default_factory=dict)
    package_sha256: str | None = Field(default=None, exclude=True)

    @property
    def total_cell_count(self) -> int:
        return sum(len(table.cells) for table in self.tables)

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
                extra="forbid",
                from_attributes=False,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            if any(item["type"] == "union_tag_invalid" for item in error.errors()):
                raise RulePackageError(f"unknown operator: {error}") from error
            raise RulePackageError(f"invalid rule package: {error}") from error
        except (AttributeError, RecursionError, TypeError, ValueError) as error:
            raise RulePackageError(f"invalid rule package: {error}") from error


class DraftRulePackage(RulePackage):
    @model_validator(mode="after")
    def _must_remain_unapproved(self) -> Self:
        if self.manifest.approved:
            raise ValueError("A draft rule package cannot be approved")
        return self
