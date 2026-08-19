"""Which recorded voltage governs, and what a working-voltage plan asks for.

Every figure, reference and condition here is this module's own. Nothing reproduces a value,
a table or any wording from any standard: what is under test is the selection rule and the
plan's shape, neither of which the source states.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from insulation_coordination.calculation.verification_rules import (
    VerificationRuleSet,
    read_verification_rules,
)
from insulation_coordination.calculation.voltage_evidence import (
    CLASS_LIMIT_CONDITIONS,
    CLASS_LIMIT_STEP,
    OPERATING_CONDITIONS,
    WORKING_VOLTAGE_QUANTITIES,
    VoltageEvidenceService,
    plan_working_voltage,
)
from insulation_coordination.domain.enums import CircuitSourceRelationship
from insulation_coordination.domain.project import PairVoltage, PairVoltages, Project
from insulation_coordination.domain.supply import (
    EarthingArrangement,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyKind,
)
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    EvidenceTarget,
    VerificationStatus,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
    WorkingVoltageDetermination,
)
from tests.fixtures.supply_topologies import COVER, ENCLOSURE, circuit_id, supply_topology
from tests.fixtures.synthetic_rules import synthetic_verification_rule_package
from tests.fixtures.verification_topologies import with_protection_matrix

RECORDED_AT = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
AC = VoltageQuantityKind.AC_RMS
PEAK = VoltageQuantityKind.RECURRING_PEAK
APPROVED = EvidenceApprovalState.APPROVED_FOR_DESIGN
DRAFT = EvidenceApprovalState.DRAFT
SUPERSEDED = EvidenceApprovalState.SUPERSEDED_WITH_JUSTIFICATION
ESTIMATE = VoltageEvidenceMethod.ENGINEERING_ESTIMATE
MEASUREMENT = VoltageEvidenceMethod.MEASUREMENT


@pytest.fixture
def rules() -> VerificationRuleSet:
    return read_verification_rules(with_protection_matrix(synthetic_verification_rule_package()))


@pytest.fixture
def project() -> Project:
    """Two circuits, a PE-bonded enclosure and an insulating cover, on two supply rows."""
    return supply_topology(
        ["Input", "Output"],
        sources={
            0: CircuitSourceRelationship.MAINS_CONNECTED,
            1: CircuitSourceRelationship.INTERNALLY_GENERATED,
        },
    ).model_copy(update={"supply_configurations": _configurations()})


def _configurations() -> tuple[SupplyConfiguration, ...]:
    """One enabled row and one disabled one. Both entirely this module's invention."""
    return (
        SupplyConfiguration(
            id=UUID(int=61),
            enabled=True,
            name="Site supply",
            supply_kind=SupplyKind.AC_MAINS,
            nominal_voltage_v=Decimal(17),
            phase_system=PhaseSystem.THREE_PHASE,
            earthing_arrangement=EarthingArrangement.TN_STAR_POINT_EARTHED,
            overvoltage_category=OvervoltageCategory.III,
            input_topology=InputTopology.DIRECT_INPUT,
        ),
        SupplyConfiguration(
            id=UUID(int=62),
            enabled=False,
            name="Bench supply",
            supply_kind=SupplyKind.NON_MAINS_DC,
            nominal_voltage_v=Decimal(23),
            phase_system=None,
            earthing_arrangement=EarthingArrangement.NOT_APPLICABLE,
            overvoltage_category=None,
            input_topology=InputTopology.DIRECT_INPUT,
        ),
    )


def evidence(
    value: str,
    *,
    entry_id: int,
    target: EvidenceTarget,
    quantity: VoltageQuantityKind = AC,
    method: VoltageEvidenceMethod = ESTIMATE,
    state: EvidenceApprovalState = APPROVED,
) -> VoltageEvidence:
    measured = method is MEASUREMENT
    return VoltageEvidence(
        id=UUID(int=entry_id),
        pair_id=target.pair_id,
        net_id=target.net_id,
        quantity_kind=quantity,
        value_v=Decimal(value),
        method=method,
        operating_condition="normal operation",
        source_reference=f"REF-{entry_id}",
        measurement_points="at the terminals" if measured else "",
        tolerance_or_uncertainty="plus or minus one percent" if measured else "",
        recorded_at=RECORDED_AT,
        approval_state=state,
        approval_justification="the earlier figure was withdrawn" if state is SUPERSEDED else "",
    )


