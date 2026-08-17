"""Verified overrides and the warnings they carry. Synthetic packages only; no IEC content.

Nothing here asserts a value the standard states. What it asserts is which claims the active
package supports, which it refuses, which obligations follow from a basis whatever the package
says, and that the dependency issue #37 consumes is recorded rather than assumed.
"""

from __future__ import annotations

from decimal import Decimal
from functools import cache

import pytest

from insulation_coordination.calculation.impulse_override import (
    HF_TRANSFORMER_WARNING,
    SPD_MONITORING_UNSTATED_WARNING,
    SPD_REDUCTION_WARNING,
    OverrideRefusalCode,
    PairImpulseOverride,
    resolve_impulse_override,
)
from insulation_coordination.calculation.supply_rules import (
    SPD_MAINS_ROUTE,
    SupplyRuleSet,
    read_supply_rules,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass, InsulationType
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.supply_topologies import (
    ENCLOSURE,
    NO_ISOLATION,
    VERIFIED,
    circuit_id,
    pair_between,
    supply_topology,
)
from tests.fixtures.synthetic_rules import synthetic_supply_rule_package

#: Above the synthetic attenuation rule's own invented frequency threshold, and below it.
ACCEPTED_HZ = Decimal(5000)
REFUSED_HZ = Decimal(50)


@cache
def _rules() -> SupplyRuleSet:
    return read_supply_rules(synthetic_supply_rule_package())


@pytest.fixture
def rules() -> SupplyRuleSet:
    return _rules()


def _without(package: RulePackage, rule_id: str) -> SupplyRuleSet:
    return read_supply_rules(
        package.model_copy(
            update={"decisions": tuple(item for item in package.decisions if item.id != rule_id)}
        )
    )


def _device(**overrides: object) -> VerifiedImpulseOverride:
    fields: dict[str, object] = {
        "value_v": Decimal(120),
        "basis": ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
        "verification_method": ReductionVerificationMethod.TEST,
        "justification": "Synthetic reduction",
        "evidence_reference": "SYN-SPD-1",
        "affected_location": "the limiter at the input terminals",
        "spd_device_placement": SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        "spd_device_degradable": False,
    }
    fields.update(overrides)
    return VerifiedImpulseOverride(**fields)


def _transformer(**overrides: object) -> VerifiedImpulseOverride:
    fields: dict[str, object] = {
        "value_v": Decimal(120),
        "basis": ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER,
        "verification_method": ReductionVerificationMethod.TEST,
        "justification": "Synthetic attenuation",
        "evidence_reference": "SYN-HF-1",
        "affected_location": "the secondary winding",
        "transformer_frequency_hz": ACCEPTED_HZ,
    }
    fields.update(overrides)
    return VerifiedImpulseOverride(**fields)


def _resolve(
    project: Project,
    pair: PairCase,
    override: VerifiedImpulseOverride,
    rules: SupplyRuleSet,
    *,
    insulation_type: InsulationType | None = InsulationType.BASIC,
    mains_supplied: bool = True,
) -> object:
    return resolve_impulse_override(
        project,
        pair,
        PairImpulseOverride(pair_id=pair.id, override=override),
        rules,
        derived_impulse_v=Decimal(500),
        insulation_type=insulation_type,
        mains_supplied=mains_supplied,
    )


# --- a claim that needs no rule ------------------------------------------------------------


def test_a_conservative_increase_applies_without_consulting_anything(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)
    increase = VerifiedImpulseOverride(
        value_v=Decimal(9000),
        basis=ImpulseOverrideBasis.CONSERVATIVE_INCREASE,
        verification_method=ReductionVerificationMethod.CALCULATION,
        justification="Synthetic conservative increase",
        evidence_reference="",
        affected_location="the whole assembly's input",
    )

    outcome = _resolve(project, pair, increase, rules)

    assert outcome.applied
    assert outcome.effective_impulse_v == Decimal(9000)
    assert outcome.warnings == ()
    assert outcome.spd_monitoring_dependency is None
    assert outcome.trace_steps and outcome.trace_steps[0].output.value == Decimal(9000)


def test_a_verified_circuit_characteristic_applies_and_records_why(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)
    characteristic = VerifiedImpulseOverride(
        value_v=Decimal(200),
        basis=ImpulseOverrideBasis.VERIFIED_CIRCUIT_CHARACTERISTIC,
        verification_method=ReductionVerificationMethod.SIMULATION,
        justification="Synthetic circuit characteristic",
        evidence_reference="SYN-CIRC-1",
        affected_location="the filtered node",
    )

    outcome = _resolve(project, pair, characteristic, rules)

    assert outcome.applied
    assert "the filtered node" in outcome.trace_steps[0].reason
    assert "500" in outcome.trace_steps[0].substituted


# --- a limiting device ----------------------------------------------------------------------


def test_a_device_reduction_always_carries_its_obligations(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(), rules)

    assert outcome.applied
    warning = next(item for item in outcome.warnings if item.code == SPD_REDUCTION_WARNING)
    assert "impulse withstand test" in warning.message
    assert "degrades in service" in warning.message
    assert ids.TEST_INTERNAL_SPD_MONITORING in warning.message
    assert warning.semantic_rule_id == ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS


def test_no_other_basis_carries_that_warning(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(project, pair, _transformer(), rules)

    assert SPD_REDUCTION_WARNING not in {item.code for item in outcome.warnings}


def test_an_internal_device_records_the_type_test_issue_37_generates(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    dependency = _resolve(project, pair, _device(), rules).spd_monitoring_dependency

    assert dependency is not None
    assert dependency.pair_id == pair.id
    assert dependency.affected_location == "the limiter at the input terminals"
    assert dependency.device_placement is SpdDevicePlacement.INTERNAL_TO_EQUIPMENT
    assert dependency.required_type_test_semantic_id == ids.TEST_INTERNAL_SPD_MONITORING
    assert dependency.monitoring_rule_ids == (
        f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
    )
    assert dependency.monitoring_required
    assert dependency.status_indication_required


def test_a_degradable_device_also_asks_the_reduction_clause(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(spd_device_degradable=True), rules)

    dependency = outcome.spd_monitoring_dependency
    assert outcome.applied
    assert dependency is not None
    assert dependency.device_degradable
    assert dependency.monitoring_required and dependency.status_indication_required
    assert f"{SPD_MAINS_ROUTE}.device_monitoring" in dependency.monitoring_rule_ids


def test_a_degradable_device_blocks_when_the_clause_states_nothing_about_one() -> None:
    package = synthetic_supply_rule_package()
    rules = _without(package, f"{SPD_MAINS_ROUTE}.device_monitoring")
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(spd_device_degradable=True), rules)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [OverrideRefusalCode.MONITORING_UNSTATED]
    assert outcome.spd_monitoring_dependency is None


def test_an_internal_device_blocks_when_no_monitoring_is_stated_at_all() -> None:
    package = synthetic_supply_rule_package()
    monitoring = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"
    emptied = tuple(
        item.model_copy(update={"rows": ()}) if item.id == monitoring else item
        for item in package.decisions
    )
    rules = read_supply_rules(package.model_copy(update={"decisions": emptied}))
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(), rules)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [OverrideRefusalCode.MONITORING_UNSTATED]


def test_an_external_device_the_package_is_silent_about_still_applies_and_says_so(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(
        project,
        pair,
        _device(spd_device_placement=SpdDevicePlacement.EXTERNAL_TO_EQUIPMENT),
        rules,
    )

    assert outcome.applied
    assert outcome.spd_monitoring_dependency is None
    silence = next(
        item for item in outcome.warnings if item.code == SPD_MONITORING_UNSTATED_WARNING
    )
    assert "Nothing here concludes that none is owed" in silence.message


def test_a_device_reduction_needs_the_pair_insulation_class(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(), rules, insulation_type=None)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [
        OverrideRefusalCode.INSULATION_CLASS_UNRESOLVED
    ]


def test_a_reduction_basis_stating_a_higher_value_is_flagged(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary",))
    pair = pair_between(project, circuit_id(0), ENCLOSURE)

    outcome = _resolve(project, pair, _device(value_v=Decimal(4000)), rules)

    assert outcome.applied
    assert "supply_override_above_derived" in {item.code for item in outcome.warnings}


# --- a high-frequency isolation transformer --------------------------------------------------


def test_the_attenuation_needs_a_verified_barrier_between_the_two_sides(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, NO_ISOLATION),))
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(project, pair, _transformer(), rules)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [OverrideRefusalCode.NO_VERIFIED_BARRIER]


def test_the_attenuation_applies_across_a_verified_barrier_the_package_permits(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(project, pair, _transformer(), rules)

    assert outcome.applied
    assert outcome.effective_impulse_v == Decimal(120)
    warning = next(item for item in outcome.warnings if item.code == HF_TRANSFORMER_WARNING)
    assert "not on the one-level transfer" in warning.message
    assert "SYN-HF-1" in warning.message
    assert ids.SUPPLY_HF_TRANSFORMER_ATTENUATION in outcome.source_rule_ids


def test_a_frequency_the_package_does_not_accept_is_refused(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(project, pair, _transformer(transformer_frequency_hz=REFUSED_HZ), rules)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [OverrideRefusalCode.ATTENUATION_UNSTATED]


def test_a_showing_the_package_does_not_accept_is_refused(rules: SupplyRuleSet) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(
        project,
        pair,
        _transformer(verification_method=ReductionVerificationMethod.CALCULATION),
        rules,
    )

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [
        OverrideRefusalCode.EVIDENCE_KIND_UNSUPPORTED
    ]


def test_an_unevaluated_circuit_class_is_refused_rather_than_assumed(
    rules: SupplyRuleSet,
) -> None:
    project = supply_topology(("Primary", "Secondary"), ((0, 1, VERIFIED),))
    unevaluated = tuple(
        net.model_copy(update={"decisive_voltage_class": DecisiveVoltageClass.NOT_EVALUATED})
        if net.id == circuit_id(1)
        else net
        for net in project.net_classes
    )
    project = project.model_copy(update={"net_classes": unevaluated})
    pair = pair_between(project, circuit_id(0), circuit_id(1))

    outcome = _resolve(project, pair, _transformer(), rules)

    assert not outcome.applied
    assert [item.code for item in outcome.refusals] == [
        OverrideRefusalCode.CIRCUIT_CLASS_UNEVALUATED
    ]
