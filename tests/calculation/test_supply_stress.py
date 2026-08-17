"""Single-scenario derivation and governing selection. Synthetic packages only; no IEC content.

Every voltage here is the fixture's invention, and so is every measure its resolution rule
selects. What these tests assert is behaviour: which rule was asked, what happens when it
answers nothing, and which scenario governs when several answer.
"""

from __future__ import annotations

from decimal import Decimal
from functools import cache
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from insulation_coordination.calculation.supply_rules import SupplyRuleSet, read_supply_rules
from insulation_coordination.calculation.supply_stress import (
    OVERVOLTAGE_CATEGORY_I_WARNING,
    TOV_PEAK_COLUMN,
    TOV_RMS_COLUMN,
    SupplyStressService,
    supply_form,
)
from insulation_coordination.domain.rules import DecisionRow, DecisionValue, Matcher, RulePackage
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    DerivedSupplyScenario,
    EarthingArrangement,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyDerivationBlockCode,
    SupplyKind,
    UnresolvedSupplyScenario,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

#: Inside the fixture's synthetic band axis, which runs 11 V to 33 V in three bands.
IN_BAND = Decimal(15)


@cache
def _supply_rules() -> SupplyRuleSet:
    return read_supply_rules(synthetic_supply_rule_package())


@pytest.fixture
def rules() -> SupplyRuleSet:
    return _supply_rules()


@pytest.fixture
def service() -> SupplyStressService:
    return SupplyStressService()


def _configuration(**overrides: object) -> SupplyConfiguration:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": IN_BAND,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.III,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=IN_BAND),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _derived(result: DerivedSupplyScenario | UnresolvedSupplyScenario) -> DerivedSupplyScenario:
    assert isinstance(result, DerivedSupplyScenario), getattr(result, "blocks", result)
    return result


def _codes(
    result: DerivedSupplyScenario | UnresolvedSupplyScenario,
) -> tuple[SupplyDerivationBlockCode, ...]:
    assert isinstance(result, UnresolvedSupplyScenario)
    return tuple(block.code for block in result.blocks)


def _with_rule_rows(package: RulePackage, rows: tuple[DecisionRow, ...]) -> SupplyRuleSet:
    rule = next(
        item for item in package.decisions if item.id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )
    replaced = rule.model_copy(update={"rows": rows})
    return read_supply_rules(
        package.model_copy(
            update={
                "decisions": tuple(
                    replaced if item.id == rule.id else item for item in package.decisions
                )
            }
        )
    )


def _with_column_labels(
    package: RulePackage, table_id: str, labels: tuple[str, ...]
) -> SupplyRuleSet:
    table = next(item for item in package.tables if item.id == table_id)
    relabelled = table.model_copy(
        update={"column_axis": table.column_axis.model_copy(update={"labels": labels})}
    )
    return read_supply_rules(
        package.model_copy(
            update={
                "tables": tuple(
                    relabelled if item.id == table.id else item for item in package.tables
                )
            }
        )
    )


# --- the system voltage each arrangement resolves to ---------------------------------