def with_evidence(project: Project, *entries: VoltageEvidence) -> Project:
    return project.model_copy(update={"voltage_evidence": entries})


def pair_target(project: Project, first: UUID, second: UUID) -> EvidenceTarget:
    key = "::".join(sorted((str(first), str(second))))
    return EvidenceTarget(pair_id=next(p.id for p in project.pairs if p.key == key))


def _for_target(
    determinations: tuple[WorkingVoltageDetermination, ...], target: EvidenceTarget
) -> WorkingVoltageDetermination:
    return next(item for item in determinations if item.target == target)


# --- applicable entries ---------------------------------------------------------------


def test_applicable_keeps_only_this_target_and_this_quantity(project: Project) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    other = EvidenceTarget(net_id=circuit_id(1))
    wanted = evidence("31", entry_id=1, target=target)
    populated = with_evidence(
        project,
        wanted,
        evidence("41", entry_id=2, target=other),
        evidence("51", entry_id=3, target=target, quantity=PEAK),
    )

    assert VoltageEvidenceService().applicable(populated, target, AC) == (wanted,)


def test_applicable_keeps_entries_that_are_not_allowed_to_govern(project: Project) -> None:
    """A draft and a superseded entry are still part of the record a reviewer reads."""
    target = EvidenceTarget(net_id=circuit_id(0))
    populated = with_evidence(
        project,
        evidence("31", entry_id=1, target=target, state=DRAFT),
        evidence("41", entry_id=2, target=target, state=SUPERSEDED),
    )

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert len(result.applicable) == 2
    assert result.governing == ()
    assert result.approved_value_v is None
    assert len(result.awaiting_approval) == 1
    assert len(result.superseded) == 1


# --- the governing value --------------------------------------------------------------


def test_the_highest_approved_value_governs(project: Project) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    highest = evidence("71", entry_id=2, target=target)
    populated = with_evidence(project, evidence("31", entry_id=1, target=target), highest)

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert result.governing == (highest,)
    assert result.approved_value_v == Decimal(71)
    assert result.effective_value_v == Decimal(71)
    assert result.unresolved_inputs == ()


def test_tied_approved_values_are_both_retained(project: Project) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    first = evidence("71", entry_id=1, target=target)
    second = evidence("71", entry_id=2, target=target, method=VoltageEvidenceMethod.CALCULATION)
    populated = with_evidence(project, first, second)

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert set(result.governing) == {first, second}
    assert result.approved_value_v == Decimal(71)
    assert "tied" in result.trace_steps[0].reason


def test_a_higher_draft_does_not_govern_and_is_reported(project: Project) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    approved = evidence("31", entry_id=1, target=target)
    populated = with_evidence(
        project, approved, evidence("91", entry_id=2, target=target, state=DRAFT)
    )

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert result.governing == (approved,)
    assert result.approved_value_v == Decimal(31)
    assert any("approved" in message for message in result.unresolved_inputs)


def test_a_lower_measurement_never_displaces_a_standing_approved_value(project: Project) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    design = evidence("71", entry_id=1, target=target)
    populated = with_evidence(
        project, design, evidence("31", entry_id=2, target=target, method=MEASUREMENT)
    )

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert result.governing == (design,)
    assert result.approved_value_v == Decimal(71)


