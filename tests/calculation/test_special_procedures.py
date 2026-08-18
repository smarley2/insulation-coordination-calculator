"""The three package procedures a schedule carries besides its tests.

Every name, reference and step here is this module's or its fixture's own. What is under test
is which rule was asked, what was done with the answer, and what happens when the package will
not answer at all - never a value or a wording from any standard.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.impulse_override import SpdMonitoringDependency
from insulation_coordination.calculation.special_procedures import (
    ELECTRICAL_TEST_KINDS,
    monitoring_preparation,
)
from insulation_coordination.calculation.verification_plan import (
    SPD_MONITORING_OWED_WARNING,
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
    TestReferenceKind,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.verification_topologies import (
    COVER,
    ENCLOSURE,
    LIVE_A,
    LIVE_B,
    declared_solid_insulation,
    mains_configuration,
    pair_between,
    verification_and_supply_package,
    verification_topology,
    with_pair_fields,
)

BASIC = ProtectionImplementation.BASIC_INSULATION
PRECONDITIONING_GATE = f"{ids.TEST_PRECONDITIONING}.applicability"
FOIL_GATE = f"{ids.TEST_ACCESSIBLE_SURFACE_FOIL}.applicability"


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    return verification_and_supply_package(
        tmp_path / "merged.icrules", partial_discharge_classifications=("type_test",)
    )


@pytest.fixture
def project() -> Project:
    return with_pair_fields(
        verification_topology(supply_configurations=(mains_configuration(),)),
        protection_implementation=BASIC,
        solid_insulation=declared_solid_insulation(),
    )


def build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


def rows_for(plan: VerificationPlan, pair: PairCase, kind: TestKind) -> tuple[TestApplication, ...]:
    return tuple(
        item
        for item in plan.test_applications
        if item.test_kind is kind and pair.id in item.covered_pair_ids
    )


def with_spd_reduction(project: Project, pair_id: UUID) -> Project:
    override = VerifiedImpulseOverride(
        value_v=Decimal(50),
        basis=ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
        verification_method=ReductionVerificationMethod.TEST,
        justification="Synthetic reduction for this test module.",
        evidence_reference="SYN-RED-1",
        affected_location="the primary to enclosure insulation",
        spd_device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        spd_device_degradable=True,
    )
    return with_pair_fields(project, pair_id, impulse_override=override)


# --- internal SPD monitoring -------------------------------------------------------------


def test_a_reduction_an_internal_device_justifies_produces_the_monitoring_test(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(with_spd_reduction(project, pair.id), package)
    rows = rows_for(plan, pair, TestKind.INTERNAL_SPD_MONITORING)
    assert len(rows) == 1
    assert ids.TEST_INTERNAL_SPD_MONITORING in rows[0].source_rule_ids
    assert TestClassification.TYPE in rows[0].classifications


def test_a_pair_with_no_reduction_gets_no_monitoring_test_at_all(
    project: Project, package: RulePackage
) -> None:
    """A device that justifies no reduction is not a device this schedule tests."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assert rows_for(build(project, package), pair, TestKind.INTERNAL_SPD_MONITORING) == ()


