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

from pydantic import TypeAdapter, ValidationError

from insulation_coordination.domain.rules import (
    Add,
    Compare,
    Divide,
    Expression,
    Formula,
    LinearInterpolate,
    Literal,
    Lookup,
    Maximum,
    Minimum,
    Multiply,
    Round,
    Select,
    SourceReference,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    Variable,
)
from insulation_coordination.domain.trace import EvaluatedValue, Quantity, TraceStep

DEFAULT_DECIMAL_PRECISION = 34
_BOOLEAN_UNIT = "bool"
_DIMENSIONLESS = "1"
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


@dataclass(frozen=True)
class _Result:
    quantity: Quantity
    steps: tuple[TraceStep, ...]
    symbolic: str
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
            symbolic=" + ".join(child.symbolic for child in children),
            substituted=" + ".join(_display(child.quantity) for child in children),
            reason="sum evaluated",
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
            symbolic=r" \times ".join(child.symbolic for child in children),
            substituted=" × ".join(_display(child.quantity) for child in children),
            reason="product evaluated",
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
        return self._result(
            expression,
            quantity,
            (numerator, denominator),
            symbolic=rf"\frac{{{numerator.symbolic}}}{{{denominator.symbolic}}}",
            substituted=f"{_display(numerator.quantity)} / {_display(denominator.quantity)}",
            reason="quotient evaluated",
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
            symbolic=f"{left.symbolic} {symbol} {right.symbolic}",
            substituted=f"{_display(left.quantity)} {symbol} {_display(right.quantity)}",
            reason=f"comparison is {str(matched).lower()}",
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
            symbolic=rf"\operatorname{{select}}({condition.symbolic}, {if_true.symbolic}, {if_false.symbolic})",
            substituted=(
                f"select({_display(condition.quantity)}, "
                f"{_display(if_true.quantity)}, {_display(if_false.quantity)})"
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
        winner = next(child for child in children if child.quantity.value == target)
        quantity = _quantity(target, unit)
        operation = "min" if minimum else "max"
        reason = f"{winner.label} {'sets the minimum' if minimum else 'governs'}"
        return self._result(
            expression,
            quantity,
            children,
            symbolic=rf"\{operation}({', '.join(child.symbolic for child in children)})",
            substituted=f"{operation}({', '.join(_display(child.quantity) for child in children)})",
            reason=reason,
            label=winner.label,
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
            symbolic=rf"\operatorname{{round}}({child.symbolic}, {expression.places})",
            substituted=f"round({_display(child.quantity)}, {expression.places})",
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
        return self._result(
            expression,
            quantity,
            (row, column),
            symbolic=rf"\operatorname{{lookup}}_{{{table.id}}}(r, c)",
            substituted=(
                f"lookup {table.id} at row {_display(row.quantity)}, "
                f"column {_display(column.quantity)}"
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
            _supported_range(table, table.column_axis, column.quantity.value)
            column_index = _exact_axis_index(table.column_axis, column.quantity.value)
            column_quantity = column.quantity
            children = (x, column)
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
        substituted = (
            f"{lower.value} {table.unit} + ({_display(x.quantity)} - "
            f"{_coordinate(x0, table.row_axis.unit)})"
            f"({upper.value} {table.unit} - {lower.value} {table.unit})"
            f"/({_coordinate(x1, table.row_axis.unit)} - "
            f"{_coordinate(x0, table.row_axis.unit)}), "
            f"column {_display(column_quantity)}"
        )
        return self._result(
            expression,
            quantity,
            children,
            symbolic="y = y_0 + (x-x_0)(y_1-y_0)/(x_1-x_0)",
            substituted=substituted,
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
        reason: str,
        inputs: tuple[Quantity, ...] | None = None,
        source: SourceReference | None = None,
        source_cells: tuple[str, ...] = (),
        cell_references: tuple[SourceReference, ...] = (),
        unrounded: Decimal | None = None,
        rounded: Decimal | None = None,
        label: str | None = None,
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
            validated[table_id] = Table.model_validate(
                table.model_dump(mode="python", warnings=False)
            )
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
    if len(matches) != 1:
        state = "absent" if not matches else "ambiguous"
        raise EvaluationError(f"table {table.id!r} cell ({row}, {column}) is {state}")
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
