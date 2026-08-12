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

SOURCE = SourceReference(
    document_id="synthetic-source", standard="SYNTHETIC-1", edition="1", clause="4.2"
)
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


def test_exhaustive_numeric_only_rule_raises_when_no_row_matches() -> None:
    # DecisionRule's own coverage check (_require_full_coverage) only walks
    # categorical inputs; a rule with a purely numeric input constructs fine
    # under exhaustive=True even though its single row leaves values above 100
    # uncovered. The runtime raise in evaluate_decision is what catches that,
    # not construction-time validation.
    rule = DecisionRule(
        id="synthetic-exhaustive-numeric",
        inputs=(DecisionInput(name="level", kind="numeric", unit="V"),),
        outputs=(DecisionOutput(name="protection", kind="categorical", allowed_values=("basic",)),),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="level", op="range", minimum=Decimal(0), maximum=Decimal(100)),
                ),
                values=(DecisionValue(name="protection", categorical="basic"),),
                source=SOURCE,
            ),
        ),
        exhaustive=True,
        source=SOURCE,
    )
    with pytest.raises(EvaluationError, match="matched no row"):
        evaluate_decision(rule, {"level": Decimal(200)})


def _range_rule(
    *,
    minimum: Decimal | None,
    maximum: Decimal | None,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
) -> DecisionRule:
    return DecisionRule(
        id="synthetic-range",
        inputs=(DecisionInput(name="level", kind="numeric", unit="V"),),
        outputs=(DecisionOutput(name="protection", kind="categorical", allowed_values=("basic",)),),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="level",
                        op="range",
                        minimum=minimum,
                        maximum=maximum,
                        minimum_inclusive=minimum_inclusive,
                        maximum_inclusive=maximum_inclusive,
                    ),
                ),
                values=(DecisionValue(name="protection", categorical="basic"),),
                source=SOURCE,
            ),
        ),
        exhaustive=False,
        source=SOURCE,
    )


def _boolean_rule(*, mixed: bool = False) -> DecisionRule:
    inputs = (DecisionInput(name="enabled", kind="boolean"),)
    combinations: tuple[tuple[bool, str | None, str], ...] = (
        (True, None, "path-a"),
        (False, None, "path-b"),
    )
    if mixed:
        inputs += (DecisionInput(name="mode", kind="categorical", allowed_values=("x", "y")),)
        combinations = (
            (True, "x", "path-a"),
            (False, "x", "path-b"),
            (True, "y", "path-b"),
            (False, "y", "path-a"),
        )
    return DecisionRule(
        id="synthetic-boolean",
        inputs=inputs,
        outputs=(
            DecisionOutput(name="route", kind="categorical", allowed_values=("path-a", "path-b")),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(Matcher(input="enabled", op="equals", boolean=enabled),)
                + ((Matcher(input="mode", op="equals", values=(mode,)),) if mode else ()),
                values=(DecisionValue(name="route", categorical=route),),
                source=SOURCE,
            )
            for enabled, mode, route in combinations
        ),
        exhaustive=True,
        source=SOURCE,
    )


@pytest.mark.parametrize(("enabled", "route"), ((True, "path-a"), (False, "path-b")))
def test_boolean_equals_matcher_selects_the_matching_route(enabled: bool, route: str) -> None:
    assert evaluate_decision(_boolean_rule(), {"enabled": enabled}).values[0].categorical == route


def test_boolean_rule_requires_its_boolean_input() -> None:
    assert evaluate_decision(_boolean_rule(), {}).status == "input_required"


def test_mixed_boolean_and_categorical_rule_evaluates_every_combination() -> None:
    rule = _boolean_rule(mixed=True)
    assert {
        evaluate_decision(rule, {"enabled": enabled, "mode": mode}).values[0].categorical
        for enabled in (False, True)
        for mode in ("x", "y")
    } == {"path-a", "path-b"}


@pytest.mark.parametrize("enabled", (0, 1))
def test_integer_does_not_satisfy_boolean_equals_matcher(enabled: int) -> None:
    with pytest.raises(EvaluationError, match="boolean"):
        evaluate_decision(_boolean_rule(), {"enabled": enabled})


@pytest.mark.parametrize(
    ("minimum", "maximum", "minimum_inclusive", "maximum_inclusive", "level", "expect_matched"),
    (
        # Inclusive minimum: a value exactly at the bound matches.
        (Decimal(10), Decimal(20), True, True, Decimal(10), True),
        # Inclusive maximum: a value exactly at the bound matches.
        (Decimal(10), Decimal(20), True, True, Decimal(20), True),
        # Exclusive minimum: a value exactly at the bound does not match.
        (Decimal(10), Decimal(20), False, True, Decimal(10), False),
        # Exclusive maximum: a value exactly at the bound does not match.
        (Decimal(10), Decimal(20), True, False, Decimal(20), False),
        # One-sided range, minimum only: nothing caps the upper side.
        (Decimal(10), None, True, True, Decimal(1_000_000), True),
        # One-sided range, maximum only: nothing caps the lower side.
        (None, Decimal(20), True, True, Decimal(-1_000_000), True),
    ),
)
def test_range_matcher_boundaries(
    minimum: Decimal | None,
    maximum: Decimal | None,
    minimum_inclusive: bool,
    maximum_inclusive: bool,
    level: Decimal,
    expect_matched: bool,
) -> None:
    rule = _range_rule(
        minimum=minimum,
        maximum=maximum,
        minimum_inclusive=minimum_inclusive,
        maximum_inclusive=maximum_inclusive,
    )
    result = evaluate_decision(rule, {"level": level})
    assert (result.status == "matched") is expect_matched
