"""What excuses assembled equipment its routine test, and what the schedule does about it.

Every name, reference and reviewer here is this module's own. What is under test is the
direction the decision falls in and the trace it leaves behind, never a value or a wording from
any standard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.routine_exemption import (
    ExemptionConditionState,
    RoutineExemptionAssessment,
    assess_routine_exemption,
)
from insulation_coordination.calculation.verification_plan import (
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.calculation.verification_rules import (
    EXEMPTION_CONDITION_INPUTS,
    read_verification_rules,
)
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    RoutineTestExemptionEvidence,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
)
from tests.fixtures.verification_topologies import (
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
REVIEWED_AT = datetime(2026, 6, 7, 8, 9, 10, tzinfo=UTC)
#: Every field of the record answered and evidenced. A test states only what it takes away.
COMPLETE: dict[str, object] = {
    "subassemblies_routine_tested": True,
    "subassembly_evidence_reference": "SYN-SUB-1",
    "assembly_cannot_compromise_insulation": True,
    "assembly_justification": "SYN-ASSY-1",
    "assembled_type_test_passed": True,
    "assembled_type_test_reference": "SYN-TYPE-1",
    "reviewer": "A Reviewer",
    "reviewed_at": REVIEWED_AT,
}


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    """A package that states a partial-discharge classification, so nothing else is outstanding.

    The exemption can only excuse a row whose own question is answered, and this module is
    about the exemption rather than about everything else a plan reports.
    """

    return verification_and_supply_package(
        tmp_path / "merged.icrules", partial_discharge_classifications=("type_test",)
    )


def evidence(**overrides: object) -> RoutineTestExemptionEvidence:
    fields = dict(COMPLETE)
    fields.update(overrides)
    return RoutineTestExemptionEvidence(**fields)  # type: ignore[arg-type]


def project_with(exemption: RoutineTestExemptionEvidence | None) -> Project:
    return with_pair_fields(
        verification_topology(supply_configurations=(mains_configuration(),)),
        protection_implementation=BASIC,
        solid_insulation=declared_solid_insulation(),
        routine_exemption=exemption,
    )


def build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


def assess(pair: PairCase, package: RulePackage) -> RoutineExemptionAssessment:
    return assess_routine_exemption(
        pair, read_verification_rules(package).assembled_routine_exemption
    )


def routine_rows(plan: VerificationPlan, pair: PairCase) -> tuple[TestApplication, ...]:
    return tuple(
        item
        for item in plan.test_applications
        if pair.id in item.covered_pair_ids and TestClassification.ROUTINE in item.classifications
    )


# --- the decision trace ---------------------------------------------------------------------


def test_a_project_that_recorded_nothing_still_gets_every_condition_named(
    package: RulePackage,
) -> None:
    """ "There is no record" said once tells a reviewer less than the questions they must answer."""
    project = project_with(None)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    assert not assessment.exemption_permitted
    states = {item.state for item in assessment.conditions}
    assert states == {ExemptionConditionState.NOT_DECLARED}
    assert len(assessment.conditions) == len(EXEMPTION_CONDITION_INPUTS) + 2
    # Claiming nothing is the ordinary state, so nothing is outstanding for it.
    assert assessment.unresolved_inputs == ()


def test_the_trace_names_every_condition_the_rule_takes_as_an_input(
    package: RulePackage,
) -> None:
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    named = {item.decision_input for item in assessment.conditions if item.decision_input}
    assert named == set(EXEMPTION_CONDITION_INPUTS)


@pytest.mark.parametrize(
    "field",
    [
        "subassemblies_routine_tested",
        "assembly_cannot_compromise_insulation",
        "assembled_type_test_passed",
    ],
)
def test_a_condition_the_engineer_answered_no_to_is_not_satisfied(
    package: RulePackage, field: str
) -> None:
    project = project_with(evidence(**{field: False}))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    state = next(item.state for item in assessment.conditions if item.field_name == field)
    assert state is ExemptionConditionState.NOT_SATISFIED
    assert not assessment.exemption_permitted


@pytest.mark.parametrize(
    "reference_field",
    ["subassembly_evidence_reference", "assembly_justification", "assembled_type_test_reference"],
)
def test_a_condition_ticked_with_no_evidence_behind_it_is_not_satisfied(
    package: RulePackage, reference_field: str
) -> None:
    project = project_with(evidence(**{reference_field: "   "}))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    states = {item.state for item in assessment.conditions if item.field_name != reference_field}
    assert ExemptionConditionState.EVIDENCE_MISSING in {
        item.state for item in assessment.conditions
    }
    assert not assessment.exemption_permitted
    assert states  # the other conditions are still reported rather than short-circuited


@pytest.mark.parametrize("field", ["reviewer", "reviewed_at"])
def test_a_record_nobody_signed_or_dated_is_not_an_exemption(
    package: RulePackage, field: str
) -> None:
    project = project_with(evidence(**{field: "" if field == "reviewer" else None}))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    state = next(item.state for item in assessment.conditions if item.field_name == field)
    assert state is ExemptionConditionState.EVIDENCE_MISSING
    assert not assessment.exemption_permitted


def test_a_fully_evidenced_record_is_asked_of_the_package_and_granted(
    package: RulePackage,
) -> None:
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    assert assessment.exemption_permitted
    assert assessment.decision_status == "matched"
    assert assessment.missing == ()
    assert assessment.unresolved_inputs == ()


def test_an_incomplete_record_never_reaches_the_package_at_all(package: RulePackage) -> None:
    """The rule carries the one row the source states; a bare no-match names no condition."""
    project = project_with(evidence(reviewer=""))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assess(pair, package)
    assert assessment.decision_status == "not_asked"
    assert assessment.unresolved_inputs


# --- what the schedule does with it ------------------------------------------------------------


def test_a_project_claiming_no_exemption_keeps_its_routine_test_without_complaint(
    package: RulePackage,
) -> None:
    project = project_with(None)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    rows = routine_rows(plan, pair)
    assert rows
    assert all(row.applicability is not TestApplicability.NOT_REQUIRED for row in rows)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)
    assert assessment.routine_exemption is not None
    assert all("excused its routine dielectric test" not in item for item in plan.unresolved_inputs)


def test_an_unevidenced_exemption_keeps_the_routine_test_and_says_which_condition_is_missing(
    package: RulePackage,
) -> None:
    project = project_with(evidence(assembled_type_test_passed=False))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    rows = routine_rows(plan, pair)
    assert rows
    assert all(row.applicability is not TestApplicability.NOT_REQUIRED for row in rows)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)
    assert assessment.routine_exemption is not None
    assert any(
        "the assembled equipment passed its type test" in item
        for item in assessment.routine_exemption.unresolved_inputs
    )


def test_a_granted_exemption_marks_the_routine_row_and_never_removes_it(
    package: RulePackage,
) -> None:
    # Pair ids are drawn per call, so the unexcused project's rows are found through its own
    # pair. What has to match across the two is the test id, which is derived from the
    # electrodes and the package rather than from anything that changed.
    unexcused = project_with(None)
    without = routine_rows(build(unexcused, package), pair_between(unexcused, LIVE_A, ENCLOSURE))
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    rows = routine_rows(plan, pair)
    assert {row.test_id for row in rows} == {row.test_id for row in without}
    exempt = [row for row in rows if row.applicability is TestApplicability.NOT_REQUIRED]
    assert exempt
    assert all(
        any("is not removed from the schedule" in step for step in row.preparation_steps)
        for row in exempt
    )


def test_a_granted_exemption_leaves_the_type_tests_alone(package: RulePackage) -> None:
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    type_tests = [
        item
        for item in plan.test_applications
        if pair.id in item.covered_pair_ids
        and TestClassification.TYPE in item.classifications
        and item.test_kind is TestKind.AC_DIELECTRIC
    ]
    assert type_tests
    assert all(item.applicability is not TestApplicability.NOT_REQUIRED for item in type_tests)


def test_an_excused_row_keeps_everything_it_had_not_resolved(package: RulePackage) -> None:
    """Not performing a test does not answer what nobody knew about performing it."""
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = next(
        item
        for item in routine_rows(build(project, package), pair)
        if item.test_kind is TestKind.AC_DIELECTRIC
    )
    assert row.applicability is TestApplicability.NOT_REQUIRED
    assert row.unresolved_inputs


def test_an_exemption_never_touches_a_row_that_is_not_a_routine_test(
    package: RulePackage,
) -> None:
    project = project_with(evidence())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    others = [
        item
        for item in build(project, package).test_applications
        if pair.id in item.covered_pair_ids
        and TestClassification.ROUTINE not in item.classifications
    ]
    assert others
    assert all(item.applicability is not TestApplicability.NOT_REQUIRED for item in others)


def test_one_pair_of_a_group_cannot_excuse_the_other(package: RulePackage) -> None:
    """Deduplication keeps the least settled answer, so a shared row stays required."""
    project = verification_topology(supply_configurations=(mains_configuration(),))
    project = with_pair_fields(
        project,
        protection_implementation=BASIC,
        solid_insulation=declared_solid_insulation(),
    )
    excused = pair_between(project, LIVE_A, ENCLOSURE)
    project = with_pair_fields(project, excused.id, routine_exemption=evidence())
    plan = build(project, package)
    shared = routine_rows(plan, excused)
    other = pair_between(project, LIVE_B, ENCLOSURE)
    assert all(other.id in row.covered_pair_ids for row in shared)
    assert all(row.applicability is not TestApplicability.NOT_REQUIRED for row in shared)
