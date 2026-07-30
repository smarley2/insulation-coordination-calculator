from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    Add,
    Compare,
    Divide,
    Formula,
    LinearInterpolate,
    Literal,
    Lookup,
    Maximum,
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
from insulation_coordination.domain.trace import Quantity
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula


def _source(*, row: str | None = None, column: str | None = None) -> SourceReference:
    return SourceReference(
        standard="SYNTHETIC-1",
        edition="1",
        clause="4.2",
        table="T-1",
        row=row,
        column=column,
    )


@pytest.fixture
def synthetic_table() -> Table:
    return Table(
        id="creepage",
        unit="mm",
        row_axis=TableAxis(id="voltage", unit="V", values=(Decimal(100), Decimal(200))),
        column_axis=TableAxis(id="category", unit="1", values=(Decimal(1),)),
        cells=(
            TableCell(
                row=0,
                column=0,
                value=Decimal("1.00"),
                unit="mm",
                source=_source(row="100 V", column="1"),
            ),
            TableCell(
                row=1,
                column=0,
                value=Decimal("2.00"),
                unit="mm",
                source=_source(row="200 V", column="1"),
            ),
        ),
        interpolation="linear",
        rounding_places=2,
        rounding_mode="ROUND_HALF_UP",
        source=_source(),
    )


def _formula(expression: object, *, precision: int = 34, unit: str = "1") -> Formula:
    return Formula(
        id="synthetic-formula",
        expression=expression,
        unit=unit,
        precision=precision,
        latex="z = a / b",
        applicability="synthetic applicability",
        source=_source(),
    )


def test_formula_precision_controls_decimal_arithmetic() -> None:
    expression = Divide(
        numerator=Literal(value=Decimal(1)),
        denominator=Literal(value=Decimal(7)),
    )

    low = evaluate_formula(_formula(expression, precision=16), {}, {})
    high = evaluate_formula(_formula(expression, precision=34), {}, {})

    with localcontext() as context:
        context.prec = 16
        expected_low = Decimal(1) / Decimal(7)
    with localcontext() as context:
        context.prec = 34
        expected_high = Decimal(1) / Decimal(7)
    assert low.value == expected_low
    assert high.value == expected_high
    assert low.value != high.value


@pytest.mark.parametrize("precision", [15, 101])
def test_formula_rejects_precision_outside_supported_range(precision: int) -> None:
    with pytest.raises(ValidationError, match="precision"):
        _formula(Literal(value=Decimal(1)), precision=precision)


def test_linear_interpolation_records_formula_values_and_cells(
    synthetic_table: Table,
) -> None:
    result = evaluate_formula(
        LinearInterpolate(table_id="creepage", x=Variable(name="voltage")),
        {"voltage": Quantity(value=Decimal(150), unit="V")},
        {"creepage": synthetic_table},
    )

    assert result.value == Decimal("1.50")
    assert result.unit == "mm"
    assert result.steps[-1].symbolic == "y = y_0 + (x-x_0)(y_1-y_0)/(x_1-x_0)"
    assert "150 V" in result.steps[-1].substituted
    assert result.steps[-1].source_cells == ("100V", "200V")
    assert result.steps[-1].source_reference == synthetic_table.source
    assert result.steps[-1].cell_references == (
        synthetic_table.cells[0].source,
        synthetic_table.cells[1].source,
    )
    assert result.steps[-1].unrounded_value == Decimal("1.50")
    assert result.steps[-1].rounded_value == Decimal("1.50")


def test_maximum_trace_identifies_governing_candidate() -> None:
    expression = Maximum(
        operands=(
            Variable(name="functional candidate"),
            Variable(name="impulse candidate"),
        )
    )

    result = evaluate_formula(
        expression,
        {
            "functional candidate": Quantity(value=Decimal("4.2"), unit="mm"),
            "impulse candidate": Quantity(value=Decimal("5.5"), unit="mm"),
        },
        {},
    )

    assert result.value == Decimal("5.5")
    assert result.steps[-1].reason == "impulse candidate governs"


