from __future__ import annotations

import operator
from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import reduce
from itertools import pairwise
from typing import Literal as TypingLiteral

from pydantic import TypeAdapter, ValidationError

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import (
    Add,
    Compare,
    CurveInterpolation,
    CurvePoint,
    CurveSegment,
    DecisionRule,
    DecisionValue,
    Divide,
    Expression,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    Formula,
    Identifier,
    LinearInterpolate,
    Literal,
    Lookup,
    Matcher,
    Maximum,
    Minimum,
    Multiply,
    PiecewiseCurveRule,
    Power,
    Round,
    Select,
    SourceReference,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    TableSelect,
    Variable,
)
from insulation_coordination.domain.trace import EvaluatedValue, Quantity, TraceStep

DEFAULT_DECIMAL_PRECISION = 34
_BOOLEAN_UNIT = "bool"
_DIMENSIONLESS = "1"
_COMPARE_PRECEDENCE = 10
_ADD_PRECEDENCE = 20
_MULTIPLY_PRECEDENCE = 30
_ATOM_PRECEDENCE = 100
_ROUNDING_MODES = {
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_HALF_DOWN": ROUND_HALF_DOWN,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_UP": ROUND_UP,
}
_COMPARISONS: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "lt": operator.lt,
    "le": operator.le,
    "eq": operator.eq,
    "ne": operator.ne,
    "ge": operator.ge,
    "gt": operator.gt,
}
_EXPRESSION_ADAPTER: TypeAdapter[Expression] = TypeAdapter(Expression)


class EvaluationError(ValueError):
    """A typed declarative expression cannot be evaluated safely."""


class CurveSelectionResult(FrozenModel):
    status: TypingLiteral["matched", "no_match"]
    variant: FaultTimeVoltageVariant | None = None


class CurveEvaluationResult(FrozenModel):
    status: TypingLiteral["matched", "no_match", "out_of_domain"]
    value: DecimalValue | None = None
    unit: Identifier | None = None
    variant_id: Identifier | None = None
    source: SourceReference | None = None


@dataclass(frozen=True)
class _Result:
    quantity: Quantity
    steps: tuple[TraceStep, ...]
    symbolic: str
    substituted: str
    embedded_symbolic: str
    embedded_substituted: str
    symbolic_precedence: int
    substituted_precedence: int
    operation: str
    label: str


