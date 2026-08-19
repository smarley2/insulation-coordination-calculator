"""Five equipment topologies, and what each one proves the verification plan handles.

Every figure, name and reference here comes from ``tests.fixtures.verification_projects`` and
is this repository's own invention. Nothing reproduces a value, a heading, a note or any
wording from any standard.

The routing tests beside this module work one general project hard. These work five specific
ones once each, because a plan that answers a wireless charger and a variable speed drive the
same way is not answering either of them.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.verification_plan import (
    SPD_MONITORING_OWED_WARNING,
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.domain.project import Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.verification import (
    TestApplicability,
    TestApplication,
    TestKind,
    TestReferenceKind,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.verification_projects import (
    CHARGER_HOUSING,
    CHARGER_RECEIVER,
    CHARGER_TRANSMITTER,
    DRIVE_DC_LINK,
    DRIVE_ENCLOSURE,
    DRIVE_INPUT,
    DRIVE_OUTPUT,
    LOWER_SYSTEM_VOLTAGE_V,
    SPD_DOWNSTREAM,
    SPD_ENCLOSURE,
    SPD_INPUT,
    SURFACE_CIRCUIT,
    SURFACE_ENCLOSURE,
    SURFACE_HANDLE,
    SURFACE_WINDOW,
    accessible_surfaces,
    multi_supply,
    pair_between,
    protected_pair,
    surge_protected_input,
    variable_speed_drive,
    wireless_charger,
)
from tests.fixtures.verification_topologies import (
    SYSTEM_VOLTAGE_V,
    verification_and_supply_package,
)


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    return verification_and_supply_package(tmp_path / "merged.icrules")


def build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


def rows(
    plan: VerificationPlan,
    kind: TestKind,
    *,
    high: tuple[UUID, ...] | None = None,
    low: tuple[UUID, ...] | None = None,
) -> tuple[TestApplication, ...]:
    return tuple(
        item
        for item in plan.test_applications
        if item.test_kind is kind
        and (high is None or item.high_side_net_ids == high)
        and (low is None or item.low_side_net_ids == low)
    )


def dielectric_family(application: TestApplication) -> str:
    """Which of the two dielectric table families answered this row."""

    families = {
        family
        for family in (
            ids.TEST_MAINS_DIELECTRIC_VALUES,
            ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
        )
        for rule_id in application.source_rule_ids
        if rule_id.startswith(family)
    }
    assert len(families) == 1, application.source_rule_ids
    return families.pop()


# --- wireless charger -------------------------------------------------------------------


def test_a_basic_insulation_project_is_outside_the_partial_discharge_clause(
    package: RulePackage,
) -> None:
    """Every pair of this charger selected basic insulation, and the clause names two others.

    The review this project also owes for operating above the high-frequency boundary is raised
    where its insulation is dimensioned, against the annex that governs clearance, creepage
    distance and solid insulation together - see ``tests/calculation/test_engine.py``. It is
    not a property of the partial-discharge test, whose procedure is specified at power
    frequency.
    """

    plan = build(wireless_charger(), package)

    discharge = rows(plan, TestKind.PARTIAL_DISCHARGE)
    assert discharge
    assert all(item.applicability is TestApplicability.NOT_APPLICABLE for item in discharge)
    assert all(item.unresolved_inputs == () for item in discharge)


def test_a_coupling_nobody_verified_lets_no_impulse_through(package: RulePackage) -> None:
    """An unevaluated barrier is not isolation and it is not a conductor either.

    Neither side may be planned at a figure the derivation could not establish, so every
    impulse row on this project is an engineering input rather than a number.
    """

    plan = build(wireless_charger(), package)

    impulse = rows(plan, TestKind.IMPULSE_WITHSTAND)
    assert impulse
    for item in impulse:
        assert item.voltage is None
        assert item.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
        assert item.unresolved_inputs


def test_the_two_coils_are_two_live_groups_and_read_two_routes(package: RulePackage) -> None:
    """The mains-connected transmitter and the receiver behind the coupling are not one set."""

    plan = build(wireless_charger(), package)

    transmitter = rows(
        plan, TestKind.AC_DIELECTRIC, high=(CHARGER_TRANSMITTER,), low=(CHARGER_HOUSING,)
    )
    receiver = rows(plan, TestKind.AC_DIELECTRIC, high=(CHARGER_RECEIVER,), low=(CHARGER_HOUSING,))
    assert transmitter and receiver
    assert dielectric_family(transmitter[0]) == ids.TEST_MAINS_DIELECTRIC_VALUES
    assert dielectric_family(receiver[0]) == ids.TEST_NON_MAINS_DIELECTRIC_VALUES


# --- variable speed drive ---------------------------------------------------------------


def test_a_drive_with_no_barrier_tests_its_three_circuits_as_one_group(
    package: RulePackage,
) -> None:
    """Nothing isolates the input, the DC link and the output, so one row covers all three."""

    project = variable_speed_drive()
    plan = build(project, package)

    enclosure = rows(
        plan,
        TestKind.AC_DIELECTRIC,
        high=(DRIVE_INPUT, DRIVE_DC_LINK, DRIVE_OUTPUT),
        low=(DRIVE_ENCLOSURE,),
    )
    assert enclosure
    covered = {
        pair_between(project, net, DRIVE_ENCLOSURE).id
        for net in (DRIVE_INPUT, DRIVE_DC_LINK, DRIVE_OUTPUT)
    }
    for item in enclosure:
        assert set(item.covered_pair_ids) == covered
        assert item.reference_kind is TestReferenceKind.PE_BONDED_ACCESSIBLE_PART


def test_a_mains_input_makes_the_whole_undivided_domain_mains_connected(
    package: RulePackage,
) -> None:
    """The DC link is not isolated from the input, so its test is keyed on the same source."""

    plan = build(variable_speed_drive(), package)

    internal = rows(plan, TestKind.AC_DIELECTRIC, high=(DRIVE_DC_LINK,), low=(DRIVE_OUTPUT,))
    assert internal
    assert dielectric_family(internal[0]) == ids.TEST_MAINS_DIELECTRIC_VALUES
    assert all(assessment.mains_connected for assessment in plan.pair_assessments)


# --- multiple sources --------------------------------------------------------------------


def test_a_circuit_on_two_sources_is_planned_at_the_more_severe(package: RulePackage) -> None:
    project = multi_supply()

    plan = build(project, package)
    single_source = build(
        project.model_copy(update={"supply_configurations": project.supply_configurations[:1]}),
        package,
    )
    lowered = build(
        project.model_copy(update={"supply_configurations": project.supply_configurations[1:]}),
        package,
    )

    both = rows(plan, TestKind.AC_DIELECTRIC)[0]
    higher = rows(single_source, TestKind.AC_DIELECTRIC)[0]
    lower = rows(lowered, TestKind.AC_DIELECTRIC)[0]
    assert both.voltage is not None and lower.voltage is not None
    assert higher.voltage is not None
    assert LOWER_SYSTEM_VOLTAGE_V < SYSTEM_VOLTAGE_V
    assert lower.voltage.value < both.voltage.value
    assert both.voltage.value == higher.voltage.value


def test_every_arrangement_that_could_govern_is_named_in_the_trace(
    package: RulePackage,
) -> None:
    project = multi_supply()

    plan = build(project, package)

    application = rows(plan, TestKind.AC_DIELECTRIC)[0]
    said = " ".join(f"{step.reason} {step.substituted}" for step in application.trace_steps)
    for configuration in project.supply_configurations:
        assert configuration.name in said


# --- internal surge protective device -----------------------------------------------------


def test_a_reduction_a_device_underwrites_schedules_its_monitoring_test(
    package: RulePackage,
) -> None:
    project = surge_protected_input()

    plan = build(project, package)

    monitoring = rows(plan, TestKind.INTERNAL_SPD_MONITORING)
    assert len(monitoring) == 1
    assert monitoring[0].covered_pair_ids == (protected_pair(project).id,)
    assert monitoring[0].applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert SPD_MONITORING_OWED_WARNING in {warning.code for warning in plan.warnings}
    assert not plan.is_complete


def test_the_protected_pair_owes_both_its_insulation_test_and_the_reduction_s(
    package: RulePackage,
) -> None:
    """The reduction verification joins the schedule; it does not take a row out of it."""

    project = surge_protected_input()

    plan = build(project, package)

    protected = protected_pair(project)
    reduction = rows(plan, TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION)
    assert len(reduction) == 1
    assert reduction[0].covered_pair_ids == (protected.id,)
    assert reduction[0].applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    insulation = [
        item
        for item in rows(plan, TestKind.IMPULSE_WITHSTAND)
        if protected.id in item.covered_pair_ids
    ]
    assert len(insulation) == 1


def test_the_pair_without_the_reduction_owes_no_monitoring(package: RulePackage) -> None:
    project = surge_protected_input()

    plan = build(project, package)

    downstream = pair_between(project, SPD_DOWNSTREAM, SPD_ENCLOSURE)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == downstream.id)
    assert assessment.spd_monitoring_dependency is None
    protected = next(
        item for item in plan.pair_assessments if item.pair_id == protected_pair(project).id
    )
    assert protected.spd_monitoring_dependency is not None


def test_a_project_with_no_reduction_gets_no_monitoring_row(package: RulePackage) -> None:
    """The row exists for a reduction, not for the presence of a device nobody relied on."""

    project = surge_protected_input()
    without = project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"impulse_override": None}) for pair in project.pairs
            )
        }
    )

    assert rows(build(without, package), TestKind.INTERNAL_SPD_MONITORING) == ()


def test_one_pair_s_reduction_does_not_lower_its_group_s_test(package: RulePackage) -> None:
    project = surge_protected_input()

    plan = build(project, package)

    group = rows(
        plan,
        TestKind.IMPULSE_WITHSTAND,
        high=(SPD_INPUT, SPD_DOWNSTREAM),
        low=(SPD_ENCLOSURE,),
    )
    assert group
    assert group[0].voltage is not None
    assert group[0].voltage.value > Decimal(50)


# --- accessible surfaces -------------------------------------------------------------------


def test_three_reference_kinds_stay_three_rows(package: RulePackage) -> None:
    plan = build(accessible_surfaces(), package)

    kinds = {
        item.reference_kind for item in rows(plan, TestKind.AC_DIELECTRIC, high=(SURFACE_CIRCUIT,))
    }
    assert kinds == {
        TestReferenceKind.PE_BONDED_ACCESSIBLE_PART,
        TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART,
        TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL,
    }


def test_only_the_insulating_surface_asks_for_conductive_foil(package: RulePackage) -> None:
    """A foil wrap is how a test against an insulating surface exists at all, and only that."""

    plan = build(accessible_surfaces(), package)

    by_low = {
        item.low_side_net_ids: item
        for item in rows(plan, TestKind.AC_DIELECTRIC, high=(SURFACE_CIRCUIT,))
        if item.classifications
    }
    window = by_low[(SURFACE_WINDOW,)]
    assert any("foil" in step.lower() for step in window.preparation_steps)
    for net in (SURFACE_ENCLOSURE, SURFACE_HANDLE):
        other = by_low[(net,)]
        assert not any("foil" in step.lower() for step in other.preparation_steps)
        assert len(other.preparation_steps) < len(window.preparation_steps)
