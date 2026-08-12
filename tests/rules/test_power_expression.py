from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    Formula,
    Literal,
    Power,
    SourceReference,
    Variable,
)
from insulation_coordination.domain.trace import Quantity
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

SOURCE = SourceReference(
    document_id="synthetic-source", standard="SYNTHETIC-1", edition="1", clause="4.2"
)


def _formula(expression: Power, unit: str = "1", precision: int = 34) -> Formula:
    return Formula(
        id="synthetic-power",
        expression=expression,
        unit=unit,
        precision=precision,
        source=SOURCE,
    )


def test_integer_power_is_exact() -> None:
    result = evaluate_formula(
        _formula(Power(base=Literal(value=Decimal(3)), numerator=2)),
        {},
        {},
    )
    assert result.value == Decimal(9)


def test_negative_exponent_inverts() -> None:
    result = evaluate_formula(
        _formula(Power(base=Literal(value=Decimal(4)), numerator=-1)),
        {},
        {},
    )
    assert result.value == Decimal("0.25")


def test_negative_exponent_on_zero_is_rejected() -> None:
    with pytest.raises(EvaluationError, match="zero base"):
        evaluate_formula(
            _formula(Power(base=Literal(value=Decimal(0)), numerator=-1)),
            {},
            {},
        )


def test_square_root_is_reproducible() -> None:
    formula = _formula(Power(base=Literal(value=Decimal(2)), numerator=1, denominator=2))
    first = evaluate_formula(formula, {}, {}).value
    second = evaluate_formula(formula, {}, {}).value
    assert first == second
    assert first * first == pytest.approx(Decimal(2), abs=Decimal("1e-30"))


def test_square_root_of_a_negative_operand_is_rejected() -> None:
    with pytest.raises(EvaluationError, match="negative operand"):
        evaluate_formula(
            _formula(Power(base=Literal(value=Decimal(-1)), numerator=1, denominator=2)),
            {},
            {},
        )


def test_declared_precision_is_honoured() -> None:
    low = evaluate_formula(
        _formula(
            Power(base=Literal(value=Decimal(2)), numerator=1, denominator=2),
            precision=16,
        ),
        {},
        {},
    ).value
    high = evaluate_formula(
        _formula(
            Power(base=Literal(value=Decimal(2)), numerator=1, denominator=2),
            precision=34,
        ),
        {},
        {},
    ).value
    assert len(low.as_tuple().digits) < len(high.as_tuple().digits)


def test_power_nested_in_power_base_has_unambiguous_substituted_trace() -> None:
    expression = Power(
        base=Power(base=Literal(value=Decimal(2)), numerator=1, denominator=2),
        numerator=2,
    )
    result = evaluate_formula(_formula(expression), {}, {})
    assert result.value == Decimal(2)
    power_steps = [step for step in result.steps if step.operation == "power"]
    outer_substituted = power_steps[-1].substituted
    # The nested power's substituted form must be parenthesised as a whole,
    # otherwise "base ^ (1/2) ^ (2/1)" reads ambiguously (left- vs
    # right-associative give different values).
    assert outer_substituted == "(2 1 ^ (1/2)) ^ (2/1)"


def test_power_over_a_variable_round_trips_and_traces() -> None:
    expression = Power(base=Variable(name="voltage"), numerator=1, denominator=2)
    assert Power.model_validate(expression.model_dump(mode="json")) == expression
    result = evaluate_formula(
        _formula(expression, unit="1"),
        {"voltage": Quantity(value=Decimal(9), unit="1")},
        {},
    )
    assert result.value == Decimal(3)
    assert any(step.operation == "power" for step in result.steps)