@pytest.mark.parametrize(
    ("phase_system", "earthing", "topology", "measures"),
    [
        (
            PhaseSystem.SINGLE_PHASE,
            EarthingArrangement.TN_STAR_POINT_EARTHED,
            InputTopology.DIRECT_INPUT,
            ("phase_to_earth_rms",),
        ),
        (
            PhaseSystem.SINGLE_PHASE,
            EarthingArrangement.TT_STAR_POINT_EARTHED,
            InputTopology.DIRECT_INPUT,
            ("phase_to_earth_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.TN_STAR_POINT_EARTHED,
            InputTopology.DIRECT_INPUT,
            ("phase_to_earth_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.TT_STAR_POINT_EARTHED,
            InputTopology.DIRECT_INPUT,
            ("phase_to_earth_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.IT_THREE_PHASE,
            InputTopology.DIRECT_INPUT,
            ("phase_to_artificial_neutral_rms", "phase_to_phase_rms"),
        ),
        (
            PhaseSystem.SINGLE_PHASE,
            EarthingArrangement.IT_SINGLE_PHASE,
            InputTopology.DIRECT_INPUT,
            ("between_supply_conductors_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.TN_TT_CORNER_EARTHED_DELTA,
            InputTopology.DIRECT_INPUT,
            ("phase_to_phase_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.TN_TT_HIGH_LEG_DELTA,
            InputTopology.DIRECT_INPUT,
            ("phase_to_phase_rms",),
        ),
        (
            PhaseSystem.THREE_PHASE,
            EarthingArrangement.TN_STAR_POINT_EARTHED,
            InputTopology.RECTIFIED_FROM_AC,
            ("pre_rectifier_ac_rms",),
        ),
    ],
)
def test_every_mains_arrangement_reads_the_measure_the_rule_names(
    service: SupplyStressService,
    rules: SupplyRuleSet,
    phase_system: PhaseSystem,
    earthing: EarthingArrangement,
    topology: InputTopology,
    measures: tuple[str, ...],
) -> None:
    scenario = _derived(
        service.derive_scenario(
            _configuration(
                phase_system=phase_system,
                earthing_arrangement=earthing,
                input_topology=topology,
                declared_system_voltages=tuple(
                    DeclaredSystemVoltage(measure=measure, value_v=IN_BAND + index)
                    for index, measure in enumerate(measures)
                ),
            ),
            rules,
        )
    )

    assert scenario.system_voltage_for_impulse_v == IN_BAND
    assert scenario.system_voltage_for_tov_v == IN_BAND + (len(measures) - 1)
    assert ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION in scenario.source_rule_ids


def test_a_non_mains_supply_resolves_its_own_measure(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(
        service.derive_scenario(
            _configuration(
                supply_kind=SupplyKind.NON_MAINS_AC,
                earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
                declared_system_voltages=(
                    DeclaredSystemVoltage(measure="between_supply_conductors_rms", value_v=IN_BAND),
                ),
            ),
            rules,
        )
    )

    assert scenario.system_voltage_for_impulse_v == IN_BAND


def test_series_connected_bridges_read_the_bridge_voltage_field(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(
        service.derive_scenario(
            _configuration(
                input_topology=InputTopology.SERIES_CONNECTED_RECTIFIER_BRIDGES,
                rectifier_bridge_rms_v=Decimal(30),
                declared_system_voltages=(),
            ),
            rules,
        )
    )

    assert scenario.system_voltage_for_impulse_v == Decimal(30)


def test_a_three_phase_it_arrangement_resolves_impulse_and_tov_separately(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(
        service.derive_scenario(
            _configuration(
                earthing_arrangement=EarthingArrangement.IT_THREE_PHASE,
                declared_system_voltages=(
                    DeclaredSystemVoltage(
                        measure="phase_to_artificial_neutral_rms", value_v=Decimal(12)
                    ),
                    DeclaredSystemVoltage(measure="phase_to_phase_rms", value_v=Decimal(21)),
                ),
            ),
            rules,
        )
    )

    assert scenario.system_voltage_for_impulse_v == Decimal(12)
    assert scenario.system_voltage_for_tov_v == Decimal(21)


def test_a_non_mains_dc_supply_is_looked_up_on_the_dc_axis(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    configuration = _configuration(
        supply_kind=SupplyKind.NON_MAINS_DC,
        phase_system=None,
        earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="between_supply_conductors_rms", value_v=IN_BAND),
        ),
    )

    assert supply_form(configuration) == "dc"
    scenario = _derived(service.derive_scenario(configuration, rules))
    assert any(
        step.semantic_rule_id == f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc.lookup"
        for step in scenario.trace_steps
    )


def test_a_rectified_mains_supply_stays_on_the_ac_axis(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    configuration = _configuration(
        supply_kind=SupplyKind.RECTIFIED_DC_FROM_AC_MAINS,
        input_topology=InputTopology.RECTIFIED_FROM_AC,
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="pre_rectifier_ac_rms", value_v=IN_BAND),
        ),
    )

    assert supply_form(configuration) == "ac"
    scenario = _derived(service.derive_scenario(configuration, rules))
    assert any(
        step.semantic_rule_id == f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac.lookup"
        for step in scenario.trace_steps
    )


# --- what the derived values carry ---------------------------------------------------


def test_a_derived_scenario_carries_its_impulse_tov_and_provenance(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(service.derive_scenario(_configuration(), rules))

    assert scenario.source_ovc is OvervoltageCategory.III
    assert scenario.rated_impulse_v > 0
    assert scenario.temporary_overvoltage_rms_v is not None
    assert scenario.temporary_overvoltage_peak_v is not None
    assert scenario.temporary_overvoltage_peak_v > scenario.temporary_overvoltage_rms_v
    assert scenario.source_rule_ids == (
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac.lookup",
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac.lookup",
    )
    assert scenario.trace_steps[0].semantic_rule_id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    assert "phase_to_earth_rms" in scenario.trace_steps[0].reason
    assert scenario.warnings == ()


@pytest.mark.parametrize("category", list(OvervoltageCategory))
def test_each_overvoltage_category_selects_its_own_column(
    service: SupplyStressService, rules: SupplyRuleSet, category: OvervoltageCategory
) -> None:
    scenario = _derived(
        service.derive_scenario(_configuration(overvoltage_category=category), rules)
    )
    first = _derived(
        service.derive_scenario(_configuration(overvoltage_category=OvervoltageCategory.I), rules)
    )

    assert (scenario.rated_impulse_v == first.rated_impulse_v) is (
        category is OvervoltageCategory.I
    )


def test_the_impulse_band_is_selected_and_never_interpolated(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    def at(voltage: int) -> DerivedSupplyScenario:
        return _derived(
            service.derive_scenario(
                _configuration(
                    declared_system_voltages=(
                        DeclaredSystemVoltage(
                            measure="phase_to_earth_rms", value_v=Decimal(voltage)
                        ),
                    ),
                ),
                rules,
            )
        )

    lower, higher = at(12), at(21)

    # Two different voltages inside one band select the same impulse cell, while the
    # temporary-overvoltage lookup on the very same voltages interpolates between bands.
    assert lower.rated_impulse_v == higher.rated_impulse_v
    assert lower.temporary_overvoltage_rms_v != higher.temporary_overvoltage_rms_v


def test_the_temporary_overvoltage_reads_its_rms_and_peak_columns_independently(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(service.derive_scenario(_configuration(), rules))

    selected = {cell for step in scenario.trace_steps for cell in step.source_cells}
    assert any(cell.endswith(TOV_RMS_COLUMN) for cell in selected)
    assert any(cell.endswith(TOV_PEAK_COLUMN) for cell in selected)


def test_a_derived_scenario_carries_the_kind_it_came_from(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(service.derive_scenario(_configuration(), rules))

    assert scenario.supply_kind is SupplyKind.AC_MAINS


# --- the lowest overvoltage category -----------------------------------------------------


def test_the_lowest_category_on_a_mains_supply_always_warns(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    scenario = _derived(
        service.derive_scenario(_configuration(overvoltage_category=OvervoltageCategory.I), rules)
    )
    again = _derived(
        service.derive_scenario(_configuration(overvoltage_category=OvervoltageCategory.I), rules)
    )

    codes = {warning.code for warning in scenario.warnings}
    assert OVERVOLTAGE_CATEGORY_I_WARNING in codes
    # Recomputed rather than stored, so it cannot be dismissed away between two runs.
    assert scenario.warnings == again.warnings
    assert scenario.rated_impulse_v > 0


@pytest.mark.parametrize(
    ("category", "kind", "earthing"),
    [
        (OvervoltageCategory.II, SupplyKind.AC_MAINS, EarthingArrangement.TN_STAR_POINT_EARTHED),
        (OvervoltageCategory.III, SupplyKind.AC_MAINS, EarthingArrangement.TN_STAR_POINT_EARTHED),
        (OvervoltageCategory.I, SupplyKind.NON_MAINS_AC, EarthingArrangement.NOT_APPLICABLE),
    ],
)
def test_no_other_configuration_carries_that_warning(
    service: SupplyStressService,
    rules: SupplyRuleSet,
    category: OvervoltageCategory,
    kind: SupplyKind,
    earthing: EarthingArrangement,
) -> None:
    measure = (
        "phase_to_earth_rms" if kind is SupplyKind.AC_MAINS else "between_supply_conductors_rms"
    )
    scenario = _derived(
        service.derive_scenario(
            _configuration(
                overvoltage_category=category,
                supply_kind=kind,
                earthing_arrangement=earthing,
                declared_system_voltages=(DeclaredSystemVoltage(measure=measure, value_v=IN_BAND),),
            ),
            rules,
        )
    )

    assert OVERVOLTAGE_CATEGORY_I_WARNING not in {warning.code for warning in scenario.warnings}


# --- blocking --------------------------------------------------------------------------


def test_a_custom_reviewed_topology_blocks_instead_of_borrowing_a_neighbour(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    result = service.derive_scenario(
        _configuration(input_topology=InputTopology.CUSTOM_REVIEWED_CONFIGURATION), rules
    )

    assert _codes(result) == (SupplyDerivationBlockCode.UNSUPPORTED_ARRANGEMENT,)


def test_an_arrangement_the_rule_states_nothing_for_blocks(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    result = service.derive_scenario(_configuration(phase_system=None), rules)

    assert _codes(result) == (SupplyDerivationBlockCode.SYSTEM_VOLTAGE_UNRESOLVED,)


def test_a_measure_the_configuration_states_no_voltage_for_blocks(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    result = service.derive_scenario(_configuration(declared_system_voltages=()), rules)

    assert _codes(result) == (SupplyDerivationBlockCode.MISSING_DECLARED_VOLTAGE,)
    assert isinstance(result, UnresolvedSupplyScenario)
    assert "phase_to_earth_rms" in result.blocks[0].message


def test_every_reason_a_configuration_cannot_derive_is_reported_together(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    result = service.derive_scenario(
        _configuration(overvoltage_category=None, declared_system_voltages=()), rules
    )

    assert set(_codes(result)) == {
        SupplyDerivationBlockCode.MISSING_DECLARED_VOLTAGE,
        SupplyDerivationBlockCode.CONFIGURATION_INCOMPLETE,
    }


def test_a_system_voltage_outside_the_reviewed_bands_blocks(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    result = service.derive_scenario(
        _configuration(
            declared_system_voltages=(
                DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=Decimal(9999)),
            ),
        ),
        rules,
    )

    assert _codes(result) == (SupplyDerivationBlockCode.LOOKUP_REFUSED,)


def test_an_arrangement_covering_states_the_rule_disagrees_about_blocks(
    service: SupplyStressService,
) -> None:
    package = synthetic_supply_rule_package()
    original = next(
        item for item in package.decisions if item.id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )
    disagreeing = DecisionRow(
        matchers=(Matcher(input="earthing_arrangement", op="equals", values=("tt",)),),
        values=(
            DecisionValue(
                name="system_voltage_measure", categorical="between_supply_conductors_rms"
            ),
        ),
        source=original.rows[0].source,
    )
    rules = _with_rule_rows(package, (disagreeing, *original.rows))

    result = service.derive_scenario(
        _configuration(earthing_arrangement=EarthingArrangement.TN_TT_CORNER_EARTHED_DELTA), rules
    )

    assert _codes(result) == (SupplyDerivationBlockCode.AMBIGUOUS_ARRANGEMENT,)


def test_a_table_without_the_column_a_category_needs_blocks(
    service: SupplyStressService,
) -> None:
    rules = _with_column_labels(
        synthetic_supply_rule_package(),
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
        ("unrelated-1", "unrelated-2", "unrelated-3", "unrelated-4"),
    )

    result = service.derive_scenario(_configuration(), rules)

    assert _codes(result) == (SupplyDerivationBlockCode.MISSING_LOOKUP_COLUMN,)


def test_an_absent_temporary_overvoltage_warns_and_leaves_the_impulse_standing(
    service: SupplyStressService,
) -> None:
    rules = _with_column_labels(
        synthetic_supply_rule_package(),
        f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac",
        ("unrelated-rms", "unrelated-peak"),
    )

    scenario = _derived(service.derive_scenario(_configuration(), rules))

    assert scenario.rated_impulse_v > 0
    assert scenario.temporary_overvoltage_rms_v is None
    assert scenario.temporary_overvoltage_peak_v is None
    assert {warning.code for warning in scenario.warnings} == {"supply_missing_lookup_column"}


# --- the governing scenario ------------------------------------------------------------


def _row(index: int, name: str, voltage: int, **overrides: object) -> SupplyConfiguration:
    return _configuration(
        id=UUID(int=index),
        name=name,
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=Decimal(voltage)),
        ),
        **overrides,
    )


def test_the_worst_scenario_governs_and_the_others_are_kept(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (_row(1, "Lower", 12), _row(2, "Higher", 30))

    governing = service.derive_all(rows, rules)

    assert governing.impulse_configuration_id == UUID(int=2)
    assert governing.tov_configuration_id == UUID(int=2)
    assert governing.tov_rms_configuration_id == UUID(int=2)
    assert governing.tov_rms_v is not None and governing.tov_peak_v is not None
    assert tuple(scenario.configuration_name for scenario in governing.scenarios) == (
        "Lower",
        "Higher",
    )
    assert any("Higher governs" in step.reason for step in governing.trace_steps)


def test_impulse_and_temporary_overvoltage_may_be_governed_separately(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    # Both rows sit in one impulse band, so the impulse ties and the lowest identifier takes
    # it; the interpolating temporary overvoltage separates them and the higher voltage wins.
    rows = (_row(2, "Lower voltage", 12), _row(5, "Higher voltage", 21))

    governing = service.derive_all(rows, rules)

    assert governing.impulse_configuration_id == UUID(int=2)
    assert governing.tov_configuration_id == UUID(int=5)
    assert governing.tov_rms_configuration_id == UUID(int=5)


def test_a_tie_is_broken_by_the_lowest_configuration_identifier(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (_row(7, "Later listed", 15), _row(3, "Lower identifier", 15))

    governing = service.derive_all(rows, rules)

    assert governing.impulse_configuration_id == UUID(int=3)
    impulse_step = governing.trace_steps[0]
    assert "Lower identifier governs" in impulse_step.reason
    assert "tied with Later listed" in impulse_step.reason


def test_a_disabled_configuration_takes_no_part(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (_row(1, "Enabled", 12), _row(2, "Disabled but valid", 30, enabled=False))

    governing = service.derive_all(rows, rules)

    assert governing.impulse_configuration_id == UUID(int=1)
    assert len(governing.scenarios) == 1
    assert governing.unresolved == ()


def test_every_invalid_row_is_reported_not_only_the_first(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (
        _row(1, "No category", 15, overvoltage_category=None),
        _row(2, "No topology rule", 15, input_topology=InputTopology.CUSTOM_REVIEWED_CONFIGURATION),
        _row(3, "Valid", 15),
    )

    governing = service.derive_all(rows, rules)

    assert tuple(row.configuration_name for row in governing.unresolved) == (
        "No category",
        "No topology rule",
    )
    assert governing.impulse_configuration_id == UUID(int=3)


def test_a_duplicate_name_stops_the_later_row_deriving(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (_row(1, "Same name", 12), _row(2, "  same   NAME ", 30))

    governing = service.derive_all(rows, rules)

    assert tuple(row.configuration_id for row in governing.unresolved) == (UUID(int=2),)
    assert governing.impulse_configuration_id == UUID(int=1)


def test_no_enabled_configuration_leaves_every_governing_value_absent(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    governing = service.derive_all((), rules)

    assert governing.impulse_v is None
    assert governing.tov_peak_v is None
    assert governing.tov_rms_v is None
    assert governing.trace_steps == ()


def test_the_same_input_gives_the_same_result(
    service: SupplyStressService, rules: SupplyRuleSet
) -> None:
    rows = (_row(2, "Second", 21), _row(1, "First", 21))

    assert service.derive_all(rows, rules) == service.derive_all(rows, rules)


@settings(deadline=None, max_examples=30)
@given(
    voltages=st.lists(st.integers(min_value=11, max_value=33), min_size=1, max_size=4),
    additional=st.integers(min_value=11, max_value=33),
)
def test_enabling_another_valid_scenario_never_lowers_the_governing_stress(
    voltages: list[int], additional: int
) -> None:
    service = SupplyStressService()
    rules = _supply_rules()
    rows = tuple(
        _row(index, f"Row {index}", voltage) for index, voltage in enumerate(voltages, start=1)
    )
    extra = _row(len(rows) + 1, f"Row {len(rows) + 1}", additional)

    before = service.derive_all(rows, rules)
    after = service.derive_all((*rows, extra), rules)

    assert before.unresolved == () and after.unresolved == ()
    for earlier, later in (
        (before.impulse_v, after.impulse_v),
        (before.tov_peak_v, after.tov_peak_v),
        (before.tov_rms_v, after.tov_rms_v),
    ):
        assert earlier is not None and later is not None
        assert later >= earlier