class _Evaluator:
    def __init__(
        self,
        variables: Mapping[str, Quantity],
        tables: Mapping[str, Table],
        formula: Formula | None,
    ) -> None:
        self.variables = variables
        self.tables = tables
        self.formula = formula

    def evaluate(self, expression: Expression) -> _Result:
        if isinstance(expression, Literal):
            return self._literal(expression)
        if isinstance(expression, Variable):
            return self._variable(expression)
        if isinstance(expression, Add):
            return self._add(expression)
        if isinstance(expression, Multiply):
            return self._multiply(expression)
        if isinstance(expression, Divide):
            return self._divide(expression)
        if isinstance(expression, Compare):
            return self._compare(expression)
        if isinstance(expression, Select):
            return self._select(expression)
        if isinstance(expression, Minimum):
            return self._extreme(expression, minimum=True)
        if isinstance(expression, Maximum):
            return self._extreme(expression, minimum=False)
        if isinstance(expression, Round):
            return self._round(expression)
        if isinstance(expression, Lookup):
            return self._lookup(expression)
        if isinstance(expression, LinearInterpolate):
            return self._interpolate(expression)
        if isinstance(expression, TableSelect):
            return self._table_select(expression)
        if isinstance(expression, Power):
            return self._power(expression)
        raise EvaluationError(f"unsupported typed expression {type(expression).__name__}")

    def _literal(self, expression: Literal) -> _Result:
        quantity = _quantity(expression.value, _DIMENSIONLESS)
        return self._result(
            expression,
            quantity,
            (),
            symbolic=str(expression.value),
            substituted=_display(quantity),
            reason="literal value",
            inputs=(quantity,),
            label=str(expression.value),
        )

    def _variable(self, expression: Variable) -> _Result:
        quantity = self.variables.get(expression.name)
        if not isinstance(quantity, Quantity):
            raise EvaluationError(f"variable {expression.name!r} is absent or not a Quantity")
        _require_finite(quantity.value, f"variable {expression.name!r}")
        return self._result(
            expression,
            quantity,
            (),
            symbolic=expression.name,
            substituted=_display(quantity),
            reason=f"input {expression.name}",
            inputs=(quantity,),
            label=expression.name,
        )

    def _add(self, expression: Add) -> _Result:
        children = tuple(self.evaluate(item) for item in expression.operands)
        _require_numeric(children)
        unit = _compatible_unit(children, "add")
        value = sum((child.quantity.value for child in children), Decimal(0))
        quantity = _quantity(value, unit)
        return self._result(
            expression,
            quantity,
            children,
            symbolic=" + ".join(
                _render_child(
                    child,
                    "symbolic",
                    _ADD_PRECEDENCE,
                    group_equal=index > 0,
                )
                for index, child in enumerate(children)
            ),
            substituted=" + ".join(
                _render_child(
                    child,
                    "substituted",
                    _ADD_PRECEDENCE,
                    group_equal=index > 0,
                )
                for index, child in enumerate(children)
            ),
            reason="sum evaluated",
            symbolic_precedence=_ADD_PRECEDENCE,
            substituted_precedence=_ADD_PRECEDENCE,
        )

    def _multiply(self, expression: Multiply) -> _Result:
        children = tuple(self.evaluate(item) for item in expression.operands)
        _require_numeric(children)
        value = reduce(operator.mul, (child.quantity.value for child in children))
        unit = _combine_units((child.quantity.unit, 1) for child in children)
        quantity = _quantity(value, unit)
        return self._result(
            expression,
            quantity,
            children,
            symbolic=r" \times ".join(
                _render_child(
                    child,
                    "symbolic",
                    _MULTIPLY_PRECEDENCE,
                    group_equal=index > 0,
                )
                for index, child in enumerate(children)
            ),
            substituted=" × ".join(
                _render_child(
                    child,
                    "substituted",
                    _MULTIPLY_PRECEDENCE,
                    group_equal=index > 0,
                )
                for index, child in enumerate(children)
            ),
            reason="product evaluated",
            symbolic_precedence=_MULTIPLY_PRECEDENCE,
            substituted_precedence=_MULTIPLY_PRECEDENCE,
        )

    def _divide(self, expression: Divide) -> _Result:
        numerator = self.evaluate(expression.numerator)
        denominator = self.evaluate(expression.denominator)
        _require_numeric((numerator, denominator))
        if denominator.quantity.value == 0:
            raise EvaluationError("division by zero")
        quantity = _quantity(
            numerator.quantity.value / denominator.quantity.value,
            _combine_units(
                (
                    (numerator.quantity.unit, 1),
                    (denominator.quantity.unit, -1),
                )
            ),
        )
        rendered_denominator = _render_child(
            denominator, "substituted", _MULTIPLY_PRECEDENCE, group_equal=True
        )
        return self._result(
            expression,
            quantity,
            (numerator, denominator),
            symbolic=(
                rf"\frac{{{numerator.embedded_symbolic}}}"
                rf"{{{denominator.embedded_symbolic}}}"
            ),
            substituted=(
                f"{_render_child(numerator, 'substituted', _MULTIPLY_PRECEDENCE)} / "
                f"{rendered_denominator}"
            ),
            reason="quotient evaluated",
            symbolic_precedence=_ATOM_PRECEDENCE,
            substituted_precedence=_MULTIPLY_PRECEDENCE,
        )

    def _compare(self, expression: Compare) -> _Result:
        left = self.evaluate(expression.left)
        right = self.evaluate(expression.right)
        _require_numeric((left, right))
        _compatible_unit((left, right), "compare")
        comparison = _COMPARISONS.get(expression.comparison)
        if comparison is None:
            raise EvaluationError(f"unsupported comparison {expression.comparison!r}")
        matched = comparison(left.quantity.value, right.quantity.value)
        quantity = _quantity(Decimal(int(matched)), _BOOLEAN_UNIT)
        symbol = {
            "lt": "<",
            "le": r"\le",
            "eq": "=",
            "ne": r"\ne",
            "ge": r"\ge",
            "gt": ">",
        }[expression.comparison]
        return self._result(
            expression,
            quantity,
            (left, right),
            symbolic=(
                f"{_render_child(left, 'symbolic', _COMPARE_PRECEDENCE, group_equal=True)} "
                f"{symbol} "
                f"{_render_child(right, 'symbolic', _COMPARE_PRECEDENCE, group_equal=True)}"
            ),
            substituted=(
                f"{_render_child(left, 'substituted', _COMPARE_PRECEDENCE, group_equal=True)} "
                f"{symbol} "
                f"{_render_child(right, 'substituted', _COMPARE_PRECEDENCE, group_equal=True)}"
            ),
            reason=f"comparison is {str(matched).lower()}",
            symbolic_precedence=_COMPARE_PRECEDENCE,
            substituted_precedence=_COMPARE_PRECEDENCE,
        )

    def _select(self, expression: Select) -> _Result:
        condition = self.evaluate(expression.condition)
        if_true = self.evaluate(expression.if_true)
        if_false = self.evaluate(expression.if_false)
        if condition.quantity.unit != _BOOLEAN_UNIT:
            raise EvaluationError("select condition must be boolean")
        if condition.quantity.value not in (Decimal(0), Decimal(1)):
            raise EvaluationError("select condition must be zero or one")
        unit = _compatible_unit((if_true, if_false), "select")
        selected = if_true if condition.quantity.value == 1 else if_false
        quantity = _quantity(selected.quantity.value, unit)
        return self._result(
            expression,
            quantity,
            (condition, if_true, if_false),
            symbolic=(
                rf"\operatorname{{select}}({condition.embedded_symbolic}, "
                f"{if_true.embedded_symbolic}, {if_false.embedded_symbolic})"
            ),
            substituted=(
                f"select({condition.embedded_substituted}, "
                f"{if_true.embedded_substituted}, {if_false.embedded_substituted})"
            ),
            reason=f"{'true' if selected is if_true else 'false'} branch selected",
            label=selected.label,
        )

    def _extreme(self, expression: Minimum | Maximum, *, minimum: bool) -> _Result:
        children = tuple(self.evaluate(item) for item in expression.operands)
        _require_numeric(children)
        unit = _compatible_unit(children, "minimum" if minimum else "maximum")
        chooser = min if minimum else max
        target = chooser(child.quantity.value for child in children)
        winner_index, winner = next(
            (index, child) for index, child in enumerate(children) if child.quantity.value == target
        )
        quantity = _quantity(target, unit)
        operation = "min" if minimum else "max"
        winner_label = (
            winner.label
            if isinstance(expression.operands[winner_index], Variable)
            else f"candidate {winner_index + 1}"
        )
        reason = f"{winner_label} {'sets the minimum' if minimum else 'governs'}"
        return self._result(
            expression,
            quantity,
            children,
            symbolic=(rf"\{operation}({', '.join(child.embedded_symbolic for child in children)})"),
            substituted=(
                f"{operation}({', '.join(child.embedded_substituted for child in children)})"
            ),
            reason=reason,
            label=winner_label,
        )

    def _round(self, expression: Round) -> _Result:
        child = self.evaluate(expression.value)
        _require_numeric((child,))
        mode = _ROUNDING_MODES.get(expression.mode)
        if mode is None:
            raise EvaluationError(f"unsupported rounding mode {expression.mode!r}")
        quantum = Decimal(1).scaleb(-expression.places)
        rounded = child.quantity.value.quantize(quantum, rounding=mode)
        quantity = _quantity(rounded, child.quantity.unit)
        return self._result(
            expression,
            quantity,
            (child,),
            symbolic=(rf"\operatorname{{round}}({child.embedded_symbolic}, {expression.places})"),
            substituted=f"round({child.embedded_substituted}, {expression.places})",
            reason=f"rounded to {expression.places} places using {expression.mode}",
            unrounded=child.quantity.value,
            rounded=rounded,
            label=child.label,
        )

    def _lookup(self, expression: Lookup) -> _Result:
        row = self.evaluate(expression.row)
        column = self.evaluate(expression.column)
        table = self._table(expression.table_id)
        _axis_input(row.quantity, table.row_axis, "row")
        _axis_input(column.quantity, table.column_axis, "column")
        _supported_range(table, table.row_axis, row.quantity.value)
        _supported_range(table, table.column_axis, column.quantity.value)
        row_index = _exact_axis_index(table.row_axis, row.quantity.value)
        column_index = _exact_axis_index(table.column_axis, column.quantity.value)
        cell = _cell(table, row_index, column_index)
        quantity = _quantity(cell.value, table.unit)
        symbolic = (
            rf"\operatorname{{lookup}}_{{{table.id}}}"
            f"({row.embedded_symbolic}, {column.embedded_symbolic})"
        )
        return self._result(
            expression,
            quantity,
            (row, column),
            symbolic=symbolic,
            substituted=(
                f"lookup {table.id} at row {row.embedded_substituted}, "
                f"column {column.embedded_substituted}"
            ),
            embedded_symbolic=symbolic,
            embedded_substituted=(
                f"lookup_{{{table.id}}}({row.embedded_substituted}, {column.embedded_substituted})"
            ),
            reason="exact table cell selected",
            source=cell.source,
            source_cells=(
                (
                    f"{_coordinate(row.quantity.value, table.row_axis.unit)}/"
                    f"{_coordinate(column.quantity.value, table.column_axis.unit)}"
                ),
            ),
            cell_references=(cell.source,),
        )

    def _interpolate(self, expression: LinearInterpolate) -> _Result:
        x = self.evaluate(expression.x)
        table = self._table(expression.table_id)
        if table.interpolation != "linear":
            raise EvaluationError(f"table {table.id!r} does not permit linear interpolation")
        _axis_input(x.quantity, table.row_axis, "interpolation")
        _supported_range(table, table.row_axis, x.quantity.value)
        column = self.evaluate(expression.column) if expression.column is not None else None
        if column is None:
            if len(table.column_axis.values) != 1:
                raise EvaluationError(
                    f"table {table.id!r} requires explicit interpolation column selection"
                )
            column_index = 0
            column_quantity = _quantity(table.column_axis.values[0], table.column_axis.unit)
            children: tuple[_Result, ...] = (x,)
        else:
            _axis_input(column.quantity, table.column_axis, "column")
            column_index = _exact_axis_index(table.column_axis, column.quantity.value)
            column_quantity = column.quantity
            children = (x, column)
        _supported_range(table, table.column_axis, column_quantity.value)
        lower_index, upper_index = _bounds(table.row_axis, x.quantity.value)
        lower = _cell(table, lower_index, column_index)
        upper = _cell(table, upper_index, column_index)
        x0 = table.row_axis.values[lower_index]
        x1 = table.row_axis.values[upper_index]
        exact_index = next(
            (
                index
                for index, coordinate in enumerate(table.row_axis.values)
                if coordinate == x.quantity.value
            ),
            None,
        )
        if exact_index is None:
            unrounded = lower.value + (
                (x.quantity.value - x0) * (upper.value - lower.value) / (x1 - x0)
            )
        else:
            unrounded = _cell(table, exact_index, column_index).value
        rounded = unrounded
        if table.rounding_places is not None and table.rounding_mode is not None:
            quantum = Decimal(1).scaleb(-table.rounding_places)
            rounded = unrounded.quantize(
                quantum,
                rounding=_ROUNDING_MODES[table.rounding_mode],
            )
        quantity = _quantity(rounded, table.unit)
        x_substituted = (
            f"({x.embedded_substituted})"
            if x.substituted_precedence < _ATOM_PRECEDENCE
            else x.embedded_substituted
        )
        column_symbolic = (
            column.embedded_symbolic if column is not None else str(column_quantity.value)
        )
        column_substituted = (
            column.embedded_substituted if column is not None else _display(column_quantity)
        )
        substituted = (
            f"{lower.value} {table.unit} + ({x_substituted} - "
            f"{_coordinate(x0, table.row_axis.unit)})"
            f"({upper.value} {table.unit} - {lower.value} {table.unit})"
            f"/({_coordinate(x1, table.row_axis.unit)} - "
            f"{_coordinate(x0, table.row_axis.unit)}), "
            f"column {column_substituted}"
        )
        return self._result(
            expression,
            quantity,
            children,
            symbolic="y = y_0 + (x-x_0)(y_1-y_0)/(x_1-x_0)",
            substituted=substituted,
            embedded_symbolic=(
                rf"\operatorname{{interpolate}}_{{{table.id}}}"
                f"({x.embedded_symbolic}, {column_symbolic})"
            ),
            embedded_substituted=(
                f"interpolate_{{{table.id}}}({x.embedded_substituted}, {column_substituted})"
            ),
            source=table.source,
            source_cells=(
                _interpolation_cell_id(table, x0, column_quantity.value),
                _interpolation_cell_id(table, x1, column_quantity.value),
            ),
            cell_references=(lower.source, upper.source),
            unrounded=unrounded,
            rounded=rounded if table.rounding_mode is not None else None,
            reason=(
                "linear interpolation evaluated"
                if table.rounding_mode is None
                else (
                    f"linear interpolation rounded to {table.rounding_places} "
                    f"places using {table.rounding_mode}"
                )
            ),
        )

    def _table_select(self, expression: TableSelect) -> _Result:
        row = self.evaluate(expression.row)
        column = self.evaluate(expression.column)
        table = self._table(expression.table_id)
        _axis_input(row.quantity, table.row_axis, "row")
        _axis_input(column.quantity, table.column_axis, "column")
        _supported_range(table, table.row_axis, row.quantity.value)
        _supported_range(table, table.column_axis, column.quantity.value)
        if (
            "linear" in (expression.row_mode, expression.column_mode)
            and table.interpolation != "linear"
        ):
            raise EvaluationError(f"table {table.id!r} does not permit linear interpolation")
        row_weights = _axis_weights(
            table.row_axis,
            row.quantity.value,
            expression.row_mode,
        )
        column_weights = _axis_weights(
            table.column_axis,
            column.quantity.value,
            expression.column_mode,
        )
        selected = tuple(
            (
                _cell(table, row_index, column_index),
                row_weight * column_weight,
                row_index,
                column_index,
            )
            for row_index, row_weight in row_weights
            for column_index, column_weight in column_weights
        )
        unrounded = sum(
            (cell.value * weight for cell, weight, _, _ in selected),
            Decimal(0),
        )
        rounded = unrounded
        if table.rounding_places is not None and table.rounding_mode is not None:
            rounded = unrounded.quantize(
                Decimal(1).scaleb(-table.rounding_places),
                rounding=_ROUNDING_MODES[table.rounding_mode],
            )
        cells = tuple(cell for cell, _, _, _ in selected)
        source_cells = tuple(
            f"{table.row_axis.labels[row_index]}/{table.column_axis.labels[column_index]}"
            for _, _, row_index, column_index in selected
        )
        mode = f"{expression.row_mode}/{expression.column_mode}"
        symbolic = (
            rf"\operatorname{{table\_select}}_{{{table.id}}}"
            f"({row.embedded_symbolic}, {column.embedded_symbolic})"
        )
        return self._result(
            expression,
            _quantity(rounded, table.unit),
            (row, column),
            symbolic=symbolic,
            substituted=(
                f"select {table.id} at row {row.embedded_substituted}, "
                f"column {column.embedded_substituted} using {mode}"
            ),
            reason=f"table selected using {mode} axis modes",
            source=cells[0].source if len(cells) == 1 else table.source,
            source_cells=source_cells,
            cell_references=tuple(cell.source for cell in cells),
            unrounded=unrounded,
            rounded=rounded if table.rounding_mode is not None else None,
        )

    def _power(self, expression: Power) -> _Result:
        child = self.evaluate(expression.base)
        _require_numeric((child,))
        # ponytail: dimensionless-only ceiling, deliberate. Carry unit^n through
        # _combine_units when denominator == 1 if a dimensioned power is ever needed.
        if child.quantity.unit != _DIMENSIONLESS:
            raise EvaluationError("power requires a dimensionless operand")
        base = child.quantity.value
        if expression.numerator < 0 and base == 0:
            raise EvaluationError("negative exponent on a zero base")
        if expression.denominator == 2 and base < 0:
            raise EvaluationError("negative operand under a square root")
        precision = (
            self.formula.precision if self.formula is not None else DEFAULT_DECIMAL_PRECISION
        )
        try:
            with localcontext(
                Context(
                    prec=precision,
                    traps=[InvalidOperation, DivisionByZero, Overflow, FloatOperation],
                )
            ):
                raised = base**expression.numerator
                value = raised.sqrt() if expression.denominator == 2 else +raised
        except DecimalException as error:
            raise EvaluationError(f"power could not be evaluated: {error}") from error
        quantity = _quantity(value, child.quantity.unit)
        exponent = (
            str(expression.numerator)
            if expression.denominator == 1
            else rf"\frac{{{expression.numerator}}}{{{expression.denominator}}}"
        )
        substituted_base = _render_child(
            child, "substituted", _MULTIPLY_PRECEDENCE, group_equal=True
        )
        return self._result(
            expression,
            quantity,
            (child,),
            symbolic=f"{{{child.embedded_symbolic}}}^{{{exponent}}}",
            substituted=(
                f"{substituted_base} ^ ({expression.numerator}/{expression.denominator})"
            ),
            reason=(
                f"raised to {expression.numerator}/{expression.denominator} "
                f"at precision {precision}"
            ),
            label=child.label,
            # The LaTeX form {base}^{exponent} is fully braced, so it is
            # self-grouping regardless of nesting: atom precedence like `_divide`'s
            # symbolic \frac{}{} form. The substituted form "base ^ (n/d)" is not
            # self-grouping around the base, so a nested Power needs the same
            # multiply-level precedence `_divide` uses for its substituted form,
            # or `2 ^ (1/2) ^ (2/1)` reads ambiguously when self-nested.
            symbolic_precedence=_ATOM_PRECEDENCE,
            substituted_precedence=_MULTIPLY_PRECEDENCE,
        )

    def _table(self, table_id: str) -> Table:
        table = self.tables.get(table_id)
        if not isinstance(table, Table) or table.id != table_id:
            raise EvaluationError(f"table {table_id!r} is absent")
        return table

    def _result(
        self,
        expression: Expression,
        quantity: Quantity,
        children: tuple[_Result, ...],
        *,
        symbolic: str,
        substituted: str,
        embedded_symbolic: str | None = None,
        embedded_substituted: str | None = None,
        reason: str,
        inputs: tuple[Quantity, ...] | None = None,
        source: SourceReference | None = None,
        source_cells: tuple[str, ...] = (),
        cell_references: tuple[SourceReference, ...] = (),
        unrounded: Decimal | None = None,
        rounded: Decimal | None = None,
        label: str | None = None,
        symbolic_precedence: int = _ATOM_PRECEDENCE,
        substituted_precedence: int = _ATOM_PRECEDENCE,
    ) -> _Result:
        step = TraceStep(
            semantic_rule_id=(
                self.formula.id if self.formula is not None else f"expression:{expression.op}"
            ),
            operation=expression.op,
            symbolic=symbolic,
            substituted=substituted,
            inputs=(inputs if inputs is not None else tuple(child.quantity for child in children)),
            source_reference=(
                source
                if source is not None
                else self.formula.source
                if self.formula is not None
                else None
            ),
            formula_source_reference=(self.formula.source if self.formula is not None else None),
            source_cells=source_cells,
            cell_references=cell_references,
            applicability=(self.formula.applicability if self.formula is not None else ""),
            output=quantity,
            unrounded_value=quantity.value if unrounded is None else unrounded,
            rounded_value=rounded,
            reason=reason,
        )
        return _Result(
            quantity=quantity,
            steps=tuple(item for child in children for item in child.steps) + (step,),
            symbolic=symbolic,
            substituted=substituted,
            embedded_symbolic=(symbolic if embedded_symbolic is None else embedded_symbolic),
            embedded_substituted=(
                substituted if embedded_substituted is None else embedded_substituted
            ),
            symbolic_precedence=symbolic_precedence,
            substituted_precedence=substituted_precedence,
            operation=expression.op,
            label=label or f"candidate {len(children) or 1}",
        )


