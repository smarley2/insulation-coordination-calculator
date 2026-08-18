"""The reinforced treatment adapter's blocking behaviour. Synthetic packages only.

Nothing here states a factor, a level or a mode of any source: every value the assertions use
comes from :mod:`tests.fixtures.synthetic_rules`, whose numbers are invented for this suite.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.calculation import clearance, creepage, reinforced_rules
from insulation_coordination.calculation.reinforced_rules import (
    CLEARANCE_ROUTE,
    CREEPAGE_ROUTE,
    READ_SEMANTIC_IDS,
    ReinforcedRuleBlockCode,
    ReinforcedTreatmentUnavailable,
    multiply_stress,
    next_preferred_level,
    read_reinforced_rules,
    reinforced_rule_blocks,
)
from insulation_coordination.domain.rules import DecisionRule, RulePackage
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from scripts.scan_licensed_content import scan_file
from tests.fixtures.synthetic_rules import (
    SYNTHETIC_REINFORCED_FACTOR,
    SYNTHETIC_REQUIREMENT_LEVELS_V,
    synthetic_part1_rule_package,
    with_stepped_reinforced_impulse,
)


@pytest.fixture
def package() -> RulePackage:
    return synthetic_part1_rule_package()


def _codes(package: RulePackage | None) -> tuple[ReinforcedRuleBlockCode, ...]:
    return tuple(block.code for block in reinforced_rule_blocks(package))


def _replace_decision(package: RulePackage, rule: DecisionRule) -> RulePackage:
    return package.model_copy(
        update={
            "decisions": tuple(rule if item.id == rule.id else item for item in package.decisions)
        }
    )


def _decision(package: RulePackage, rule_id: str) -> DecisionRule:
    return next(rule for rule in package.decisions if rule.id == rule_id)


def test_the_adapter_resolves_both_routes_and_follows_the_axis(package: RulePackage) -> None:
    rules = read_reinforced_rules(package)

    assert rules.clearance.id == CLEARANCE_ROUTE
    assert rules.creepage.id == CREEPAGE_ROUTE
    assert READ_SEMANTIC_IDS == {CLEARANCE_ROUTE, CREEPAGE_ROUTE}
    # The coordinates were followed from the rule's own reference, never named by the adapter.
    assert rules.level_axes == {ids.CLEARANCE_REQUIREMENTS: SYNTHETIC_REQUIREMENT_LEVELS_V}
    assert reinforced_rule_blocks(package) == ()


def test_no_package_blocks_and_never_returns_a_value() -> None:
    assert _codes(None) == (ReinforcedRuleBlockCode.NO_PACKAGE,)
    with pytest.raises(ReinforcedTreatmentUnavailable) as raised:
        read_reinforced_rules(None)

    assert raised.value.codes == (ReinforcedRuleBlockCode.NO_PACKAGE,)


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("approved", ReinforcedRuleBlockCode.PACKAGE_NOT_APPROVED),
        ("compatible", ReinforcedRuleBlockCode.PACKAGE_NOT_COMPATIBLE),
    ),
)
def test_an_untrusted_package_blocks_whole(
    package: RulePackage, field: str, code: ReinforcedRuleBlockCode
) -> None:
    untrusted = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={field: False})}
    )

    assert _codes(untrusted) == (code,)


def test_both_missing_routes_are_reported_in_one_pass(package: RulePackage) -> None:
    """The whole list, not the first reason: an installation is fixed by seeing all of it."""
    without = package.model_copy(update={"decisions": ()})

    assert _codes(without) == (
        ReinforcedRuleBlockCode.RULE_MISSING,
        ReinforcedRuleBlockCode.RULE_MISSING,
    )


def test_a_route_asked_by_other_inputs_blocks_on_its_shape(package: RulePackage) -> None:
    rule = _decision(package, CREEPAGE_ROUTE)
    renamed = rule.model_copy(
        update={
            "inputs": (rule.inputs[0],),
            "rows": tuple(
                row.model_copy(update={"matchers": (row.matchers[0],)}) for row in rule.rows
            ),
        }
    )

    assert _codes(_replace_decision(package, renamed)) == (
        ReinforcedRuleBlockCode.UNEXPECTED_SHAPE,
    )


def test_a_clearance_route_stating_no_axis_blocks(package: RulePackage) -> None:
    """A step has to know what it steps along, and this application will not name it."""
    rule = _decision(package, CLEARANCE_ROUTE)
    without_axis = rule.model_copy(
        update={
            "outputs": tuple(item for item in rule.outputs if item.name != "preferred_level_axis"),
            "rows": tuple(
                row.model_copy(
                    update={
                        "values": tuple(
                            value for value in row.values if value.name != "preferred_level_axis"
                        )
                    }
                )
                for row in rule.rows
            ),
        }
    )

    assert _codes(_replace_decision(package, without_axis)) == (
        ReinforcedRuleBlockCode.UNEXPECTED_SHAPE,
    )


def test_a_mode_this_application_cannot_carry_out_blocks(package: RulePackage) -> None:
    """A third kind of treatment is refused, not silently reduced to a multiplication."""
    rule = _decision(package, CREEPAGE_ROUTE)
    extra_mode = rule.model_copy(
        update={
            "outputs": tuple(
                item.model_copy(update={"allowed_values": (*item.allowed_values, "synthetic_mode")})
                if item.name == "treatment_mode"
                else item
                for item in rule.outputs
            )
        }
    )

    assert _codes(_replace_decision(package, extra_mode)) == (
        ReinforcedRuleBlockCode.UNEXPECTED_SHAPE,
    )


def test_an_axis_the_package_does_not_carry_blocks(package: RulePackage) -> None:
    without_table = package.model_copy(
        update={
            "tables": tuple(
                item for item in package.tables if item.id != ids.CLEARANCE_REQUIREMENTS
            )
        }
    )

    assert _codes(without_table) == (ReinforcedRuleBlockCode.RULE_MISSING,)


def test_a_class_no_statement_covers_is_refused_rather_than_answered(
    package: RulePackage,
) -> None:
    """An unreached row is not a statement that nothing needs doing."""
    rules = read_reinforced_rules(package)

    with pytest.raises(ReinforcedTreatmentUnavailable) as raised:
        rules.treatment(
            CLEARANCE_ROUTE,
            insulation_class="basic",
            treated_quantity="impulse_withstand_voltage",
        )

    assert raised.value.codes == (ReinforcedRuleBlockCode.TREATMENT_NOT_STATED,)


def test_the_multiplier_and_the_mode_come_from_the_matched_row(package: RulePackage) -> None:
    rules = read_reinforced_rules(package)

    treatment = rules.treatment(
        CREEPAGE_ROUTE,
        insulation_class="reinforced",
        treated_quantity="basic_insulation_requirement",
    )

    assert treatment.mode == reinforced_rules.MULTIPLY
    assert treatment.multiplier == SYNTHETIC_REINFORCED_FACTOR
    assert multiply_stress(Decimal(10), treatment.multiplier) == 10 * SYNTHETIC_REINFORCED_FACTOR


def test_a_step_carries_the_axis_the_row_defers_to(package: RulePackage) -> None:
    rules = read_reinforced_rules(with_stepped_reinforced_impulse(package))

    treatment = rules.treatment(
        CLEARANCE_ROUTE,
        insulation_class="reinforced",
        treated_quantity="impulse_withstand_voltage",
    )

    assert treatment.mode == reinforced_rules.NEXT_LEVEL_IN_REQUIREMENT_AXIS
    assert treatment.level_axis_rule_id == ids.CLEARANCE_REQUIREMENTS
    assert treatment.levels == SYNTHETIC_REQUIREMENT_LEVELS_V


def test_stepping_moves_exactly_one_coordinate() -> None:
    lowest, next_level = SYNTHETIC_REQUIREMENT_LEVELS_V[:2]

    assert next_preferred_level(SYNTHETIC_REQUIREMENT_LEVELS_V, lowest) == next_level


def test_stepping_refuses_a_value_the_axis_does_not_carry() -> None:
    with pytest.raises(ReinforcedTreatmentUnavailable) as raised:
        next_preferred_level(
            SYNTHETIC_REQUIREMENT_LEVELS_V, SYNTHETIC_REQUIREMENT_LEVELS_V[0] + Decimal(1)
        )

    assert raised.value.codes == (ReinforcedRuleBlockCode.VALUE_OFF_AXIS,)


def test_stepping_refuses_the_top_of_the_axis() -> None:
    with pytest.raises(ReinforcedTreatmentUnavailable) as raised:
        next_preferred_level(SYNTHETIC_REQUIREMENT_LEVELS_V, SYNTHETIC_REQUIREMENT_LEVELS_V[-1])

    assert raised.value.codes == (ReinforcedRuleBlockCode.NO_HIGHER_LEVEL,)


@pytest.mark.parametrize("module", (clearance, creepage, reinforced_rules))
def test_no_fallback_constant_survives_in_the_treatment_modules(module: object) -> None:
    """The block is the only answer to a package that cannot state the treatment.

    An embedded series or factor would be a silent fallback: a reinforced pair would keep
    being dimensioned from a value this build has no approved rule for, and the result would
    be indistinguishable from one the standard produced. The repository's own licensed-content
    scanner is the check, so the rule this asserts is the same one the audit applies.
    """
    root = Path(__file__).parents[2]
    path = Path(getattr(module, "__file__", ""))
    # The inline-factor check only runs on paths under src/insulation_coordination/calculation,
    # so a wrong root would silently reduce this to the series check alone.
    assert path.relative_to(root).parts[:3] == ("src", "insulation_coordination", "calculation")

    findings = scan_file(path, root)

    assert findings == (), f"{path.name} still carries licensed-looking content: {findings}"