def test_a_lower_measurement_governs_once_the_higher_value_is_superseded(
    project: Project,
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    measured = evidence("31", entry_id=2, target=target, method=MEASUREMENT)
    populated = with_evidence(
        project,
        evidence("71", entry_id=1, target=target, state=SUPERSEDED),
        measured,
    )

    result = VoltageEvidenceService().governing(populated, target, AC)

    assert result.governing == (measured,)
    assert result.approved_value_v == Decimal(31)
    assert "superseded" in result.trace_steps[0].reason


def test_no_evidence_at_all_is_reported_as_a_missing_input(project: Project) -> None:
    result = VoltageEvidenceService().governing(project, EvidenceTarget(net_id=circuit_id(0)), AC)

    assert result.approved_value_v is None
    assert result.effective_value_v is None
    assert result.trace_steps == ()
    assert any("no" in message.lower() for message in result.unresolved_inputs)


# --- the derived stress stays separate --------------------------------------------------


def test_a_derived_stress_is_compared_with_evidence_and_never_merged_into_it(
    project: Project,
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    populated = with_evidence(project, evidence("31", entry_id=1, target=target))

    result = VoltageEvidenceService().governing(
        populated, target, AC, derived_v=Decimal(88), derived_source="Site supply"
    )

    assert result.approved_value_v == Decimal(31)
    assert result.derived_value_v == Decimal(88)
    assert result.effective_value_v == Decimal(88)
    assert all(entry.value_v != Decimal(88) for entry in result.applicable)
    comparison = result.trace_steps[-1]
    assert "Site supply" in comparison.substituted
    assert comparison.output.value == Decimal(88)


def test_a_derived_stress_alone_produces_an_effective_value_but_no_governing_entry(
    project: Project,
) -> None:
    result = VoltageEvidenceService().governing(
        project, EvidenceTarget(net_id=circuit_id(0)), AC, derived_v=Decimal(88)
    )

    assert result.governing == ()
    assert result.effective_value_v == Decimal(88)
    assert result.trace_steps[-1].output.value == Decimal(88)


@given(
    values=st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=8),
    extra=st.integers(min_value=1, max_value=10_000),
)
def test_adding_an_approved_entry_never_lowers_the_effective_value(
    values: list[int], extra: int
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    base = supply_topology(["Input"])
    service = VoltageEvidenceService()
    entries = tuple(
        evidence(str(value), entry_id=index, target=target)
        for index, value in enumerate(values, start=1)
    )

    added = evidence(str(extra), entry_id=len(values) + 1, target=target)
    before = service.governing(with_evidence(base, *entries), target, AC)
    after = service.governing(with_evidence(base, *entries, added), target, AC)

    assert before.approved_value_v is not None and after.approved_value_v is not None
    assert after.approved_value_v >= before.approved_value_v
    assert after.approved_value_v == Decimal(max([*values, extra]))
    assert all(entry.value_v <= after.approved_value_v for entry in after.applicable)


# --- working-voltage determinations -----------------------------------------------------


def test_a_determination_is_planned_for_every_circuit_and_every_pair_touching_one(
    project: Project, rules: VerificationRuleSet
) -> None:
    determinations = plan_working_voltage(project, rules)

    net_targets = {item.target.net_id for item in determinations if item.target.net_id}
    pair_targets = {item.target.pair_id for item in determinations if item.target.pair_id}
    assert net_targets == {circuit_id(0), circuit_id(1)}
    assert pair_targets == {
        pair_target(project, circuit_id(0), circuit_id(1)).pair_id,
        pair_target(project, circuit_id(0), ENCLOSURE).pair_id,
        pair_target(project, circuit_id(1), ENCLOSURE).pair_id,
        pair_target(project, circuit_id(0), COVER).pair_id,
        pair_target(project, circuit_id(1), COVER).pair_id,
    }
    assert pair_target(project, ENCLOSURE, COVER).pair_id not in pair_targets


def test_a_pair_recorded_as_never_adjacent_is_not_planned(
    project: Project, rules: VerificationRuleSet
) -> None:
    excluded_id = pair_target(project, circuit_id(0), COVER).pair_id
    never = PairVoltage.not_applicable("never adjacent")
    populated = project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(
                    update={
                        "voltages": PairVoltages(
                            long_term_rms_v=never,
                            steady_state_peak_v=never,
                            recurring_peak_v=never,
                            temporary_overvoltage_peak_v=never,
                        )
                    }
                )
                if pair.id == excluded_id
                else pair
                for pair in project.pairs
            )
        }
    )

    determinations = plan_working_voltage(populated, rules)

    assert all(item.target.pair_id != excluded_id for item in determinations)


def test_a_determination_id_is_stable_across_recomputation_and_unique_per_target(
    project: Project, rules: VerificationRuleSet
) -> None:
    first = plan_working_voltage(project, rules)
    second = plan_working_voltage(project, rules)

    assert [item.id for item in first] == [item.id for item in second]
    assert len({item.id for item in first}) == len(first)


