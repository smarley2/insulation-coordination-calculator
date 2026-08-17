"""The supply rule adapter's blocking behaviour. Synthetic packages only; no IEC content."""

from decimal import Decimal

import pytest

from insulation_coordination.calculation.supply_rules import (
    READ_SEMANTIC_IDS,
    RULES_READ_ELSEWHERE,
    SPD_MAINS_ROUTE,
    SPD_MONITORING_ROUTE,
    SPD_NON_MAINS_ROUTE,
    SupplyRuleBlockCode,
    SupplyRulesUnavailable,
    read_supply_rules,
    supply_rule_blocks,
)
from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionRule,
    Formula,
    RulePackage,
    Table,
    TableSelect,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package


@pytest.fixture
def supply_package() -> RulePackage:
    return synthetic_supply_rule_package()


def _without_decision(package: RulePackage, rule_id: str) -> RulePackage:
    return package.model_copy(
        update={"decisions": tuple(rule for rule in package.decisions if rule.id != rule_id)}
    )


def _replace_decision(package: RulePackage, rule: DecisionRule) -> RulePackage:
    return package.model_copy(
        update={
            "decisions": tuple(rule if item.id == rule.id else item for item in package.decisions)
        }
    )


def _decision(package: RulePackage, rule_id: str) -> DecisionRule:
    return next(rule for rule in package.decisions if rule.id == rule_id)


def _formula(package: RulePackage, formula_id: str) -> Formula:
    return next(item for item in package.formulas if item.id == formula_id)


def _table(package: RulePackage, table_id: str) -> Table:
    return next(item for item in package.tables if item.id == table_id)


def _blocks(package: RulePackage | None) -> tuple[tuple[SupplyRuleBlockCode, str | None], ...]:
    return tuple((block.code, block.semantic_rule_id) for block in supply_rule_blocks(package))


def test_an_approved_package_resolves_every_supply_rule(supply_package: RulePackage) -> None:
    rules = read_supply_rules(supply_package)

    assert rules.system_voltage_resolution.id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    assert rules.multiple_source_propagation.id == ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION
    assert rules.verified_barrier_transfer.id == ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    assert rules.hf_transformer_attenuation.id == ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
    assert rules.spd_reduction.mains.id == SPD_MAINS_ROUTE
    assert rules.spd_reduction.non_mains.id == SPD_NON_MAINS_ROUTE
    assert rules.spd_reduction.monitoring.id == SPD_MONITORING_ROUTE
    assert supply_rule_blocks(supply_package) == ()


def test_each_quantity_resolves_its_own_ac_and_dc_lookup(supply_package: RulePackage) -> None:
    rules = read_supply_rules(supply_package)

    assert rules.impulse.for_form("ac").table.id == f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac"
    assert rules.impulse.for_form("dc").table.id == f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc"
    assert rules.temporary_overvoltage.for_form("ac").table.id == (
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac"
    )
    assert rules.impulse.ac.table.id != rules.temporary_overvoltage.ac.table.id


def test_no_package_blocks_and_never_returns_a_value() -> None:
    assert _blocks(None) == ((SupplyRuleBlockCode.NO_PACKAGE, None),)
    with pytest.raises(SupplyRulesUnavailable) as raised:
        read_supply_rules(None)

    assert raised.value.codes == (SupplyRuleBlockCode.NO_PACKAGE,)


def test_an_unapproved_package_blocks_whole(supply_package: RulePackage) -> None:
    unapproved = supply_package.model_copy(
        update={"manifest": supply_package.manifest.model_copy(update={"approved": False})}
    )

    assert _blocks(unapproved) == ((SupplyRuleBlockCode.PACKAGE_NOT_APPROVED, None),)


def test_an_incompatible_package_blocks_whole(supply_package: RulePackage) -> None:
    incompatible = supply_package.model_copy(
        update={"manifest": supply_package.manifest.model_copy(update={"compatible": False})}
    )

    assert _blocks(incompatible) == ((SupplyRuleBlockCode.PACKAGE_NOT_COMPATIBLE, None),)


