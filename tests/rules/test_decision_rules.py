from decimal import Decimal

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    SourceReference,
)

SOURCE = SourceReference(
    document_id="synthetic-source", standard="SYNTHETIC-1", edition="1", clause="4.2", table="T-1"
)


def _rule(
    rows: tuple[DecisionRow, ...],
    *,
    exhaustive: bool = False,
) -> DecisionRule:
    return DecisionRule(
        id="synthetic-decision",
        inputs=(
            DecisionInput(name="colour", kind="categorical", allowed_values=("red", "blue")),
            DecisionInput(name="level", kind="numeric", unit="V"),
        ),
        outputs=(
            DecisionOutput(name="protection", kind="categorical", allowed_values=("basic", "none")),
        ),
        rows=rows,
        exhaustive=exhaustive,
        source=SOURCE,
    )


def _row(colour: str, protection: str) -> DecisionRow:
    return DecisionRow(
        matchers=(Matcher(input="colour", op="equals", values=(colour,)),),
        values=(DecisionValue(name="protection", categorical=protection),),
        source=SOURCE,
    )


def test_round_trip_preserves_every_field() -> None:
    rule = _rule((_row("red", "basic"), _row("blue", "none")))
    assert DecisionRule.model_validate(rule.model_dump(mode="json")) == rule


def test_matcher_naming_an_undeclared_input_is_rejected() -> None:
    row = DecisionRow(
        matchers=(Matcher(input="shape", op="equals", values=("round",)),),
        values=(DecisionValue(name="protection", categorical="basic"),),
        source=SOURCE,
    )
    with pytest.raises(ValidationError, match="undeclared input"):
        _rule((row,))


def test_categorical_matcher_outside_allowed_values_is_rejected() -> None:
    with pytest.raises(ValidationError, match="allowed values"):
        _rule((_row("green", "basic"),))


def test_range_matcher_on_a_categorical_input_is_rejected() -> None:
    row = DecisionRow(
        matchers=(Matcher(input="colour", op="range", minimum=Decimal(0), maximum=Decimal(1)),),
        values=(DecisionValue(name="protection", categorical="basic"),),
        source=SOURCE,
    )
    with pytest.raises(ValidationError, match="numeric input"):
        _rule((row,))


@pytest.mark.parametrize(
    ("op", "values"),
    (("equals", ("100",)), ("in", ("100", "200"))),
)
def test_value_matcher_on_a_non_categorical_input_is_rejected(
    op: str, values: tuple[str, ...]
) -> None:
    # Matcher values are strings; against a numeric input the row could never fire,
    # and a non-exhaustive rule would answer "no_match" instead of failing loudly.
    row = DecisionRow(
        matchers=(Matcher(input="level", op=op, values=values),),
        values=(DecisionValue(name="protection", categorical="basic"),),
        source=SOURCE,
    )
    with pytest.raises(ValidationError, match="categorical input"):
        _rule((row,))


def test_row_missing_a_declared_output_is_rejected() -> None:
    row = DecisionRow(
        matchers=(Matcher(input="colour", op="equals", values=("red",)),),
        values=(),
        source=SOURCE,
    )
    with pytest.raises(ValidationError, match="exactly the declared outputs"):
        _rule((row,))


def test_decision_value_setting_two_value_fields_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one value"):
        DecisionValue(name="protection", categorical="basic", numeric=Decimal(1))


def test_categorical_output_outside_allowed_values_is_rejected() -> None:
    with pytest.raises(ValidationError, match="allowed values"):
        _rule((_row("red", "enhanced"),))


def test_exhaustive_rule_with_uncovered_combination_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not cover"):
        _rule((_row("red", "basic"),), exhaustive=True)


def test_exhaustive_rule_covering_every_combination_is_accepted() -> None:
    rule = _rule((_row("red", "basic"), _row("blue", "none")), exhaustive=True)
    assert len(rule.rows) == 2