def test_every_evaluated_node_has_an_ordered_immutable_complete_trace() -> None:
    formula = _formula(
        Add(
            operands=(
                Variable(name="a"),
                Variable(name="b"),
            )
        ),
        unit="V",
    )

    result = evaluate_formula(
        formula,
        {
            "a": Quantity(value=Decimal(2), unit="V"),
            "b": Quantity(value=Decimal(3), unit="V"),
        },
        {},
    )

    assert [step.operation for step in result.steps] == ["variable", "variable", "add"]
    assert all(step.semantic_rule_id == formula.id for step in result.steps)
    assert result.steps[-1].symbolic == formula.latex
    assert result.steps[-1].substituted == "2 V + 3 V"
    assert result.steps[-1].source_reference == formula.source
    assert result.steps[-1].formula_source_reference == formula.source
    assert result.steps[-1].applicability == formula.applicability
    assert result.steps[-1].output == Quantity(value=Decimal(5), unit="V")
    assert result.steps[-1].reason == "sum evaluated"
    with pytest.raises(ValidationError, match="frozen"):
        result.steps[-1].reason = "changed"


def test_lookup_requires_exact_axis_units_and_records_selected_cell(
    synthetic_table: Table,
) -> None:
    expression = Lookup(
        table_id="creepage",
        row=Variable(name="voltage"),
        column=Literal(value=Decimal(1)),
    )

    result = evaluate_formula(
        expression,
        {"voltage": Quantity(value=Decimal(100), unit="V")},
        {"creepage": synthetic_table},
    )

    assert result.value == Decimal("1.00")
    assert result.steps[-1].source_cells == ("100V/1",)
    assert result.steps[-1].source_reference == synthetic_table.cells[0].source


@pytest.mark.parametrize(
    ("expression", "variables", "match"),
    [
        (
            Add(operands=(Variable(name="a"), Variable(name="b"))),
            {
                "a": Quantity(value=Decimal(1), unit="V"),
                "b": Quantity(value=Decimal(1), unit="mm"),
            },
            "compatible units",
        ),
        (
            Maximum(operands=(Variable(name="a"), Variable(name="b"))),
            {
                "a": Quantity(value=Decimal(1), unit="V"),
                "b": Quantity(value=Decimal(1), unit="mm"),
            },
            "compatible units",
        ),
        (
            Compare(
                comparison="eq",
                left=Variable(name="a"),
                right=Variable(name="b"),
            ),
            {
                "a": Quantity(value=Decimal(1), unit="V"),
                "b": Quantity(value=Decimal(1), unit="mm"),
            },
            "compatible units",
        ),
        (
            Select(
                condition=Literal(value=Decimal(1)),
                if_true=Variable(name="a"),
                if_false=Variable(name="b"),
            ),
            {
                "a": Quantity(value=Decimal(1), unit="V"),
                "b": Quantity(value=Decimal(1), unit="V"),
            },
            "boolean",
        ),
        (
            Select(
                condition=Compare(
                    comparison="eq",
                    left=Literal(value=Decimal(1)),
                    right=Literal(value=Decimal(1)),
                ),
                if_true=Variable(name="a"),
                if_false=Variable(name="b"),
            ),
            {
                "a": Quantity(value=Decimal(1), unit="V"),
                "b": Quantity(value=Decimal(1), unit="mm"),
            },
            "compatible units",
        ),
    ],
)
def test_compatible_units_are_enforced_for_typed_operations(
    expression: object,
    variables: dict[str, Quantity],
    match: str,
) -> None:
    with pytest.raises(EvaluationError, match=match):
        evaluate_formula(expression, variables, {})


def test_multiply_and_divide_have_deterministic_unit_semantics() -> None:
    expression = Divide(
        numerator=Multiply(operands=(Variable(name="distance"), Variable(name="voltage"))),
        denominator=Variable(name="voltage divisor"),
    )

    result = evaluate_formula(
        expression,
        {
            "distance": Quantity(value=Decimal(2), unit="mm"),
            "voltage": Quantity(value=Decimal(3), unit="V"),
            "voltage divisor": Quantity(value=Decimal(6), unit="V"),
        },
        {},
    )

    assert result.value == Decimal(1)
    assert result.unit == "mm"
    product = next(step for step in result.steps if step.operation == "multiply")
    assert product.output.unit == "V*mm"


def test_divide_rejects_zero() -> None:
    with pytest.raises(EvaluationError, match="zero"):
        evaluate_formula(
            Divide(
                numerator=Literal(value=Decimal(1)),
                denominator=Literal(value=Decimal(0)),
            ),
            {},
            {},
        )


def test_binary_float_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Decimal"):
        Quantity(value=0.1, unit="V")
    bypassed = Literal(value=Decimal(1)).model_copy(update={"value": Decimal("NaN")})
    with pytest.raises(EvaluationError, match="finite"):
        evaluate_formula(bypassed, {}, {})