def evaluate_formula(
    formula: Formula | Expression,
    variables: Mapping[str, Quantity],
    tables: Mapping[str, Table],
) -> EvaluatedValue:
    declared_formula, expression = _validated_formula(formula)
    validated_variables = _validated_variables(variables)
    validated_tables = _validated_tables(tables)
    precision = (
        declared_formula.precision if declared_formula is not None else DEFAULT_DECIMAL_PRECISION
    )
    if isinstance(precision, bool) or not 16 <= precision <= 100:
        raise EvaluationError("formula precision must be an integer from 16 to 100")
    if declared_formula is not None:
        _validate_formula_ranges(declared_formula, validated_variables)
    try:
        context = Context(
            prec=precision,
            rounding=ROUND_HALF_EVEN,
            Emin=-999_999,
            Emax=999_999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation, DivisionByZero, Overflow, FloatOperation],
        )
        with localcontext(context):
            result = _Evaluator(
                validated_variables,
                validated_tables,
                declared_formula,
            ).evaluate(expression)
            if declared_formula is not None and result.quantity.unit != declared_formula.unit:
                raise EvaluationError(
                    f"formula {declared_formula.id!r} produced {result.quantity.unit!r}, "
                    f"not declared unit {declared_formula.unit!r}"
                )
            steps = result.steps
            if declared_formula is not None and declared_formula.latex:
                steps = steps[:-1] + (
                    steps[-1].model_copy(update={"symbolic": declared_formula.latex}),
                )
            return EvaluatedValue.from_quantity(result.quantity, steps)
    except EvaluationError:
        raise
    except (DecimalException, OverflowError, TypeError, ValueError) as error:
        raise EvaluationError(f"invalid Decimal operation: {error}") from error