def test_reference_output_survives_round_trip() -> None:
    rule = DecisionRule(
        id="synthetic-reference-decision",
        inputs=(DecisionInput(name="colour", kind="categorical", allowed_values=("red",)),),
        outputs=(DecisionOutput(name="impulse", kind="reference"),),
        rows=(
            DecisionRow(
                matchers=(Matcher(input="colour", op="equals", values=("red",)),),
                values=(DecisionValue(name="impulse", reference="synthetic-other-rule"),),
                source=SOURCE,
            ),
        ),
        exhaustive=True,
        source=SOURCE,
    )
    restored = DecisionRule.model_validate(rule.model_dump(mode="json"))
    assert restored.rows[0].values[0].reference == "synthetic-other-rule"


def test_duplicate_input_or_output_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Decision input and output names must be unique"):
        DecisionRule(
            id="synthetic-decision",
            inputs=(
                DecisionInput(name="colour", kind="categorical", allowed_values=("red", "blue")),
                DecisionInput(name="colour", kind="numeric", unit="V"),
            ),
            outputs=(
                DecisionOutput(
                    name="protection", kind="categorical", allowed_values=("basic", "none")
                ),
            ),
            rows=(_row("red", "basic"),),
            exhaustive=False,
            source=SOURCE,
        )
    with pytest.raises(ValidationError, match="Decision input and output names must be unique"):
        DecisionRule(
            id="synthetic-decision",
            inputs=(
                DecisionInput(name="colour", kind="categorical", allowed_values=("red", "blue")),
            ),
            outputs=(
                DecisionOutput(
                    name="protection", kind="categorical", allowed_values=("basic", "none")
                ),
                DecisionOutput(name="protection", kind="numeric"),
            ),
            rows=(_row("red", "basic"),),
            exhaustive=False,
            source=SOURCE,
        )


def _boolean_rule(*, include_false: bool = True, mixed: bool = False) -> DecisionRule:
    inputs = (DecisionInput(name="enabled", kind="boolean"),)
    combinations: tuple[tuple[bool, str | None, str], ...] = ((True, None, "path-a"),) + (
        ((False, None, "path-b"),) if include_false else ()
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


def test_exhaustive_rule_with_boolean_input_covers_true_and_false() -> None:
    assert len(_boolean_rule().rows) == 2


def test_exhaustive_rule_with_boolean_input_rejects_uncovered_false() -> None:
    with pytest.raises(ValidationError, match="does not cover"):
        _boolean_rule(include_false=False)


def test_exhaustive_rule_covers_boolean_and_categorical_cartesian_product() -> None:
    assert len(_boolean_rule(mixed=True).rows) == 4


def test_boolean_input_rejects_string_equals_matcher() -> None:
    with pytest.raises(ValidationError, match="boolean"):
        DecisionRule(
            id="synthetic-string-boolean",
            inputs=(DecisionInput(name="enabled", kind="boolean"),),
            outputs=(DecisionOutput(name="route", kind="categorical", allowed_values=("path-a",)),),
            rows=(
                DecisionRow(
                    matchers=(Matcher(input="enabled", op="equals", values=("true",)),),
                    values=(DecisionValue(name="route", categorical="path-a"),),
                    source=SOURCE,
                ),
            ),
            exhaustive=False,
            source=SOURCE,
        )


@pytest.mark.parametrize("boolean", (0, 1))
def test_boolean_equals_matcher_rejects_integer_declarations(boolean: int) -> None:
    with pytest.raises(ValidationError):
        Matcher(input="enabled", op="equals", boolean=boolean)


def test_decision_value_kind_mismatch_is_rejected() -> None:
    row = DecisionRow(
        matchers=(Matcher(input="colour", op="equals", values=("red",)),),
        values=(DecisionValue(name="protection", numeric=Decimal(42)),),
        source=SOURCE,
    )
    with pytest.raises(ValidationError, match="is declared.*row supplies"):
        _rule((row,))
