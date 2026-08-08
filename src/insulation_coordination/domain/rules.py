from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import pairwise, product
from typing import Annotated, Any, Self, cast
from typing import Literal as TypingLiteral
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic.config import ExtraValues

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue

RULE_SCHEMA_VERSION = 4
IEC_IMPORTER_VERSION = "iec-pdf-4"
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


class SourceGeometryReference(FrozenModel):
    artifact_sha256: str
    bbox: tuple[DecimalValue, DecimalValue, DecimalValue, DecimalValue] | None = None

    @field_validator("artifact_sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _ordered_bbox(self) -> Self:
        if self.bbox is not None:
            left, bottom, right, top = self.bbox
            if left >= right or bottom >= top:
                raise ValueError("bounding box coordinates must be ordered")
        return self


class SourceReference(FrozenModel):
    document_id: Identifier
    standard: Identifier
    edition: Identifier
    page: int | None = Field(default=None, ge=1, strict=True)
    clause: ReferenceText | None = None
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    row: ReferenceText | None = None
    column: ReferenceText | None = None
    geometry: SourceGeometryReference | None = None
    note: ReferenceText | None = None


class SourceDocument(FrozenModel):
    id: Identifier
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


class Power(FrozenModel):
    op: TypingLiteral["power"] = "power"
    base: Expression
    numerator: int = Field(strict=True)
    denominator: TypingLiteral[1, 2] = 1


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
    | TableSelect
    | Power,
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
    Power,
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


DecisionValueKind = TypingLiteral["categorical", "numeric", "boolean"]
# ponytail: a boolean input currently cannot influence row selection — `range` is
# refused, `equals`/`in` are refused, `any` ignores it, and `exhaustive=True` with a
# boolean input is refused — so all a boolean input can do is force `input_required`.
# Narrowing DecisionValueKind to drop "boolean" is a separate maintainer decision.


class DecisionInput(FrozenModel):
    name: Identifier
    kind: DecisionValueKind
    unit: Identifier | None = None
    allowed_values: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _kind_matches_declaration(self) -> Self:
        if self.kind == "categorical" and not self.allowed_values:
            raise ValueError("A categorical input must declare its allowed values")
        if self.kind != "categorical" and self.allowed_values:
            raise ValueError("Only a categorical input may declare allowed values")
        if self.kind == "numeric" and self.unit is None:
            raise ValueError("A numeric input must declare a unit")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ValueError("Allowed values must be unique")
        return self


class DecisionOutput(FrozenModel):
    name: Identifier
    kind: DecisionValueKind | TypingLiteral["reference"]
    unit: Identifier | None = None
    allowed_values: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _kind_matches_declaration(self) -> Self:
        if self.kind == "categorical" and not self.allowed_values:
            raise ValueError("A categorical output must declare its allowed values")
        if self.kind != "categorical" and self.allowed_values:
            raise ValueError("Only a categorical output may declare allowed values")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ValueError("Allowed values must be unique")
        return self


class Matcher(FrozenModel):
    input: Identifier
    op: TypingLiteral["any", "equals", "in", "range"]
    values: tuple[Identifier, ...] = ()
    boolean: bool | None = None
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    @model_validator(mode="after")
    def _operands_match_operator(self) -> Self:
        if self.op == "equals" and self.boolean is not None:
            if self.values or self.minimum is not None or self.maximum is not None:
                raise ValueError("A boolean equals matcher uses only boolean")
        elif self.boolean is not None:
            raise ValueError("Only equals may declare boolean")
        if self.op in ("equals", "in") and not self.values and self.boolean is None:
            raise ValueError(f"A {self.op} matcher must declare values")
        if self.op == "equals" and self.boolean is None and len(self.values) != 1:
            raise ValueError("An equals matcher must declare exactly one value")
        if self.op in ("any", "range") and self.values:
            raise ValueError(f"A {self.op} matcher must not declare values")
        if self.op == "range":
            if self.minimum is None and self.maximum is None:
                raise ValueError("A range matcher must declare a bound")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("Range matcher minimum must not exceed maximum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError(f"A {self.op} matcher must not declare bounds")
        return self


class DecisionValue(FrozenModel):
    name: Identifier
    categorical: Identifier | None = None
    numeric: DecimalValue | None = None
    boolean: bool | None = None
    reference: Identifier | None = None
    unit: Identifier | None = None

    @model_validator(mode="after")
    def _exactly_one_value(self) -> Self:
        declared = tuple(
            value
            for value in (self.categorical, self.numeric, self.boolean, self.reference)
            if value is not None
        )
        if len(declared) != 1:
            raise ValueError("A decision value must declare exactly one value field")
        if self.unit is not None and self.numeric is None:
            raise ValueError("Only a numeric decision value may declare a unit")
        return self

    @property
    def kind(self) -> str:
        if self.categorical is not None:
            return "categorical"
        if self.numeric is not None:
            return "numeric"
        if self.boolean is not None:
            return "boolean"
        return "reference"


class DecisionRow(FrozenModel):
    matchers: tuple[Matcher, ...]
    values: tuple[DecisionValue, ...]
    source: SourceReference
    notes: NotesText = ""

    @model_validator(mode="after")
    def _unique_targets(self) -> Self:
        inputs = tuple(matcher.input for matcher in self.matchers)
        if len(set(inputs)) != len(inputs):
            raise ValueError("A decision row must match each input at most once")
        names = tuple(value.name for value in self.values)
        if len(set(names)) != len(names):
            raise ValueError("A decision row must set each output at most once")
        return self


class DecisionRule(FrozenModel):
    """A decision rule that maps inputs to outputs.

    Rows are ordered, and decision evaluation uses first-match-wins semantics:
    the first row whose matchers are satisfied determines the outputs.
    Row order mirrors the order in which the source standard states its exceptions.
    """

    id: Identifier
    inputs: tuple[DecisionInput, ...] = Field(min_length=1)
    outputs: tuple[DecisionOutput, ...] = Field(min_length=1)
    rows: tuple[DecisionRow, ...] = Field(min_length=1)
    exhaustive: bool
    applicability: ApplicabilityText = ""
    source: SourceReference

    @model_validator(mode="after")
    def _rows_agree_with_declarations(self) -> Self:
        inputs = {item.name: item for item in self.inputs}
        outputs = {item.name: item for item in self.outputs}
        if len(inputs) != len(self.inputs) or len(outputs) != len(self.outputs):
            raise ValueError("Decision input and output names must be unique")
        for row in self.rows:
            for matcher in row.matchers:
                declared = inputs.get(matcher.input)
                if declared is None:
                    raise ValueError(f"Matcher targets undeclared input {matcher.input!r}")
                if matcher.op == "range" and declared.kind != "numeric":
                    raise ValueError(f"A range matcher needs a numeric input, got {declared.kind}")
                if matcher.op == "in" and declared.kind == "boolean":
                    raise ValueError("An in matcher cannot target a boolean input")
                if matcher.op == "equals" and declared.kind == "boolean":
                    if matcher.boolean is None:
                        raise ValueError("An equals matcher needs a boolean value for a boolean input")
                elif matcher.op in ("equals", "in") and declared.kind != "categorical":
                    raise ValueError(
                        f"A {matcher.op} matcher needs a categorical input, got {declared.kind}"
                    )
                if matcher.boolean is not None and declared.kind != "boolean":
                    raise ValueError(
                        f"A boolean matcher needs a boolean input, got {declared.kind}"
                    )
                if declared.kind == "categorical" and any(
                    value not in declared.allowed_values for value in matcher.values
                ):
                    raise ValueError(
                        f"Matcher on {matcher.input!r} uses values outside its allowed values"
                    )
            if {value.name for value in row.values} != set(outputs):
                raise ValueError("Every decision row must set exactly the declared outputs")
            for value in row.values:
                declared_output = outputs[value.name]
                if value.kind != declared_output.kind:
                    raise ValueError(
                        f"Output {value.name!r} is declared {declared_output.kind}, "
                        f"row supplies {value.kind}"
                    )
                if (
                    declared_output.kind == "categorical"
                    and value.categorical not in declared_output.allowed_values
                ):
                    raise ValueError(
                        f"Output {value.name!r} uses a value outside its allowed values"
                    )
        if self.exhaustive:
            self._require_full_coverage(inputs)
        return self

    def _require_full_coverage(self, inputs: dict[str, DecisionInput]) -> None:
        decision_inputs = tuple(
            item for item in inputs.values() if item.kind in ("categorical", "boolean")
        )
        if not decision_inputs:
            return
        domains = tuple(
            item.allowed_values if item.kind == "categorical" else (False, True)
            for item in decision_inputs
        )
        for combination in product(*domains):
            assignment = dict[str, str | bool](
                zip(
                    (item.name for item in decision_inputs),
                    cast(tuple[str | bool, ...], combination),
                    strict=True,
                )
            )
            if not any(_row_admits(row, assignment) for row in self.rows):
                raise ValueError(f"An exhaustive rule does not cover {assignment}")


def _row_admits(row: DecisionRow, assignment: dict[str, str | bool]) -> bool:
    for matcher in row.matchers:
        value = assignment.get(matcher.input)
        if value is None:
            continue
        if matcher.op == "any":
            continue
        if matcher.op == "equals" and matcher.boolean is not None:
            if not isinstance(value, bool) or value is not matcher.boolean:
                return False
        elif matcher.op in ("equals", "in") and value not in matcher.values:
            return False
    return True


class ProcedureStep(FrozenModel):
    order: int = Field(ge=1, strict=True)
    text: ReferenceText
    source: SourceReference


def _require_consecutive(steps: tuple[ProcedureStep, ...], label: str) -> None:
    if tuple(step.order for step in steps) != tuple(range(1, len(steps) + 1)):
        raise ValueError(f"{label} must be numbered consecutively from one")


class ProcedureRule(FrozenModel):
    id: Identifier
    test_kind: Identifier
    classifications: tuple[Identifier, ...] = ()
    waveform: ReferenceText | None = None
    polarity: ReferenceText | None = None
    duration: ReferenceText | None = None
    repetitions: ReferenceText | None = None
    preparation_steps: tuple[ProcedureStep, ...] = ()
    procedure_steps: tuple[ProcedureStep, ...] = ()
    acceptance_reference: SourceReference | None = None
    applicability_rule_id: Identifier | None = None
    applicability: ApplicabilityText = ""
    source: SourceReference

    @model_validator(mode="after")
    def _steps_are_ordered(self) -> Self:
        if not self.procedure_steps:
            raise ValueError("A procedure rule needs at least one procedure step")
        _require_consecutive(self.preparation_steps, "Preparation steps")
        _require_consecutive(self.procedure_steps, "Procedure steps")
        if len(set(self.classifications)) != len(self.classifications):
            raise ValueError("Procedure classifications must be unique")
        return self


class GuidanceRule(FrozenModel):
    id: Identifier
    title: ReferenceText
    summary: NotesText
    warnings: tuple[NotesText, ...] = ()
    examples: tuple[NotesText, ...] = ()
    source: SourceReference


class RulePackage(FrozenModel):
    manifest: Manifest
    tables: tuple[Table, ...]
    formulas: tuple[Formula, ...]
    mappings: tuple[CompatibilityMapping, ...]
    decisions: tuple[DecisionRule, ...] = ()
    procedures: tuple[ProcedureRule, ...] = ()
    guidance: tuple[GuidanceRule, ...] = ()
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