class DecisionResult(FrozenModel):
    rule_id: Identifier
    status: TypingLiteral["matched", "no_match", "input_required"]
    matched_row: int | None = None
    values: tuple[DecisionValue, ...] = ()
    missing_inputs: tuple[Identifier, ...] = ()
    source: SourceReference | None = None


def _matches(matcher: Matcher, value: Decimal | str | bool) -> bool:
    if matcher.op == "any":
        return True
    if matcher.op == "equals" and matcher.boolean is not None:
        return isinstance(value, bool) and value is matcher.boolean
    if matcher.op in ("equals", "in"):
        return value in matcher.values
    if not isinstance(value, Decimal):
        # ponytail: defensive only. evaluate_decision's own type-validation loop
        # already guarantees a range matcher's input is a Decimal before rows are
        # checked, so this branch is unreachable through that call path. Kept as
        # correct protection for a direct caller of _matches.
        raise EvaluationError(f"input {matcher.input!r} must be numeric for a range matcher")
    below_minimum = matcher.minimum is not None and (
        value < matcher.minimum or (value == matcher.minimum and not matcher.minimum_inclusive)
    )
    above_maximum = matcher.maximum is not None and (
        value > matcher.maximum or (value == matcher.maximum and not matcher.maximum_inclusive)
    )
    return not below_minimum and not above_maximum