def test_the_monitoring_test_names_the_reduction_it_underwrites(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(with_spd_reduction(project, pair.id), package)
    row = rows_for(plan, pair, TestKind.INTERNAL_SPD_MONITORING)[0]
    assert any("the primary to enclosure insulation" in step for step in row.preparation_steps)
    assert any("degradable" in step for step in row.preparation_steps)


def test_the_monitoring_test_carries_every_step_the_package_states(
    project: Project, package: RulePackage
) -> None:
    """The simulated failure states and what each is expected to show are those steps."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(with_spd_reduction(project, pair.id), package)
    row = rows_for(plan, pair, TestKind.INTERNAL_SPD_MONITORING)[0]
    procedure = next(
        item for item in package.procedures if item.id == ids.TEST_INTERNAL_SPD_MONITORING
    )
    assert {step.text for step in procedure.procedure_steps} <= set(row.preparation_steps)


@pytest.mark.parametrize(
    ("indication", "expected"),
    [(True, "as well as detection"), (False, "requires no status indication")],
)
def test_what_the_reduction_asks_the_monitoring_to_show_is_stated_either_way(
    package: RulePackage, indication: bool, expected: str
) -> None:
    """Whether an indication is owed comes from the recorded dependency, not from this plan."""
    procedure = next(
        item for item in package.procedures if item.id == ids.TEST_INTERNAL_SPD_MONITORING
    )
    dependency = SpdMonitoringDependency(
        pair_id=UUID(int=1),
        affected_location="a synthetic location",
        device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        device_degradable=False,
        monitoring_required=True,
        status_indication_required=indication,
        verification_reference="synthetic_showing",
    )
    steps, rule_ids = monitoring_preparation(dependency, procedure)
    assert any(expected in step for step in steps)
    assert any("synthetic_showing" in step for step in steps)
    assert rule_ids[0] == ids.TEST_INTERNAL_SPD_MONITORING


def test_the_monitoring_test_keeps_the_plan_incomplete_until_it_is_acknowledged(
    project: Project, package: RulePackage
) -> None:
    """Scheduling it is not the same as somebody having agreed to perform it."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(with_spd_reduction(project, pair.id), package)
    row = rows_for(plan, pair, TestKind.INTERNAL_SPD_MONITORING)[0]
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("acknowledged" in item for item in row.unresolved_inputs)
    assert SPD_MONITORING_OWED_WARNING in {warning.code for warning in plan.warnings}
    assert not plan.is_complete


def test_one_reduction_across_a_connected_group_is_one_monitoring_row(
    project: Project, package: RulePackage
) -> None:
    reduced = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(with_spd_reduction(project, reduced.id), package)
    rows = [
        item
        for item in plan.test_applications
        if item.test_kind is TestKind.INTERNAL_SPD_MONITORING
    ]
    assert len(rows) == 1


# --- preconditioning ------------------------------------------------------------------------


def test_every_dielectric_strength_row_asks_the_preconditioning_gate(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    electrical = [
        item
        for item in plan.test_applications
        if item.test_kind in ELECTRICAL_TEST_KINDS and pair.id in item.covered_pair_ids
    ]
    assert electrical
    assert all(PRECONDITIONING_GATE in item.source_rule_ids for item in electrical)


def type_row(plan: VerificationPlan, pair: PairCase, kind: TestKind) -> TestApplication:
    """The type-test row of one kind, which is the classification the gate states a purpose for."""

    return next(
        item
        for item in rows_for(plan, pair, kind)
        if TestClassification.TYPE in item.classifications
    )


def test_a_required_preconditioning_names_its_route_and_carries_its_steps(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = type_row(build(project, package), pair, TestKind.AC_DIELECTRIC)
    route = f"{ids.TEST_PRECONDITIONING}.electrical_tests"
    assert any(route in step for step in row.preparation_steps)
    procedure = next(item for item in package.procedures if item.id == route)
    assert {step.text for step in procedure.procedure_steps} <= set(row.preparation_steps)


def test_the_preconditioning_comes_before_the_connection_instructions(
    project: Project, package: RulePackage
) -> None:
    """A specimen is preconditioned and wrapped before it is wired up."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = type_row(build(project, package), pair, TestKind.AC_DIELECTRIC)
    steps = list(row.preparation_steps)
    precondition = next(index for index, step in enumerate(steps) if "Precondition" in step)
    connect = next(index for index, step in enumerate(steps) if step.startswith("Connect"))
    assert precondition < connect


def test_a_classification_the_gate_states_no_purpose_for_is_unresolved_not_skipped(
    project: Project, package: RulePackage
) -> None:
    """The gate settles a type test and a sample test; a routine test is not among them."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    routine = next(
        item
        for item in rows_for(build(project, package), pair, TestKind.AC_DIELECTRIC)
        if TestClassification.ROUTINE in item.classifications
    )
    assert routine.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("states no purpose for a routine test" in item for item in routine.unresolved_inputs)


def test_the_partial_discharge_row_is_not_asked_the_electrical_context(
    project: Project, package: RulePackage
) -> None:
    """Which of the two preconditioning clauses covers a solid-insulation test is not ours."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = rows_for(build(project, package), pair, TestKind.PARTIAL_DISCHARGE)[0]
    assert PRECONDITIONING_GATE not in row.source_rule_ids


def test_a_row_with_no_classification_cannot_be_asked_and_says_so(
    package: RulePackage,
) -> None:
    """The impulse row of a pair with no protective means selected carries no classification."""
    project = verification_topology(supply_configurations=(mains_configuration(),))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = rows_for(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)[0]
    assert row.classifications == ()
    assert any("carries no classification" in item for item in row.unresolved_inputs)


# --- the accessible insulating surface ---------------------------------------------------------


def test_a_test_against_an_insulating_surface_carries_the_packages_foil_procedure(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, COVER)
    row = rows_for(build(project, package), pair, TestKind.AC_DIELECTRIC)[0]
    assert row.reference_kind is TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL
    assert FOIL_GATE in row.source_rule_ids
    procedure = next(
        item for item in package.procedures if item.id == ids.TEST_ACCESSIBLE_SURFACE_FOIL
    )
    assert {step.text for step in procedure.procedure_steps} <= set(row.preparation_steps)


def test_the_permitted_substitution_is_recorded_and_the_classification_is_left_alone(
    project: Project, package: RulePackage
) -> None:
    """Swapping a sample test in for a routine one on a string nothing here reads is not on."""
    pair = pair_between(project, LIVE_A, COVER)
    routine = next(
        item
        for item in rows_for(build(project, package), pair, TestKind.AC_DIELECTRIC)
        if TestClassification.ROUTINE in item.classifications
    )
    assert routine.classifications == (TestClassification.ROUTINE,)
    assert any("is not applied" in step for step in routine.preparation_steps)


def test_a_test_against_a_conductive_part_is_never_asked_the_foil_gate(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = rows_for(build(project, package), pair, TestKind.AC_DIELECTRIC)[0]
    assert FOIL_GATE not in row.source_rule_ids
    assert all("foil" not in step for step in row.preparation_steps)


def test_a_settled_row_is_not_decorated_into_an_open_one(package: RulePackage) -> None:
    """A test the plan settled as not applying needs neither preconditioning nor foil."""
    project = with_pair_fields(
        verification_topology(supply_configurations=(mains_configuration(),)),
        protection_implementation=BASIC,
        solid_insulation=declared_solid_insulation(present=False, material_pd_exempt=None),
    )
    pair = pair_between(project, LIVE_A, COVER)
    row = rows_for(build(project, package), pair, TestKind.PARTIAL_DISCHARGE)[0]
    assert row.applicability is TestApplicability.NOT_APPLICABLE
    assert row.unresolved_inputs == ()


def test_the_group_a_surface_is_tested_against_still_covers_both_of_its_pairs(
    project: Project, package: RulePackage
) -> None:
    """Decoration happens before deduplication, so a shared row is still one row."""
    first = pair_between(project, LIVE_A, COVER)
    second = pair_between(project, LIVE_B, COVER)
    rows = rows_for(build(project, package), first, TestKind.AC_DIELECTRIC)
    assert all(second.id in row.covered_pair_ids for row in rows)
