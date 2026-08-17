"""Domain propagation and pair scope. Synthetic packages and invented topologies only.

Every voltage, domain and barrier below is this test module's own. What is asserted is
behaviour: which barrier carries a stress and which does not, what a domain that was never
evaluated answers compared with one that was and found nothing, which route governs when
several reach the same place, and which pairs a mains temporary overvoltage is automatically
the concern of.

The topology builder here exists because the shipped worked examples in
``tests/fixtures/topology_examples.py`` carry two domains and one barrier each - enough for a
transfer, not enough for a cycle, a bypassed barrier or an unevaluated one. Those fixtures are
used directly wherever they do reach the case.
"""

from __future__ import annotations

from decimal import Decimal
from functools import cache
from uuid import UUID

import pytest

from insulation_coordination.calculation.impulse_override import (
    OverrideRefusalCode,
    PairImpulseOverride,
)
from insulation_coordination.calculation.stress_propagation import (
    TOV_ENTRY_CONTRADICTS_WARNING,
    UNATTACHED_SCENARIO_WARNING,
    UNRESOLVED_TOPOLOGY_WARNING,
    DomainStressMap,
    DomainStressState,
    TemporaryOvervoltageSource,
    propagate_impulse_to_domains,
    resolve_pair_stresses,
)
from insulation_coordination.calculation.supply_rules import SupplyRuleSet, read_supply_rules
from insulation_coordination.calculation.supply_stress import SupplyStressService, select_impulse
from insulation_coordination.domain.enums import (
    CircuitSourceRelationship,
    NetClassType,
)
from insulation_coordination.domain.project import (
    PairVoltage,
    PairVoltages,
    Project,
)
from insulation_coordination.domain.rules import (
    DecisionRow,
    DecisionValue,
    Matcher,
    RulePackage,
)
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    DerivedSupplyScenario,
    EarthingArrangement,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PairRelationship,
    PhaseSystem,
    ReductionVerificationMethod,
    SupplyConfiguration,
    SupplyKind,
    VerifiedImpulseOverride,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.supply_topologies import (
    COVER,
    ENCLOSURE,
    NO_ISOLATION,
    UNEVALUATED,
    VERIFIED,
    barrier_id,
    circuit_id,
    domain_id,
    pair_between,
    supply_topology,
)
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package
from tests.fixtures.topology_examples import obc_isolated_project, obc_non_isolated_project

#: Inside the fixture's synthetic band axis, which runs 11 V to 33 V in three bands.
IN_BAND = Decimal(15)

_ORDINAL_CATEGORIES = ("ovc_i", "ovc_ii", "ovc_iii", "ovc_iv")


@cache
def _plain_rules() -> SupplyRuleSet:
    """The fixture package as it ships: one transfer answer for every source category."""

    return read_supply_rules(synthetic_supply_rule_package())


@cache
def _one_level_rules() -> SupplyRuleSet:
    """The same package with a transfer decision that steps down once per barrier.

    The shipped fixture answers every transfer with one category, which is enough to prove a
    barrier attenuates at all and not enough to tell a one-barrier route from a two-barrier
    one. Rows built here restore that difference without touching any value: they map a source
    category to the next one down, which is a shape, not a reading.
    """

    package = synthetic_supply_rule_package()
    original = next(
        item for item in package.decisions if item.id == ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION
    )
    rows = tuple(
        DecisionRow(
            matchers=(
                Matcher(input="evaluated_side", op="equals", values=(side,)),
                Matcher(
                    input=(
                        "mains_overvoltage_category"
                        if side == "non_mains"
                        else "non_mains_overvoltage_category"
                    ),
                    op="equals",
                    values=(category,),
                ),
                Matcher(
                    input=(
                        "non_mains_overvoltage_category"
                        if side == "non_mains"
                        else "mains_overvoltage_category"
                    ),
                    op="any",
                ),
                Matcher(input="galvanic_isolation_present", op="equals", boolean=True),
            ),
            values=(
                DecisionValue(
                    name="source_requirement",
                    categorical=category,
                ),
                DecisionValue(
                    name="transferred_requirement",
                    categorical=_ORDINAL_CATEGORIES[
                        max(_ORDINAL_CATEGORIES.index(category) - 1, 0)
                    ],
                ),
                DecisionValue(name="governing_requirement", categorical=category),
            ),
            source=original.rows[0].source,
        )
        for side in ("mains", "non_mains")
        for category in _ORDINAL_CATEGORIES
    )
    return _with_decision(package, original.id, rows)