def evaluate_decision(
    rule: DecisionRule,
    inputs: Mapping[str, Decimal | str | bool],
) -> DecisionResult:
    """Resolve one reviewed decision rule without guessing a missing input."""

    missing = tuple(item.name for item in rule.inputs if item.name not in inputs)
    if missing:
        return DecisionResult(rule_id=rule.id, status="input_required", missing_inputs=missing)
    for declared in rule.inputs:
        value = inputs[declared.name]
        if declared.kind == "categorical" and value not in declared.allowed_values:
            raise EvaluationError(f"input {declared.name!r} is outside its allowed values")
        if declared.kind == "numeric" and not isinstance(value, Decimal):
            raise EvaluationError(f"input {declared.name!r} must be numeric")
        if declared.kind == "boolean" and not isinstance(value, bool):
            raise EvaluationError(f"input {declared.name!r} must be boolean")
    for index, row in enumerate(rule.rows):
        if all(_matches(matcher, inputs[matcher.input]) for matcher in row.matchers):
            return DecisionResult(
                rule_id=rule.id,
                status="matched",
                matched_row=index,
                values=row.values,
                source=row.source,
            )
    if rule.exhaustive:
        raise EvaluationError(f"exhaustive decision rule {rule.id!r} matched no row")
    return DecisionResult(rule_id=rule.id, status="no_match")