def test_a_determination_names_the_enabled_supply_rows_and_the_governing_procedure(
    project: Project, rules: VerificationRuleSet
) -> None:
    determination = plan_working_voltage(project, rules)[0]

    assert determination.supply_configuration_ids == (UUID(int=61),)
    assert determination.source_rule_ids == (rules.working_voltage_determination.id,)
    assert determination.required_quantities == WORKING_VOLTAGE_QUANTITIES
    assert determination.operating_conditions == OPERATING_CONDITIONS


def test_the_working_voltage_is_planned_under_the_rated_worst_case_alone(
    project: Project, rules: VerificationRuleSet
) -> None:
    """Abnormal operation and single fault are not operating conditions of this quantity.

    Listing them here raised the working voltage to a figure no clause asks a design to be
    dimensioned on, and it buried the determination they do belong to.
    """
    determination = plan_working_voltage(project, rules)[0]

    assert determination.operating_conditions == OPERATING_CONDITIONS
    assert not {"abnormal operation", "single fault"} & set(determination.operating_conditions)


def test_the_abnormal_and_single_fault_voltages_are_kept_as_their_own_quantity(
    project: Project, rules: VerificationRuleSet
) -> None:
    """Moved, not dropped: they are what the class limits and Table 3 are judged against."""
    determination = plan_working_voltage(project, rules)[0]

    assert determination.class_limit_conditions == CLASS_LIMIT_CONDITIONS
    assert set(determination.class_limit_conditions) == {"abnormal operation", "single fault"}
    assert CLASS_LIMIT_STEP in determination.preparation_steps


def test_a_determination_with_no_evidence_is_planned_and_lists_what_it_needs(
    project: Project, rules: VerificationRuleSet
) -> None:
    determination = plan_working_voltage(project, rules)[0]

    assert determination.status is VerificationStatus.PLANNED
    assert determination.expected_values == ()
    assert determination.measurement_points == ()
    assert len(determination.unresolved_inputs) >= len(WORKING_VOLTAGE_QUANTITIES)


def test_an_unapproved_entry_forces_review_rather_than_acting_approved(
    project: Project, rules: VerificationRuleSet
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    populated = with_evidence(project, evidence("91", entry_id=1, target=target, state=DRAFT))

    determination = _for_target(plan_working_voltage(populated, rules), target)

    assert determination.status is VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    assert determination.expected_values == ()
    assert any("approved" in message for message in determination.unresolved_inputs)


def test_partial_design_evidence_is_reported_as_design_evidence_with_the_rest_unresolved(
    project: Project, rules: VerificationRuleSet
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    entry = evidence("31", entry_id=1, target=target)
    populated = with_evidence(project, entry)

    determination = _for_target(plan_working_voltage(populated, rules), target)

    assert determination.status is VerificationStatus.DESIGN_EVIDENCE_AVAILABLE
    assert determination.expected_values == (entry,)
    assert len(determination.unresolved_inputs) == len(WORKING_VOLTAGE_QUANTITIES) - 1


def test_a_measurement_beside_a_design_value_reports_measured_not_complete(
    project: Project, rules: VerificationRuleSet
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    populated = with_evidence(
        project,
        *(
            evidence(str(30 + index), entry_id=index, target=target, quantity=quantity)
            for index, quantity in enumerate(WORKING_VOLTAGE_QUANTITIES, start=1)
        ),
        evidence("99", entry_id=9, target=target, quantity=AC, method=MEASUREMENT),
    )

    determination = _for_target(plan_working_voltage(populated, rules), target)

    assert determination.status is VerificationStatus.MEASURED
    assert determination.measurement_points == ("at the terminals",)


def test_a_measurement_for_every_required_quantity_completes_the_determination(
    project: Project, rules: VerificationRuleSet
) -> None:
    target = EvidenceTarget(net_id=circuit_id(0))
    populated = with_evidence(
        project,
        *(
            evidence(
                str(30 + index),
                entry_id=index,
                target=target,
                quantity=quantity,
                method=MEASUREMENT,
            )
            for index, quantity in enumerate(WORKING_VOLTAGE_QUANTITIES, start=1)
        ),
    )

    determination = _for_target(plan_working_voltage(populated, rules), target)

    assert determination.status is VerificationStatus.COMPLETE
    assert determination.expected_values == ()
    assert determination.unresolved_inputs == ()