@pytest.mark.parametrize(
    ("update", "match"),
    [
        ({"id": "other"}, "absent"),
        ({"interpolation": "none"}, "does not permit"),
    ],
)
def test_interpolation_rejects_absent_table_and_disallowed_interpolation(
    synthetic_table: Table,
    update: dict[str, object],
    match: str,
) -> None:
    table = synthetic_table.model_copy(update=update)
    with pytest.raises(EvaluationError, match=match):
        evaluate_formula(
            LinearInterpolate(
                table_id="creepage",
                x=Variable(name="voltage"),
            ),
            {"voltage": Quantity(value=Decimal(150), unit="V")},
            {table.id: table},
        )


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (Decimal(99), "outside"),
        (Decimal(150), "absent"),
    ],
)
def test_lookup_rejects_out_of_range_and_absent_keys(
    synthetic_table: Table,
    value: Decimal,
    match: str,
) -> None:
    with pytest.raises(EvaluationError, match=match):
        evaluate_formula(
            Lookup(
                table_id="creepage",
                row=Variable(name="voltage"),
                column=Literal(value=Decimal(1)),
            ),
            {"voltage": Quantity(value=value, unit="V")},
            {"creepage": synthetic_table},
        )


def test_lookup_rejects_ambiguous_keys(synthetic_table: Table) -> None:
    ambiguous = synthetic_table.model_copy(
        update={
            "row_axis": synthetic_table.row_axis.model_copy(
                update={"values": (Decimal(100), Decimal(100))}
            )
        }
    )

    with pytest.raises(EvaluationError, match="ambiguous"):
        evaluate_formula(
            Lookup(
                table_id="creepage",
                row=Variable(name="voltage"),
                column=Literal(value=Decimal(1)),
            ),
            {"voltage": Quantity(value=Decimal(100), unit="V")},
            {"creepage": ambiguous},
        )


def test_table_operations_reject_values_outside_declared_supported_range(
    synthetic_table: Table,
) -> None:
    supported = SupportedRange(
        variable="voltage",
        minimum=Decimal(100),
        maximum=Decimal(160),
        unit="V",
        source=_source(),
    )
    table = synthetic_table.model_copy(update={"supported_ranges": (supported,)})

    with pytest.raises(EvaluationError, match="supported range"):
        evaluate_formula(
            LinearInterpolate(
                table_id="creepage",
                x=Variable(name="voltage"),
            ),
            {"voltage": Quantity(value=Decimal(175), unit="V")},
            {"creepage": table},
        )


def test_formula_output_must_match_its_declared_unit() -> None:
    with pytest.raises(EvaluationError, match="declared unit"):
        evaluate_formula(
            _formula(Literal(value=Decimal(1)), unit="V"),
            {},
            {},
        )


def test_formula_rejects_variables_outside_its_supported_range() -> None:
    supported = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(10),
        unit="V",
        source=_source(),
    )
    formula = _formula(Variable(name="voltage"), unit="V").model_copy(
        update={"supported_ranges": (supported,)}
    )

    with pytest.raises(EvaluationError, match="supported range"):
        evaluate_formula(
            formula,
            {"voltage": Quantity(value=Decimal(20), unit="V")},
            {},
        )


def test_formula_rejects_ambiguous_supported_ranges() -> None:
    first = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(10),
        unit="V",
        source=_source(),
    )
    formula = _formula(Variable(name="voltage"), unit="V").model_copy(
        update={"supported_ranges": (first, first)}
    )

    with pytest.raises(EvaluationError, match="ambiguous"):
        evaluate_formula(
            formula,
            {"voltage": Quantity(value=Decimal(5), unit="V")},
            {},
        )


def test_formula_revalidation_normalizes_non_finite_range_errors() -> None:
    supported = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(10),
        unit="V",
        source=_source(),
    ).model_copy(update={"minimum": Decimal("NaN")})
    formula = _formula(Variable(name="voltage"), unit="V").model_copy(
        update={"supported_ranges": (supported,)}
    )

    with pytest.raises(EvaluationError, match="invalid formula"):
        evaluate_formula(
            formula,
            {"voltage": Quantity(value=Decimal(5), unit="V")},
            {},
        )


def test_select_rejects_non_boolean_truth_values() -> None:
    with pytest.raises(EvaluationError, match="zero or one"):
        evaluate_formula(
            Select(
                condition=Variable(name="condition"),
                if_true=Literal(value=Decimal(1)),
                if_false=Literal(value=Decimal(2)),
            ),
            {"condition": Quantity(value=Decimal(2), unit="bool")},
            {},
        )