def select_curve_variant(
    rule: PiecewiseCurveRule,
    selector: FaultTimeVoltageSelector,
) -> CurveSelectionResult:
    matches = tuple(variant for variant in rule.variants if variant.selector == selector)
    if not matches:
        return CurveSelectionResult(status="no_match")
    if len(matches) > 1:
        raise EvaluationError(f"curve rule {rule.id!r} has multiple variants for selector")
    return CurveSelectionResult(status="matched", variant=matches[0])


def evaluate_piecewise_curve(
    rule: PiecewiseCurveRule,
    selector: FaultTimeVoltageSelector,
    x: DecimalValue,
) -> CurveEvaluationResult:
    _require_finite(x, "curve input")
    selection = select_curve_variant(rule, selector)
    if selection.variant is None:
        return CurveEvaluationResult(status="no_match")
    variant = selection.variant
    if x < variant.points[0].x or x > variant.points[-1].x:
        return CurveEvaluationResult(
            status="out_of_domain",
            unit=variant.y_axis.unit,
            variant_id=variant.id,
            source=variant.source,
        )
    for point in variant.points:
        if x == point.x:
            return _curve_evaluation_result(variant, point.y)
    segment = next(
        (
            item
            for item in variant.segments
            if variant.points[item.start].x < x < variant.points[item.end].x
        ),
        None,
    )
    if segment is None:
        raise EvaluationError(f"curve variant {variant.id!r} has incomplete segment coverage")
    try:
        context = Context(
            prec=DEFAULT_DECIMAL_PRECISION,
            rounding=ROUND_HALF_EVEN,
            Emin=-999_999,
            Emax=999_999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation, DivisionByZero, Overflow, FloatOperation],
        )
        with localcontext(context):
            value = _interpolate_curve_segment(
                variant.points[segment.start],
                variant.points[segment.end],
                segment,
                x,
            )
        return _curve_evaluation_result(variant, value)
    except EvaluationError:
        raise
    except (DecimalException, OverflowError, TypeError, ValueError) as error:
        raise EvaluationError(f"invalid Decimal curve operation: {error}") from error


def _interpolate_curve_segment(
    start: CurvePoint,
    end: CurvePoint,
    segment: CurveSegment,
    x: Decimal,
) -> Decimal:
    interpolation: CurveInterpolation = segment.interpolation
    if interpolation == "constant":
        return start.y
    if interpolation == "step_before":
        return end.y
    if interpolation == "step_after":
        return start.y
    if interpolation in ("log_x", "log_log"):
        fraction = (x.ln() - start.x.ln()) / (end.x.ln() - start.x.ln())
    else:
        fraction = (x - start.x) / (end.x - start.x)
    if interpolation in ("log_y", "log_log"):
        return (start.y.ln() + fraction * (end.y.ln() - start.y.ln())).exp()
    return start.y + fraction * (end.y - start.y)