def _with_decision(
    package: RulePackage, rule_id: str, rows: tuple[DecisionRow, ...]
) -> SupplyRuleSet:
    replaced = tuple(
        item.model_copy(update={"rows": rows}) if item.id == rule_id else item
        for item in package.decisions
    )
    return read_supply_rules(package.model_copy(update={"decisions": replaced}))


def _configuration(**overrides: object) -> SupplyConfiguration:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "enabled": True,
        "name": "Synthetic mains",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": IN_BAND,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.IV,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=IN_BAND),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def _scenarios(
    rules: SupplyRuleSet, *configurations: SupplyConfiguration
) -> tuple[DerivedSupplyScenario, ...]:
    service = SupplyStressService()
    governing = service.derive_all(configurations or (_configuration(),), rules)
    assert governing.unresolved == (), governing.unresolved
    return governing.scenarios


def _map(
    project: Project, rules: SupplyRuleSet, *configurations: SupplyConfiguration
) -> DomainStressMap:
    return propagate_impulse_to_domains(project, _scenarios(rules, *configurations), rules)


def _stress(stresses: DomainStressMap, index: int) -> object:
    resolved = stresses.for_domain(domain_id(index))
    assert resolved is not None
    return resolved


# --- what each kind of barrier does ------------------------------------------------------


def test_a_verified_barrier_transfers_exactly_what_the_rule_states_and_no_more() -> None:
    rules = _one_level_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))

    stresses = _map(project, rules)

    primary, secondary = _stress(stresses, 0), _stress(stresses, 1)
    one_level_down = select_impulse(rules, "ac", IN_BAND, OvervoltageCategory.III).value
    assert primary.state is DomainStressState.SUPPLIED
    assert secondary.state is DomainStressState.TRANSFERRED
    # Verified isolation buys exactly the stated one-level transfer. It is not a licence to
    # attenuate further, so the arrival is the table's own value at that category.
    assert secondary.governing_impulse_v == one_level_down
    assert secondary.governing_impulse_v < primary.governing_impulse_v


def test_domains_with_no_isolation_between_them_are_one_set_at_the_worst_stress() -> None:
    rules = _plain_rules()
    project = supply_topology(("Mains side", "Battery side"), ((0, 1, NO_ISOLATION),))

    stresses = _map(project, rules)

    first, second = _stress(stresses, 0), _stress(stresses, 1)
    assert first.governing_impulse_v == second.governing_impulse_v
    assert first.state is second.state is DomainStressState.SUPPLIED
    assert first.component_domain_ids == second.component_domain_ids
    assert second.transferred == ()


def test_a_domain_pair_with_no_recorded_barrier_carries_nothing_across() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary", "Island"))

    island = _stress(_map(project, rules), 1)

    assert island.state is DomainStressState.NO_STRESS
    assert island.governing_impulse_v is None


def test_an_unevaluated_barrier_is_not_isolation_and_is_not_no_stress() -> None:
    rules = _plain_rules()
    project = supply_topology(
        ("Primary", "Unknown", "Island"),
        ((0, 1, UNEVALUATED),),
    )

    stresses = _map(project, rules)
    primary, unknown, island = (_stress(stresses, index) for index in range(3))

    assert unknown.state is DomainStressState.NOT_EVALUATED
    assert primary.state is DomainStressState.NOT_EVALUATED
    # The supplied domain still knows its own value; what it does not know is whether more
    # arrives. That is a different answer from the island's settled "nothing reaches me".
    assert primary.governing_impulse_v is not None
    assert island.state is DomainStressState.NO_STRESS
    assert island.governing_impulse_v is None
    assert unknown.unresolved_barrier_ids == (barrier_id(0),)
    assert UNRESOLVED_TOPOLOGY_WARNING in {warning.code for warning in stresses.warnings}


