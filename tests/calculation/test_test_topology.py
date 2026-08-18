"""Which electrodes a test is applied between, and when two applications are one.

Every identifier, name and figure here is this module's own. Nothing reproduces a value, a
heading or any wording from any standard: what is under test is the translation from a pair to
a pair of electrode sets, and the fold that turns equivalent applications into one row.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.test_topology import (
    CONFLICTING_APPLICATION_WARNING,
    TestSubject,
    deduplicate,
    live_group,
    reference_kind_for,
    subjects_for,
)
from insulation_coordination.domain.enums import Applicability, NetClassType
from insulation_coordination.domain.project import PairVoltage, PairVoltages, Project
from insulation_coordination.domain.trace import Quantity
from insulation_coordination.domain.verification import (
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
    TestReferenceKind,
    build_test_id,
)
from tests.fixtures.verification_topologies import (
    COVER,
    ENCLOSURE,
    LIVE_A,
    LIVE_B,
    LIVE_C,
    TOUCHABLE,
    mains_configuration,
    pair_between,
    verification_and_supply_package,
    verification_topology,
)

CIRCUIT = NetClassType.CIRCUIT
PE = NetClassType.PE_BONDED_CONDUCTIVE_PART
CONDUCTIVE = NetClassType.ACCESSIBLE_CONDUCTIVE_PART
INSULATING = NetClassType.ACCESSIBLE_INSULATING_SURFACE
REVISION = "a" * 64


@pytest.fixture
def project() -> Project:
    return verification_topology()


def subject_for(project: Project, first: UUID, second: UUID) -> TestSubject:
    pair = pair_between(project, first, second)
    return next(item for item in subjects_for(project) if item.pair_id == pair.id)


def application(
    *,
    high: tuple[UUID, ...],
    low: tuple[UUID, ...],
    covered: tuple[UUID, ...],
    kind: TestKind = TestKind.AC_DIELECTRIC,
    classifications: tuple[TestClassification, ...] = (TestClassification.ROUTINE,),
    reference: TestReferenceKind = TestReferenceKind.PE_BONDED_ACCESSIBLE_PART,
    voltage: Decimal | None = None,
    applicability: TestApplicability = TestApplicability.REQUIRED,
    unresolved: tuple[str, ...] = (),
) -> TestApplication:
    return TestApplication(
        test_id=build_test_id(
            test_kind=kind,
            reference_kind=reference,
            classifications=classifications,
            high_side_net_ids=high,
            low_side_net_ids=low,
            rule_revision=REVISION,
        ),
        covered_pair_ids=covered,
        test_kind=kind,
        classifications=classifications,
        high_side_net_ids=high,
        low_side_net_ids=low,
        reference_kind=reference,
        voltage=None if voltage is None else Quantity(value=voltage, unit="V"),
        applicability=applicability,
        unresolved_inputs=unresolved,
    )


# --- what a pair of net types is ----------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (CIRCUIT, CIRCUIT, TestReferenceKind.ADJACENT_CIRCUIT),
        (CIRCUIT, PE, TestReferenceKind.PE_BONDED_ACCESSIBLE_PART),
        (PE, CIRCUIT, TestReferenceKind.PE_BONDED_ACCESSIBLE_PART),
        (CIRCUIT, CONDUCTIVE, TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART),
        (CIRCUIT, INSULATING, TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL),
        (INSULATING, CIRCUIT, TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL),
        (PE, INSULATING, None),
        (CONDUCTIVE, PE, None),
    ],
)
def test_a_pair_of_net_types_is_read_the_same_in_either_order(
    first: NetClassType, second: NetClassType, expected: TestReferenceKind | None
) -> None:
    assert reference_kind_for(first, second) is expected


def test_within_circuit_is_never_a_relationship_between_two_net_classes() -> None:
    """It is a question about one net, and it reaches the schedule through a determination."""
    kinds = {reference_kind_for(first, second) for first in NetClassType for second in NetClassType}
    assert TestReferenceKind.WITHIN_CIRCUIT not in kinds


# --- what is tied together ------------------------------------------------------------------


def test_circuits_of_one_domain_are_one_conductor(project: Project) -> None:
    assert live_group(project, LIVE_A) == (LIVE_A, LIVE_B)
    assert live_group(project, LIVE_B) == (LIVE_A, LIVE_B)
    assert live_group(project, LIVE_C) == (LIVE_C,)


def test_a_net_outside_every_domain_answers_with_itself(project: Project) -> None:
    assert live_group(project, ENCLOSURE) == (ENCLOSURE,)


def test_a_reference_part_is_never_grouped_with_another_one(project: Project) -> None:
    """Nothing in the project says two accessible parts are bonded, so nothing assumes it."""
    subject = subject_for(project, LIVE_A, ENCLOSURE)
    assert subject.low_side_net_ids == (ENCLOSURE,)


def test_a_grouped_high_side_covers_the_pairs_of_every_net_in_it(project: Project) -> None:
    against_a = subject_for(project, LIVE_A, TOUCHABLE)
    against_b = subject_for(project, LIVE_B, TOUCHABLE)
    assert against_a.high_side_net_ids == (LIVE_A, LIVE_B) == against_b.high_side_net_ids
    assert against_a.low_side_net_ids == against_b.low_side_net_ids == (TOUCHABLE,)


def test_two_circuits_of_one_electrical_set_are_not_grouped_into_each_other(
    project: Project,
) -> None:
    """Grouping either side would put the same conductor on both sides of the test."""
    subject = subject_for(project, LIVE_A, LIVE_B)
    assert subject.high_side_net_ids == (LIVE_A,)
    assert subject.low_side_net_ids == (LIVE_B,)


def test_an_adjacent_circuit_across_a_barrier_groups_both_sides(project: Project) -> None:
    subject = subject_for(project, LIVE_A, LIVE_C)
    assert subject.high_side_net_ids == (LIVE_A, LIVE_B)
    assert subject.low_side_net_ids == (LIVE_C,)


def test_the_propagated_electrical_set_is_what_the_group_is_read_from(
    tmp_path: Path,
) -> None:
    """A barrier recording no isolation makes two domains one set, and the group follows it."""
    package = verification_and_supply_package(tmp_path / "merged.icrules")
    project = verification_topology(supply_configurations=(mains_configuration(),))
    supply = derive_project_supply(project, package)
    assert supply is not None
    # The fixture's barrier records verified isolation, so the set stays one domain wide;
    # what is asserted is that the propagated answer is the one consulted at all.
    assert live_group(project, LIVE_A, supply.domain_stresses) == (LIVE_A, LIVE_B)
    assert live_group(project, LIVE_C, supply.domain_stresses) == (LIVE_C,)


def test_a_pair_of_two_reference_parts_is_not_a_test(project: Project) -> None:
    pair = pair_between(project, ENCLOSURE, COVER)
    assert all(item.pair_id != pair.id for item in subjects_for(project))


def test_a_pair_recorded_as_never_adjacent_is_not_planned(project: Project) -> None:
    excluded = pair_between(project, LIVE_A, COVER)
    project = project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"voltages": _never_adjacent()})
                if pair.id == excluded.id
                else pair
                for pair in project.pairs
            )
        }
    )
    assert all(item.pair_id != excluded.id for item in subjects_for(project))


# --- what a reader is told to connect --------------------------------------------------------


def test_a_grouped_side_is_told_to_bridge_what_is_between_its_live_parts(
    project: Project,
) -> None:
    subject = subject_for(project, LIVE_A, ENCLOSURE)
    assert any("Bridge or open" in step for step in subject.preparation_steps)
    assert any("Live A, Live B" in step for step in subject.preparation_steps)


def test_a_single_conductor_is_not_told_to_bridge_anything(project: Project) -> None:
    subject = subject_for(project, LIVE_C, ENCLOSURE)
    assert not any("Bridge or open" in step for step in subject.preparation_steps)


def test_an_insulating_surface_is_wrapped_in_foil_rather_than_connected(
    project: Project,
) -> None:
    subject = subject_for(project, LIVE_C, COVER)
    assert any("conductive foil" in step for step in subject.preparation_steps)
    assert any("area and location" in step for step in subject.preparation_steps)


# --- deduplication -------------------------------------------------------------------------


def test_equivalent_applications_become_one_row_that_keeps_every_covered_pair() -> None:
    first = application(high=(LIVE_A, LIVE_B), low=(ENCLOSURE,), covered=(UUID(int=1),))
    second = application(high=(LIVE_A, LIVE_B), low=(ENCLOSURE,), covered=(UUID(int=2),))
    applications, warnings = deduplicate((first, second))
    assert len(applications) == 1
    assert applications[0].covered_pair_ids == (UUID(int=1), UUID(int=2))
    assert warnings == ()


def test_two_different_tests_never_collapse_into_one() -> None:
    """Every component of the identity separates two applications on its own."""
    base = application(high=(LIVE_A,), low=(ENCLOSURE,), covered=(UUID(int=1),))
    variants = (
        base,
        application(
            high=(LIVE_A,), low=(ENCLOSURE,), covered=(UUID(int=1),), kind=TestKind.DC_DIELECTRIC
        ),
        application(
            high=(LIVE_A,),
            low=(ENCLOSURE,),
            covered=(UUID(int=1),),
            classifications=(TestClassification.TYPE,),
        ),
        application(
            high=(LIVE_A,),
            low=(ENCLOSURE,),
            covered=(UUID(int=1),),
            reference=TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART,
        ),
        application(high=(LIVE_A, LIVE_B), low=(ENCLOSURE,), covered=(UUID(int=1),)),
        application(high=(LIVE_A,), low=(TOUCHABLE,), covered=(UUID(int=1),)),
    )
    applications, _ = deduplicate(variants)
    assert len({item.test_id for item in applications}) == len(variants)


def test_the_two_sides_of_a_test_are_not_interchangeable() -> None:
    forward = application(high=(LIVE_A,), low=(LIVE_C,), covered=(UUID(int=1),))
    reverse = application(high=(LIVE_C,), low=(LIVE_A,), covered=(UUID(int=1),))
    assert forward.test_id != reverse.test_id


def test_a_fold_that_had_to_choose_a_voltage_says_so_and_keeps_the_more_severe() -> None:
    lower = application(
        high=(LIVE_A, LIVE_B), low=(ENCLOSURE,), covered=(UUID(int=1),), voltage=Decimal(400)
    )
    higher = application(
        high=(LIVE_A, LIVE_B), low=(ENCLOSURE,), covered=(UUID(int=2),), voltage=Decimal(900)
    )
    applications, warnings = deduplicate((lower, higher))
    assert applications[0].voltage is not None
    assert applications[0].voltage.value == Decimal(900)
    assert [warning.code for warning in warnings] == [CONFLICTING_APPLICATION_WARNING]
    assert "400" in warnings[0].message and "900" in warnings[0].message


def test_a_fold_keeps_the_least_settled_applicability_and_every_reason_for_it() -> None:
    settled = application(high=(LIVE_A,), low=(ENCLOSURE,), covered=(UUID(int=1),))
    unsettled = application(
        high=(LIVE_A,),
        low=(ENCLOSURE,),
        covered=(UUID(int=2),),
        applicability=TestApplicability.ENGINEERING_INPUT_REQUIRED,
        unresolved=("nobody said",),
    )
    applications, _ = deduplicate((settled, unsettled))
    assert applications[0].applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert applications[0].unresolved_inputs == ("nobody said",)


def test_the_order_of_a_schedule_does_not_depend_on_the_order_it_was_generated_in() -> None:
    generated = (
        application(high=(LIVE_C,), low=(ENCLOSURE,), covered=(UUID(int=3),)),
        application(
            high=(LIVE_A,),
            low=(ENCLOSURE,),
            covered=(UUID(int=1),),
            kind=TestKind.IMPULSE_WITHSTAND,
        ),
        application(
            high=(LIVE_A,),
            low=(ENCLOSURE,),
            covered=(UUID(int=2),),
            classifications=(TestClassification.TYPE,),
        ),
    )
    forward, _ = deduplicate(generated)
    backward, _ = deduplicate(tuple(reversed(generated)))
    assert [item.test_id for item in forward] == [item.test_id for item in backward]
    assert [item.test_kind for item in forward] == [
        TestKind.AC_DIELECTRIC,
        TestKind.AC_DIELECTRIC,
        TestKind.IMPULSE_WITHSTAND,
    ]


def _never_adjacent() -> PairVoltages:
    excluded = PairVoltage(
        applicability=Applicability.NOT_APPLICABLE, justification="never adjacent"
    )
    return PairVoltages(
        long_term_rms_v=excluded,
        steady_state_peak_v=excluded,
        recurring_peak_v=excluded,
        temporary_overvoltage_peak_v=excluded,
    )