def _curve_evaluation_result(
    variant: FaultTimeVoltageVariant,
    value: Decimal,
) -> CurveEvaluationResult:
    _require_finite(value, "curve result")
    return CurveEvaluationResult(
        status="matched",
        value=value,
        unit=variant.y_axis.unit,
        variant_id=variant.id,
        source=variant.source,
    )


def _validated_formula(
    formula: Formula | Expression,
) -> tuple[Formula | None, Expression]:
    try:
        if isinstance(formula, Formula):
            validated = Formula.model_validate(formula.model_dump(mode="python", warnings=False))
            return validated, validated.expression
        if not hasattr(formula, "model_dump"):
            raise TypeError(f"expected a typed expression, got {type(formula).__name__}")
        expression = _EXPRESSION_ADAPTER.validate_python(
            formula.model_dump(mode="python", warnings=False)
        )
        return None, expression
    except (
        AttributeError,
        DecimalException,
        RecursionError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        kind = "formula" if isinstance(formula, Formula) else "expression"
        raise EvaluationError(f"invalid {kind}: {error}") from error


def _validated_variables(
    variables: Mapping[str, Quantity],
) -> dict[str, Quantity]:
    validated: dict[str, Quantity] = {}
    try:
        for name, quantity in variables.items():
            if not isinstance(name, str) or not isinstance(quantity, Quantity):
                raise TypeError("variables must map string names to Quantity values")
            validated[name] = Quantity.model_validate(
                quantity.model_dump(mode="python", warnings=False)
            )
    except (
        AttributeError,
        DecimalException,
        RecursionError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise EvaluationError(f"invalid variables: {error}") from error
    return validated


def _validated_tables(tables: Mapping[str, Table]) -> dict[str, Table]:
    validated: dict[str, Table] = {}
    try:
        for table_id, table in tables.items():
            if not isinstance(table_id, str) or not isinstance(table, Table):
                raise TypeError("tables must map string IDs to Table values")
            normalized = Table.model_validate(table.model_dump(mode="python", warnings=False))
            _validate_table_range_links(normalized)
            validated[table_id] = normalized
    except (
        AttributeError,
        DecimalException,
        RecursionError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise EvaluationError(f"invalid tables: {error}") from error
    return validated


def _validate_formula_ranges(
    formula: Formula,
    variables: Mapping[str, Quantity],
) -> None:
    ranges_by_variable: dict[str, list[SupportedRange]] = {}
    for supported in formula.supported_ranges:
        ranges_by_variable.setdefault(supported.variable, []).append(supported)
    for name, ranges in ranges_by_variable.items():
        if len(ranges) != 1:
            raise EvaluationError(
                f"formula {formula.id!r} has ambiguous supported ranges for {name!r}"
            )
        supported = ranges[0]
        quantity = variables.get(name)
        if quantity is None:
            raise EvaluationError(f"formula supported range variable {name!r} is absent")
        if quantity.unit != supported.unit:
            raise EvaluationError(
                f"formula supported range for {name!r} requires unit "
                f"{supported.unit!r}, not {quantity.unit!r}"
            )
        _require_finite(supported.minimum, f"formula range minimum for {name!r}")
        _require_finite(supported.maximum, f"formula range maximum for {name!r}")
        if not supported.minimum <= quantity.value <= supported.maximum:
            raise EvaluationError(f"variable {name!r} is outside its formula supported range")


def _require_finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise EvaluationError(f"{label} must be a finite Decimal")


def _quantity(value: Decimal, unit: str) -> Quantity:
    _require_finite(value, "calculated value")
    return Quantity(value=value, unit=unit)


def _display(quantity: Quantity) -> str:
    return f"{quantity.value} {quantity.unit}"


def _coordinate(value: Decimal, unit: str) -> str:
    return f"{value}{'' if unit == _DIMENSIONLESS else unit}"


def _interpolation_cell_id(
    table: Table,
    row_value: Decimal,
    column_value: Decimal,
) -> str:
    row = _coordinate(row_value, table.row_axis.unit)
    if len(table.column_axis.values) == 1:
        return row
    return f"{row}/{_coordinate(column_value, table.column_axis.unit)}"


def _render_child(
    child: _Result,
    field: str,
    parent_precedence: int,
    *,
    group_equal: bool = False,
) -> str:
    if field == "symbolic":
        text = child.embedded_symbolic
        precedence = child.symbolic_precedence
    elif field == "substituted":
        text = child.embedded_substituted
        precedence = child.substituted_precedence
    else:
        raise ValueError(f"unknown rendered field {field!r}")
    if precedence < parent_precedence or (group_equal and precedence == parent_precedence):
        return f"({text})"
    return text


def _require_numeric(results: tuple[_Result, ...]) -> None:
    if any(result.quantity.unit == _BOOLEAN_UNIT for result in results):
        raise EvaluationError("boolean values cannot be used in numeric operations")


def _compatible_unit(results: tuple[_Result, ...], operation: str) -> str:
    units = {result.quantity.unit for result in results}
    if len(units) != 1:
        raise EvaluationError(f"{operation} requires compatible units")
    return next(iter(units))


def _combine_units(units: Iterable[tuple[str, int]]) -> str:
    powers: dict[str, int] = {}
    for unit, direction in units:
        numerator, *denominators = unit.split("/")
        for factor in numerator.split("*"):
            if factor != _DIMENSIONLESS:
                powers[factor] = powers.get(factor, 0) + direction
        for denominator in denominators:
            for factor in denominator.split("*"):
                if factor != _DIMENSIONLESS:
                    powers[factor] = powers.get(factor, 0) - direction
    positive = sorted(factor for factor, power in powers.items() for _ in range(max(power, 0)))
    negative = sorted(factor for factor, power in powers.items() for _ in range(max(-power, 0)))
    numerator = "*".join(positive) or _DIMENSIONLESS
    return numerator if not negative else f"{numerator}/{'*'.join(negative)}"


def _axis_input(quantity: Quantity, axis: TableAxis, label: str) -> None:
    if quantity.unit != axis.unit:
        raise EvaluationError(
            f"{label} key unit {quantity.unit!r} is incompatible with axis unit {axis.unit!r}"
        )
    _require_finite(quantity.value, f"{label} key")


def _exact_axis_index(axis: TableAxis, value: Decimal) -> int:
    finite_values = tuple(item for item in axis.values if item.is_finite())
    if len(finite_values) != len(axis.values):
        raise EvaluationError(f"axis {axis.id!r} contains non-finite keys")
    matches = tuple(index for index, item in enumerate(axis.values) if item == value)
    if len(matches) > 1:
        raise EvaluationError(f"axis {axis.id!r} key {value} is ambiguous")
    if matches:
        return matches[0]
    if value < min(axis.values) or value > max(axis.values):
        raise EvaluationError(f"axis {axis.id!r} key {value} is outside its range")
    raise EvaluationError(f"axis {axis.id!r} key {value} is absent")


def _axis_weights(
    axis: TableAxis,
    value: Decimal,
    mode: str,
) -> tuple[tuple[int, Decimal], ...]:
    if mode == "exact":
        return ((_exact_axis_index(axis, value), Decimal(1)),)
    if value < axis.values[0] or value > axis.values[-1]:
        raise EvaluationError(f"axis {axis.id!r} key {value} is outside its range")
    if mode == "ceiling":
        return ((bisect_left(axis.values, value), Decimal(1)),)
    if mode != "linear":
        raise EvaluationError(f"axis {axis.id!r} has unsupported selection mode {mode!r}")
    exact = bisect_left(axis.values, value)
    if exact < len(axis.values) and axis.values[exact] == value:
        return ((exact, Decimal(1)),)
    lower, upper = _bounds(axis, value)
    span = axis.values[upper] - axis.values[lower]
    upper_weight = (value - axis.values[lower]) / span
    return (
        (lower, Decimal(1) - upper_weight),
        (upper, upper_weight),
    )


def _bounds(axis: TableAxis, value: Decimal) -> tuple[int, int]:
    values = axis.values
    if len(values) < 2:
        raise EvaluationError(f"axis {axis.id!r} has no interpolation interval")
    if any(not item.is_finite() for item in values):
        raise EvaluationError(f"axis {axis.id!r} contains non-finite keys")
    if any(left >= right for left, right in pairwise(values)):
        raise EvaluationError(f"axis {axis.id!r} has ambiguous interpolation keys")
    if value < values[0] or value > values[-1]:
        raise EvaluationError(f"axis {axis.id!r} key {value} is outside its range")
    index = bisect_left(values, value)
    if index == 0:
        return 0, 1
    if index == len(values):
        return len(values) - 2, len(values) - 1
    return index - 1, index


def _cell(table: Table, row: int, column: int) -> TableCell:
    matches = tuple(cell for cell in table.cells if cell.row == row and cell.column == column)
    if not matches:
        raise EvaluationError(f"table {table.id!r} has no cell ({row}, {column})")
    if len(matches) != 1:
        raise EvaluationError(f"table {table.id!r} cell ({row}, {column}) is ambiguous")
    cell = matches[0]
    if cell.unit != table.unit:
        raise EvaluationError(
            f"table {table.id!r} cell unit {cell.unit!r} does not match {table.unit!r}"
        )
    _require_finite(cell.value, f"table {table.id!r} cell")
    return cell


def _supported_range(table: Table, axis: TableAxis, value: Decimal) -> None:
    ranges = tuple(
        supported for supported in table.supported_ranges if supported.variable == axis.id
    )
    if not ranges:
        return
    if any(supported.unit != axis.unit for supported in ranges):
        raise EvaluationError(
            f"table {table.id!r} supported range unit does not match axis {axis.id!r}"
        )
    if not any(supported.minimum <= value <= supported.maximum for supported in ranges):
        raise EvaluationError(f"axis {axis.id!r} key {value} is outside its supported range")


def _validate_table_range_links(table: Table) -> None:
    if table.row_axis.id == table.column_axis.id:
        raise ValueError(f"table {table.id!r} must have distinct axis IDs")
    axes = {
        table.row_axis.id: table.row_axis,
        table.column_axis.id: table.column_axis,
    }
    for supported in table.supported_ranges:
        axis = axes.get(supported.variable)
        if axis is None:
            raise ValueError(
                f"table {table.id!r} supported range {supported.variable!r} "
                "is not linked to an axis"
            )
        if supported.unit != axis.unit:
            raise ValueError(
                f"table {table.id!r} supported range unit {supported.unit!r} "
                f"does not match axis {axis.id!r} unit {axis.unit!r}"
            )
        if supported.minimum < min(axis.values) or supported.maximum > max(axis.values):
            raise ValueError(
                f"table {table.id!r} supported range for {axis.id!r} exceeds the axis bounds"
            )