def test_a_verified_barrier_bypassed_by_a_connection_carries_nothing() -> None:
    rules = _one_level_rules()
    project = supply_topology(
        ("Primary", "Secondary", "Bridge"),
        ((0, 1, VERIFIED), (0, 2, NO_ISOLATION), (1, 2, NO_ISOLATION)),
    )

    stresses = _map(project, rules)

    assert _stress(stresses, 1).transferred == ()
    assert "supply_barrier_bypassed" in {warning.code for warning in stresses.warnings}


# --- routes ------------------------------------------------------------------------------


def test_every_route_to_one_domain_is_evaluated_and_the_worst_governs() -> None:
    rules = _one_level_rules()
    # A cycle: the far domain is reachable directly and the long way round.
    project = supply_topology(
        ("Primary", "Middle", "Far"),
        ((0, 1, VERIFIED), (0, 2, VERIFIED), (1, 2, VERIFIED)),
    )

    far = _stress(_map(project, rules), 2)

    routes = {stress.barrier_path for stress in far.transferred}
    assert routes == {(barrier_id(1),), (barrier_id(0), barrier_id(2))}
    assert far.governing_transfer is not None
    assert far.governing_transfer.barrier_path == (barrier_id(1),)
    assert far.governing_transfer.transferred_ovc is OvervoltageCategory.III
    assert far.governing_impulse_v == far.governing_transfer.impulse_v


def test_a_cycle_resolves_rather_than_being_refused() -> None:
    rules = _one_level_rules()
    project = supply_topology(
        ("Primary", "Middle", "Far"),
        ((0, 1, VERIFIED), (0, 2, VERIFIED), (1, 2, VERIFIED)),
    )

    first = _map(project, rules)
    again = _map(project, rules)

    assert first == again
    assert all(item.governing_impulse_v is not None for item in first.domains)


def test_a_transferred_stress_names_its_source_route_and_arrival() -> None:
    rules = _one_level_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))

    arrival = _stress(_map(project, rules), 1).transferred[0]

    assert arrival.source.scenario.configuration_name == "Synthetic mains"
    assert arrival.source.entry_domain_id == domain_id(0)
    assert arrival.domain_path == (domain_id(0), domain_id(1))
    assert arrival.barrier_path == (barrier_id(0),)
    assert arrival.transferred_ovc is OvervoltageCategory.III
    assert arrival.trace_steps


# --- sources -----------------------------------------------------------------------------


def test_a_scenario_no_net_declares_reaches_nothing_and_says_so() -> None:
    rules = _plain_rules()
    project = supply_topology(
        ("Primary", "Secondary"),
        ((0, 1, VERIFIED),),
        sources={0: CircuitSourceRelationship.INTERNALLY_GENERATED},
    )

    stresses = _map(project, rules)

    assert UNATTACHED_SCENARIO_WARNING in {warning.code for warning in stresses.warnings}
    assert all(item.governing_impulse_v is None for item in stresses.domains)


def test_two_supplies_entering_one_set_are_both_kept_and_the_worse_governs() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, NO_ISOLATION),))
    lower = _configuration(id=UUID(int=1), name="Lower")
    higher = _configuration(
        id=UUID(int=2),
        name="Higher",
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=Decimal(30)),
        ),
    )

    primary = _stress(_map(project, rules, lower, higher), 0)

    assert len(primary.own) == 2
    assert primary.governing_impulse_v == max(item.scenario.rated_impulse_v for item in primary.own)


def test_a_project_with_no_domains_propagates_nothing() -> None:
    """A project predating the topology model keeps calculating; it just propagates nothing."""

    rules = _plain_rules()
    unclassified = (
        supply_topology(("Primary",))
        .net_classes[0]
        .model_copy(
            update={
                "net_type": NetClassType.PE_BONDED_CONDUCTIVE_PART,
                "source_relationship": None,
                "connection_exposure": None,
                "decisive_voltage_class": None,
                "galvanic_domain_id": None,
            }
        )
    )
    nets = (unclassified, *supply_topology(("Primary",)).net_classes[1:])
    project = supply_topology(("Primary",)).model_copy(
        update={"galvanic_domains": (), "galvanic_barriers": (), "net_classes": nets}
    )

    assert propagate_impulse_to_domains(project, _scenarios(rules), rules) == DomainStressMap()


