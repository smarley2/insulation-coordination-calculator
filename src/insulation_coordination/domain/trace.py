from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import field_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import Identifier, SourceReference


class Quantity(FrozenModel):
    value: DecimalValue
    unit: Identifier

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Quantity values must be finite")
        return value


class CalculationWarning(FrozenModel):
    """Something a reader must be told about a result that was still produced.

    Lives beside :class:`TraceStep` rather than in the clearance engine that first raised
    one, because a warning is part of what a derivation reports and the derivations that
    report one are spread across ``domain/`` and ``calculation/``. Keeping it here is what
    lets a domain model hold its own warnings without importing an engine that will, in
    turn, come to import that model.
    """

    code: str
    message: str
    semantic_rule_id: str | None = None
    source_reference: SourceReference | None = None


class TraceStep(FrozenModel):
    semantic_rule_id: Identifier
    operation: Identifier
    symbolic: str
    substituted: str
    inputs: tuple[Quantity, ...]
    source_reference: SourceReference | None
    formula_source_reference: SourceReference | None = None
    source_cells: tuple[str, ...] = ()
    cell_references: tuple[SourceReference, ...] = ()
    applicability: str = ""
    output: Quantity
    unrounded_value: DecimalValue
    rounded_value: DecimalValue | None = None
    reason: str

    @field_validator("unrounded_value", "rounded_value")
    @classmethod
    def _finite_trace_value(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("Trace values must be finite")
        return value


class EvaluatedValue(FrozenModel):
    value: DecimalValue
    unit: Identifier
    steps: tuple[TraceStep, ...]

    @field_validator("value")
    @classmethod
    def _finite_result(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Evaluated values must be finite")
        return value

    @classmethod
    def from_quantity(cls, quantity: Quantity, steps: tuple[TraceStep, ...]) -> Self:
        return cls(value=quantity.value, unit=quantity.unit, steps=steps)