def test_evaluation_does_not_inherit_ambient_decimal_context() -> None:
    formula = _formula(
        Multiply(
            operands=(
                Literal(value=Decimal(99)),
                Literal(value=Decimal(99)),
            )
        )
    )

    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.Emax = 1
        context.Emin = -1
        result = evaluate_formula(formula, {}, {})

    assert result.value == Decimal(9801)


@pytest.mark.parametrize(
    "expression",
    [
        Literal(value=Decimal(1)).model_copy(update={"op": "python"}),
        Add(operands=(Literal(value=Decimal(1)), Literal(value=Decimal(2)))).model_copy(
            update={"operands": (Literal(value=Decimal(1)),)}
        ),
        Round(
            value=Literal(value=Decimal(1)),
            places=1,
            mode="ROUND_HALF_UP",
        ).model_copy(update={"places": True}),
    ],
)
def test_evaluator_revalidates_unchecked_expression_copies(expression: object) -> None:
    with pytest.raises(EvaluationError, match="invalid expression"):
        evaluate_formula(expression, {}, {})


def test_evaluator_revalidates_unchecked_table_copies(synthetic_table: Table) -> None:
    malformed = synthetic_table.model_copy(
        update={"row_axis": synthetic_table.row_axis.model_copy(update={"values": (100, 200)})}
    )

    result = evaluate_formula(
        LinearInterpolate(table_id="creepage", x=Variable(name="voltage")),
        {"voltage": Quantity(value=Decimal(150), unit="V")},
        {"creepage": malformed},
    )

    assert result.value == Decimal("1.50")


def test_interpolation_returns_nontrivial_upper_endpoint_exactly() -> None:
    upper_x = Decimal("3.141592653589793238462643383279503")
    upper_y = Decimal("9.876543210987654321098765432109876")
    table = Table(
        id="endpoint",
        unit="mm",
        row_axis=TableAxis(
            id="x",
            unit="V",
            values=(Decimal("0.123456789012345678901234567890123"), upper_x),
        ),
        column_axis=TableAxis(id="column", unit="1", values=(Decimal(1),)),
        cells=(
            TableCell(
                row=0,
                column=0,
                value=Decimal("1.234567890123456789012345678901234"),
                unit="mm",
                source=_source(row="lower", column="1"),
            ),
            TableCell(
                row=1,
                column=0,
                value=upper_y,
                unit="mm",
                source=_source(row="upper", column="1"),
            ),
        ),
        interpolation="linear",
        source=_source(),
    )

    result = evaluate_formula(
        LinearInterpolate(table_id=table.id, x=Variable(name="x")),
        {"x": Quantity(value=upper_x, unit="V")},
        {table.id: table},
    )

    assert result.value == upper_y


def test_table_rounding_requires_places_and_mode_together(
    synthetic_table: Table,
) -> None:
    data = synthetic_table.model_dump(mode="python")
    data["rounding_mode"] = None

    with pytest.raises(ValidationError, match="together"):
        Table.model_validate(data)


def test_interpolation_uses_declared_table_rounding_mode(
    synthetic_table: Table,
) -> None:
    cells = (
        synthetic_table.cells[0],
        synthetic_table.cells[1].model_copy(update={"value": Decimal("1.01")}),
    )
    half_up = synthetic_table.model_copy(update={"cells": cells})
    half_even = half_up.model_copy(update={"rounding_mode": "ROUND_HALF_EVEN"})
    expression = LinearInterpolate(table_id="creepage", x=Variable(name="voltage"))
    variables = {"voltage": Quantity(value=Decimal(150), unit="V")}

    rounded_up = evaluate_formula(expression, variables, {"creepage": half_up})
    rounded_even = evaluate_formula(expression, variables, {"creepage": half_even})

    assert rounded_up.value == Decimal("1.01")
    assert rounded_even.value == Decimal("1.00")
    assert rounded_up.steps[-1].reason.endswith("ROUND_HALF_UP")


def test_multicolumn_interpolation_records_formula_and_bounding_cell_sources(
    synthetic_table: Table,
) -> None:
    formula = _formula(
        LinearInterpolate(
            table_id="creepage",
            x=Variable(name="voltage"),
            column=Literal(value=Decimal(2)),
        ),
        unit="mm",
    )
    column_axis = synthetic_table.column_axis.model_copy(
        update={"values": (Decimal(1), Decimal(2))}
    )
    second_column = (
        TableCell(
            row=0,
            column=1,
            value=Decimal("3.00"),
            unit="mm",
            source=_source(row="100 V", column="2"),
        ),
        TableCell(
            row=1,
            column=1,
            value=Decimal("4.00"),
            unit="mm",
            source=_source(row="200 V", column="2"),
        ),
    )
    table = synthetic_table.model_copy(
        update={
            "column_axis": column_axis,
            "cells": synthetic_table.cells + second_column,
        }
    )

    result = evaluate_formula(
        formula,
        {"voltage": Quantity(value=Decimal(150), unit="V")},
        {"creepage": table},
    )
    step = result.steps[-1]

    assert step.formula_source_reference == formula.source
    assert step.source_cells == ("100V/2", "200V/2")
    assert step.cell_references == (
        second_column[0].source,
        second_column[1].source,
    )