def test_a_wrong_edition_package_blocks_every_rule_it_carries() -> None:
    wrong_edition = synthetic_supply_rule_package(edition=f"{EDITION}-not")

    codes = {code for code, _rule_id in _blocks(wrong_edition)}
    blocked = {rule_id for _code, rule_id in _blocks(wrong_edition)}

    assert codes == {SupplyRuleBlockCode.WRONG_EDITION}
    assert ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION in blocked
    with pytest.raises(SupplyRulesUnavailable, match="not IEC 62477-1"):
        read_supply_rules(wrong_edition)


@pytest.mark.parametrize(
    "rule_id",
    [
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        SPD_MAINS_ROUTE,
        SPD_NON_MAINS_ROUTE,
        SPD_MONITORING_ROUTE,
    ],
)
def test_a_missing_rule_blocks_and_names_itself(supply_package: RulePackage, rule_id: str) -> None:
    without = _without_decision(supply_package, rule_id)

    assert (SupplyRuleBlockCode.RULE_MISSING, rule_id) in _blocks(without)
    with pytest.raises(SupplyRulesUnavailable, match=rule_id):
        read_supply_rules(without)


def test_every_missing_rule_is_reported_not_only_the_first(
    supply_package: RulePackage,
) -> None:
    stripped = _without_decision(
        _without_decision(supply_package, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION),
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
    )

    assert {rule_id for _code, rule_id in _blocks(stripped)} == {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
    }


def test_a_rule_asking_for_an_input_this_application_does_not_supply_blocks(
    supply_package: RulePackage,
) -> None:
    rule = _decision(supply_package, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)
    widened = rule.model_copy(
        update={
            "inputs": (
                *rule.inputs,
                DecisionInput(name="synthetic_extra", kind="categorical", allowed_values=("a",)),
            )
        }
    )

    assert (
        SupplyRuleBlockCode.UNEXPECTED_SHAPE,
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
    ) in _blocks(_replace_decision(supply_package, widened))


def test_a_rule_missing_an_input_this_application_resolves_it_by_blocks(
    supply_package: RulePackage,
) -> None:
    rule = _decision(supply_package, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)
    narrowed = rule.model_copy(update={"inputs": rule.inputs[:-1]})

    assert (
        SupplyRuleBlockCode.UNEXPECTED_SHAPE,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
    ) in _blocks(_replace_decision(supply_package, narrowed))


def test_a_rule_stating_none_of_the_outputs_read_here_blocks(
    supply_package: RulePackage,
) -> None:
    rule = _decision(supply_package, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION)
    renamed = rule.model_copy(
        update={
            "outputs": tuple(
                item.model_copy(update={"name": f"synthetic_{item.name}"}) for item in rule.outputs
            ),
            "rows": tuple(
                row.model_copy(
                    update={
                        "values": tuple(
                            value.model_copy(update={"name": f"synthetic_{value.name}"})
                            for value in row.values
                        )
                    }
                )
                for row in rule.rows
            ),
        }
    )

    assert (
        SupplyRuleBlockCode.UNEXPECTED_SHAPE,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
    ) in _blocks(_replace_decision(supply_package, renamed))


def test_an_absent_device_monitoring_route_is_an_answer_not_a_block(
    supply_package: RulePackage,
) -> None:
    without = _without_decision(supply_package, f"{SPD_MAINS_ROUTE}.device_monitoring")
    rules = read_supply_rules(without)

    assert rules.spd_reduction.mains_device_monitoring is None
    assert rules.spd_reduction.non_mains_device_monitoring is not None


def test_a_device_monitoring_route_of_the_wrong_shape_still_blocks(
    supply_package: RulePackage,
) -> None:
    route = f"{SPD_MAINS_ROUTE}.device_monitoring"
    rule = _decision(supply_package, route)
    narrowed = rule.model_copy(update={"outputs": rule.outputs[:1]})

    assert (SupplyRuleBlockCode.UNEXPECTED_SHAPE, route) in _blocks(
        _replace_decision(supply_package, narrowed)
    )


def test_a_missing_lookup_formula_blocks(supply_package: RulePackage) -> None:
    formula_id = f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc.lookup"
    without = supply_package.model_copy(
        update={
            "formulas": tuple(item for item in supply_package.formulas if item.id != formula_id)
        }
    )

    assert (SupplyRuleBlockCode.RULE_MISSING, formula_id) in _blocks(without)