def test_the_shipped_worked_examples_propagate() -> None:
    rules = _one_level_rules()
    isolated = obc_isolated_project()
    non_isolated = obc_non_isolated_project()

    across = _map(isolated, rules)
    combined = _map(non_isolated, rules)

    primary, secondary = across.domains
    assert secondary.state is DomainStressState.TRANSFERRED
    assert secondary.governing_impulse_v is not None
    assert secondary.governing_impulse_v < primary.governing_impulse_v
    assert {item.governing_impulse_v for item in combined.domains} == {
        combined.domains[0].governing_impulse_v
    }


# --- pairs --------------------------------------------------------------------------------


def test_a_pair_takes_the_worse_of_its_two_sides() -> None:
    rules = _one_level_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(0), circuit_id(1)), stresses, rules
    )

    assert resolution.relationship is PairRelationship.CIRCUIT_TO_CIRCUIT
    assert resolution.governing_pre_override_impulse_v == _stress(stresses, 0).governing_impulse_v
    assert resolution.transferred_impulse_v == _stress(stresses, 1).governing_impulse_v
    assert resolution.local_domain_impulse_v == _stress(stresses, 0).own_impulse_v
    assert resolution.source_scenario_impulse_v == resolution.governing_pre_override_impulse_v
    assert resolution.verified_effective_impulse_v == resolution.governing_pre_override_impulse_v


def test_a_transferred_pair_records_the_source_it_came_from_before_the_transfer() -> None:
    rules = _one_level_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(1), COVER), stresses, rules
    )

    assert resolution.governing_pre_override_impulse_v == _stress(stresses, 1).governing_impulse_v
    assert resolution.source_scenario_impulse_v == _stress(stresses, 0).own_impulse_v
    assert resolution.source_scenario_impulse_v > resolution.governing_pre_override_impulse_v


def test_an_unresolved_topology_blocks_a_pair_without_touching_its_manual_entries() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary", "Unknown"), ((0, 1, UNEVALUATED),))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(0), ENCLOSURE), stresses, rules
    )

    assert resolution.state is DomainStressState.NOT_EVALUATED
    assert resolution.governing_pre_override_impulse_v is None
    assert resolution.verified_effective_impulse_v is None
    assert UNRESOLVED_TOPOLOGY_WARNING in {warning.code for warning in resolution.warnings}
    assert not resolution.temporary_overvoltage.applies


# --- temporary overvoltage scope ------------------------------------------------------------


def test_a_mains_temporary_overvoltage_applies_to_circuit_to_surroundings() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(0), ENCLOSURE), stresses, rules
    )

    temporary = resolution.temporary_overvoltage
    assert resolution.relationship is PairRelationship.CIRCUIT_TO_SURROUNDINGS
    assert temporary.applies
    assert temporary.source is TemporaryOvervoltageSource.DERIVED_MAINS
    assert temporary.source_configuration_id == UUID(int=1)
    assert temporary.peak_v is not None and temporary.rms_v is not None


@pytest.mark.parametrize("other", [ENCLOSURE, COVER])
def test_every_surroundings_net_type_receives_it(other: UUID) -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(0), other), stresses, rules
    )

    assert resolution.temporary_overvoltage.source is TemporaryOvervoltageSource.DERIVED_MAINS


def test_two_circuits_never_receive_the_project_mains_figure() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, NO_ISOLATION),))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(0), circuit_id(1)), stresses, rules
    )

    temporary = resolution.temporary_overvoltage
    assert resolution.relationship is PairRelationship.CIRCUIT_TO_CIRCUIT
    assert not temporary.applies
    assert temporary.peak_v is None
    assert "not automatically applied between two circuits" in temporary.reason