def test_round_records_unrounded_and_rounded_values() -> None:
    result = evaluate_formula(
        Round(
            value=Literal(value=Decimal("1.255")),
            places=2,
            mode="ROUND_HALF_UP",
        ),
        {},
        {},
    )

    step = result.steps[-1]
    assert result.value == Decimal("1.26")
    assert step.unrounded_value == Decimal("1.255")
    assert step.rounded_value == Decimal("1.26")
    assert step.reason == "rounded to 2 places using ROUND_HALF_UP"


def test_runtime_rejects_round_modes_bypassed_with_model_copy() -> None:
    expression = Round(
        value=Literal(value=Decimal("1.25")),
        places=1,
        mode="ROUND_HALF_UP",
    ).model_copy(update={"mode": "ROUND_05UP"})

    with pytest.raises(EvaluationError, match="invalid expression"):
        evaluate_formula(expression, {}, {})


@given(
    lower=st.decimals(
        min_value=Decimal(-1000),
        max_value=Decimal(1000),
        places=3,
        allow_nan=False,
        allow_infinity=False,
    ),
    delta=st.decimals(
        min_value=Decimal("0.001"),
        max_value=Decimal(1000),
        places=3,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_interpolation_returns_endpoints_exactly(
    lower: Decimal,
    delta: Decimal,
) -> None:
    upper = lower + delta
    table = Table(
        id="property-table",
        unit="mm",
        row_axis=TableAxis(id="x", unit="V", values=(Decimal(0), Decimal(1))),
        column_axis=TableAxis(id="column", unit="1", values=(Decimal(1),)),
        cells=(
            TableCell(
                row=0,
                column=0,
                value=lower,
                unit="mm",
                source=_source(row="0", column="1"),
            ),
            TableCell(
                row=1,
                column=0,
                value=upper,
                unit="mm",
                source=_source(row="1", column="1"),
            ),
        ),
        interpolation="linear",
        source=_source(),
    )
    expression = LinearInterpolate(table_id=table.id, x=Variable(name="x"))

    at_lower = evaluate_formula(
        expression,
        {"x": Quantity(value=Decimal(0), unit="V")},
        {table.id: table},
    )
    at_upper = evaluate_formula(
        expression,
        {"x": Quantity(value=Decimal(1), unit="V")},
        {table.id: table},
    )

    assert at_lower.value == lower
    assert at_upper.value == upper


@given(st.lists(st.decimals(allow_nan=False, allow_infinity=False), min_size=1, max_size=8))
def test_maximum_is_not_below_any_candidate(values: list[Decimal]) -> None:
    expression = Maximum(operands=tuple(Literal(value=value) for value in values))

    result = evaluate_formula(expression, {}, {})

    assert all(result.value >= candidate for candidate in values)


@given(
    x=st.integers(min_value=0, max_value=20),
    precision=st.integers(min_value=16, max_value=40),
)
@settings(
    max_examples=20,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
def test_archive_round_trip_does_not_change_evaluation(
    synthetic_package: object,
    tmp_path: Path,
    x: int,
    precision: int,
) -> None:
    package = synthetic_package
    table = package.tables[0]
    formula = package.formulas[0].model_copy(
        update={
            "expression": LinearInterpolate(
                table_id=table.id,
                x=Variable(name=table.row_axis.id),
                column=Literal(value=table.column_axis.values[0]),
            ),
            "unit": table.unit,
            "precision": precision,
        }
    )
    package = package.model_copy(update={"formulas": (formula,)})
    variables = {table.row_axis.id: Quantity(value=Decimal(x), unit=table.row_axis.unit)}
    before = evaluate_formula(formula, variables, {table.id: table})
    path = tmp_path / "round-trip.icrules"

    write_rule_package(path, package)
    loaded = load_rule_package(path)
    after = evaluate_formula(
        loaded.formulas[0],
        variables,
        {loaded.tables[0].id: loaded.tables[0]},
    )

    assert after == before