def test_a_missing_lookup_table_blocks(supply_package: RulePackage) -> None:
    table_id = f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac"
    without = supply_package.model_copy(
        update={"tables": tuple(item for item in supply_package.tables if item.id != table_id)}
    )

    assert (SupplyRuleBlockCode.RULE_MISSING, table_id) in _blocks(without)


def test_an_impulse_lookup_that_interpolates_between_bands_blocks(
    supply_package: RulePackage,
) -> None:
    formula_id = f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac.lookup"
    formula = _formula(supply_package, formula_id)
    expression = formula.expression
    assert isinstance(expression, TableSelect)
    interpolating = formula.model_copy(
        update={"expression": expression.model_copy(update={"row_mode": "linear"})}
    )
    package = supply_package.model_copy(
        update={
            "formulas": tuple(
                interpolating if item.id == formula_id else item for item in supply_package.formulas
            )
        }
    )

    assert (SupplyRuleBlockCode.UNEXPECTED_SHAPE, formula_id) in _blocks(package)


def test_an_impulse_table_declaring_interpolation_blocks(supply_package: RulePackage) -> None:
    table_id = f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac"
    table = _table(supply_package, table_id)
    package = supply_package.model_copy(
        update={
            "tables": tuple(
                table.model_copy(update={"interpolation": "linear"})
                if item.id == table_id
                else item
                for item in supply_package.tables
            )
        }
    )

    assert (SupplyRuleBlockCode.UNEXPECTED_SHAPE, table_id) in _blocks(package)


def test_the_temporary_overvoltage_lookup_may_interpolate(supply_package: RulePackage) -> None:
    rules = read_supply_rules(supply_package)
    lookup = rules.temporary_overvoltage.for_form("ac")

    assert lookup.table.interpolation == "linear"


def test_a_lookup_reading_the_wrong_axis_blocks(supply_package: RulePackage) -> None:
    formula_id = f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc.lookup"
    formula = _formula(supply_package, formula_id)
    expression = formula.expression
    assert isinstance(expression, TableSelect)
    crossed = formula.model_copy(
        update={
            "expression": expression.model_copy(
                update={"table_id": f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc"}
            )
        }
    )
    package = supply_package.model_copy(
        update={
            "formulas": tuple(
                crossed if item.id == formula_id else item for item in supply_package.formulas
            )
        }
    )

    assert (SupplyRuleBlockCode.UNEXPECTED_SHAPE, formula_id) in _blocks(package)


def test_a_lookup_returning_something_other_than_a_voltage_blocks(
    supply_package: RulePackage,
) -> None:
    formula_id = f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc.lookup"
    formula = _formula(supply_package, formula_id)
    package = supply_package.model_copy(
        update={
            "formulas": tuple(
                formula.model_copy(update={"unit": "mm"}) if item.id == formula_id else item
                for item in supply_package.formulas
            )
        }
    )

    assert (SupplyRuleBlockCode.UNEXPECTED_SHAPE, formula_id) in _blocks(package)


def test_the_adapter_reads_the_supply_identifiers_and_no_invented_one() -> None:
    assert READ_SEMANTIC_IDS <= ids.REQUIRED_SEMANTIC_IDS
    assert RULES_READ_ELSEWHERE <= ids.REQUIRED_SEMANTIC_IDS
    assert not READ_SEMANTIC_IDS & RULES_READ_ELSEWHERE
    assert all(item.startswith("iec62477_2022.supply.") for item in READ_SEMANTIC_IDS)


def test_the_spd_routes_are_built_from_their_identifier() -> None:
    for route in (SPD_MAINS_ROUTE, SPD_NON_MAINS_ROUTE, SPD_MONITORING_ROUTE):
        assert route.startswith(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.")


def test_the_adapter_holds_no_voltage_of_its_own(supply_package: RulePackage) -> None:
    """Every number a resolved rule carries came from the package, not from this module."""
    rules = read_supply_rules(supply_package)
    cells = {cell.value for cell in rules.impulse.for_form("ac").table.cells}

    assert cells == {
        Decimal((row + 1) * 100 + (column + 1) * 7) for row in range(3) for column in range(4)
    }