def test_two_circuits_keep_a_temporary_overvoltage_they_state_themselves() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, NO_ISOLATION),))
    stresses = _map(project, rules)
    pair = pair_between(project, circuit_id(0), circuit_id(1)).model_copy(
        update={
            "voltages": PairVoltages(
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(77))
            )
        }
    )

    temporary = resolve_pair_stresses(project, pair, stresses, rules).temporary_overvoltage

    assert temporary.applies
    assert temporary.source is TemporaryOvervoltageSource.PAIR_ENTRY
    assert temporary.peak_v == Decimal(77)


def test_a_pair_of_two_non_circuits_receives_nothing() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, ENCLOSURE, COVER), stresses, rules
    )

    assert resolution.relationship is PairRelationship.NON_CIRCUIT_REFERENCE
    assert not resolution.temporary_overvoltage.applies
    assert "Neither side" in resolution.temporary_overvoltage.reason


def test_a_temporary_overvoltage_is_not_carried_across_verified_isolation() -> None:
    rules = _one_level_rules()
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    stresses = _map(project, rules)

    resolution = resolve_pair_stresses(
        project, pair_between(project, circuit_id(1), ENCLOSURE), stresses, rules
    )

    assert resolution.relationship is PairRelationship.CIRCUIT_TO_SURROUNDINGS
    assert not resolution.temporary_overvoltage.applies
    assert "No enabled mains supply reaches" in resolution.temporary_overvoltage.reason


def test_a_recorded_exclusion_stands_and_the_disagreement_is_reported() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)
    pair = pair_between(project, circuit_id(0), ENCLOSURE).model_copy(
        update={
            "voltages": PairVoltages(
                temporary_overvoltage_peak_v=PairVoltage.not_applicable(
                    "This example records no temporary overvoltage here."
                )
            )
        }
    )

    resolution = resolve_pair_stresses(project, pair, stresses, rules)

    assert not resolution.temporary_overvoltage.applies
    assert resolution.temporary_overvoltage.contradicted_derived_peak_v is not None
    assert TOV_ENTRY_CONTRADICTS_WARNING in {warning.code for warning in resolution.warnings}


# --- an override belongs to one location ------------------------------------------------


def _increase(location: str = "pair") -> VerifiedImpulseOverride:
    return VerifiedImpulseOverride(
        value_v=Decimal(9000),
        basis=ImpulseOverrideBasis.CONSERVATIVE_INCREASE,
        verification_method=ReductionVerificationMethod.CALCULATION,
        justification="Synthetic conservative increase",
        evidence_reference="",
        affected_location=location,
    )


def test_an_override_recorded_against_another_pair_never_applies_here() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)
    here = pair_between(project, circuit_id(0), ENCLOSURE)
    elsewhere = pair_between(project, circuit_id(0), COVER)

    resolution = resolve_pair_stresses(
        project,
        here,
        stresses,
        rules,
        override=PairImpulseOverride(pair_id=elsewhere.id, override=_increase("the other pair")),
    )

    assert resolution.override_outcome is not None
    assert not resolution.override_outcome.applied
    assert [refusal.code for refusal in resolution.override_outcome.refusals] == [
        OverrideRefusalCode.WRONG_LOCATION
    ]
    assert resolution.verified_effective_impulse_v == (resolution.governing_pre_override_impulse_v)


def test_clearing_an_override_restores_the_propagated_value() -> None:
    rules = _plain_rules()
    project = supply_topology(("Primary",))
    stresses = _map(project, rules)
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    applied = resolve_pair_stresses(
        project,
        pair,
        stresses,
        rules,
        override=PairImpulseOverride(pair_id=pair.id, override=_increase()),
    )
    cleared = resolve_pair_stresses(project, pair, stresses, rules)

    assert applied.verified_effective_impulse_v == Decimal(9000)
    assert cleared.override_outcome is None
    assert cleared.verified_effective_impulse_v == cleared.governing_pre_override_impulse_v
    assert cleared.governing_pre_override_impulse_v == applied.governing_pre_override_impulse_v
