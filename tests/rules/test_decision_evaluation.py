from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    SourceReference,
)
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_decision

SOURCE = SourceReference(standard="SYNTHETIC-1", edition="1", clause="4.2")
ROW_SOURCE = SOURCE.model_copy(update={"row": "synthetic row 1"})


def _rule(*, exhaustive: bool = False) -> DecisionRule:
    return DecisionRule(
        id="synthetic-decision",
        inputs=(
            DecisionInput(name="colour", kind="categorical", allowed_values=("red", "blue")),
            DecisionInput(name="level", kind="numeric", unit="V"),
        ),
        outputs=(
            DecisionOutput(name="protection", kind="categorical", allowed_values=("basic", "none")),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="colour", op="equals", values=("red",)),
                    Matcher(input="level", op="range", minimum=Decimal(0), maximum=Decimal(100)),
                ),
                values=(DecisionValue(name="protection", categorical="basic"),),
                source=ROW_SOURCE,
            ),
            DecisionRow(
                matchers=(Matcher(input="colour", op="any"),),
                values=(DecisionValue(name="protection", categorical="none"),),
                source=SOURCE,
            ),
        ),
        exhaustive=exhaustive,
        source=SOURCE,
    )


def test_first_matching_row_wins() -> None:
    result = evaluate_decision(_rule(), {"colour": "red", "level": Decimal(50)})
    assert result.status == "matched"
    assert result.matched_row == 0
    assert result.values[0].categorical == "basic"
    assert result.source == ROW_SOURCE


def test_later_row_matches_when_the_first_does_not() -> None:
    result = evaluate_decision(_rule(), {"colour": "blue", "level": Decimal(50)})
    assert result.matched_row == 1
    assert result.values[0].categorical == "none"


def test_missing_input_reports_input_required_and_never_falls_through() -> None:
    result = evaluate_decision(_rule(), {"colour": "red"})
    assert result.status == "input_required"
    assert result.missing_inputs == ("level",)
    assert result.values == ()


def test_missing_input_wins_over_a_catch_all_row() -> None:
    # The rule above has a trailing `Matcher(op="any")` row that would otherwise
    # match anything. A missing declared input must still short-circuit to
    # input_required rather than falling through to that catch-all.
    result = evaluate_decision(_rule(), {"level": Decimal(50)})
    assert result.status == "input_required"
    assert result.missing_inputs == ("colour",)
    assert result.matched_row is None
    assert result.values == ()


def test_out_of_domain_categorical_input_raises() -> None:
    with pytest.raises(EvaluationError, match="outside its allowed values"):
        evaluate_decision(_rule(), {"colour": "green", "level": Decimal(50)})


def test_numeric_input_supplied_as_text_raises() -> None:
    with pytest.raises(EvaluationError, match="numeric"):
        evaluate_decision(_rule(), {"colour": "red", "level": "fifty"})


def test_boolean_supplied_where_numeric_is_declared_raises() -> None:
    # bool is an int subclass but never a Decimal, so this must be rejected
    # the same way a string would be, not silently accepted as 0/1.
    with pytest.raises(EvaluationError, match="numeric"):
        evaluate_decision(_rule(), {"colour": "red", "level": True})


def test_no_match_on_a_non_exhaustive_rule_reports_no_match() -> None:
    rule = DecisionRule(
        id="synthetic-narrow",
        inputs=(DecisionInput(name="level", kind="numeric", unit="V"),),
        outputs=(DecisionOutput(name="protection", kind="categorical", allowed_values=("basic",)),),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="level", op="range", minimum=Decimal(0), maximum=Decimal(1)),
                ),
                values=(DecisionValue(name="protection", categorical="basic"),),
                source=SOURCE,
            ),
        ),
        exhaustive=False,
        source=SOURCE,
    )
    result = evaluate_decision(rule, {"level": Decimal(9)})
    assert result.status == "no_match"
    assert result.matched_row is None
    assert result.values == ()
