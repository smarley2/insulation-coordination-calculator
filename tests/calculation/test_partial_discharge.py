"""What the partial-discharge assessment concludes, and what it refuses to conclude.

Every figure, reference and material name here is this module's or its fixture's own. What is
under test is the direction each answer falls in - a missing declaration becoming an
engineering input rather than a no - and never a value from any standard.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.high_frequency import PART4_FREQUENCY_THRESHOLD_HZ
from insulation_coordination.calculation.partial_discharge import (
    APPLICABILITY_CLAUSE,
    ELECTRIC_STRESS_TRACE_ID,
    PartialDischargeOutcome,
    assess_partial_discharge,
)
from insulation_coordination.calculation.verification_plan import (
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.calculation.verification_rules import (
    PARTIAL_DISCHARGE_GATE_OUTPUT,
    SOLID_PARTIAL_DISCHARGE_REQUIRED_OUTPUT,
    SOLID_PARTIAL_DISCHARGE_SAMPLE_OUTPUT,
    SOLID_PARTIAL_DISCHARGE_STRESS_INPUT,
    SolidInsulationPartialDischargeRules,
    read_verification_rules,
)
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import DecisionValue, RulePackage
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    SolidInsulationTestData,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
)
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.synthetic_rules import (
    SYNTHETIC_PARTIAL_DISCHARGE_PEAK_THRESHOLD_V,
)
from tests.fixtures.verification_topologies import (
    ENCLOSURE,
    LIVE_A,
    declared_solid_insulation,
    mains_configuration,
    pair_between,
    verification_and_supply_package,
    verification_topology,
    with_pair_fields,
)

BASIC = ProtectionImplementation.BASIC_INSULATION
#: The one means every test here uses unless it is testing the scope itself. The applicability
#: clause is scoped to double and to reinforced insulation, so a pair protected by anything
#: else is outside it and its assessment answers a different question.
REINFORCED = ProtectionImplementation.REINFORCED_INSULATION
#: The fixture's recurring peak for a non-mains pair. Named so a test reads the quotient rather
#: than a bare number.
RECURRING_PEAK_V = Decimal(25)


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    """A package whose partial-discharge procedure states what kind of test it is.

    The real projection states none - the classification lives in a matrix Table 30 does not
    carry - and a plan that does not know whether a test is a type or a sample test cannot
    schedule it either way. That case has its own test at the bottom of this module; every
    other case here is about the applicability question, so it uses a package that does not
    leave the classification hanging over every assertion.
    """

    return verification_and_supply_package(
        tmp_path / "merged.icrules", partial_discharge_classifications=("type_test",)
    )


@pytest.fixture
def unclassified_package(tmp_path: Path) -> RulePackage:
    """The package exactly as the real projection shapes it: no partial-discharge classification."""

    return verification_and_supply_package(tmp_path / "unclassified.icrules")


def project_with(
    solid: SolidInsulationTestData | None = None,
    *,
    recurring_peak_v: Decimal | None = RECURRING_PEAK_V,
    frequency_hz: Decimal = Decimal(50),
    implementation: ProtectionImplementation | None = REINFORCED,
) -> Project:
    """The verification topology with one protection implementation and one declaration."""

    project = verification_topology(
        supply_configurations=(mains_configuration(),),
        recurring_peak_v=recurring_peak_v,
        frequency_hz=frequency_hz,
    )
    return with_pair_fields(
        project, protection_implementation=implementation, solid_insulation=solid
    )


def assess(
    project: Project,
    package: RulePackage,
    *,
    clause: SolidInsulationPartialDischargeRules | None = None,
    recurring_peak_v: Decimal | None = RECURRING_PEAK_V,
) -> PartialDischargeOutcome:
    """The assessment of one pair, read without the schedule row in the way.

    The classification the applicability clause states is read here rather than off a schedule
    row, so a test of this module fails for a reason inside it. The row carries the same
    answer: ``verification_plan`` takes a discharge row's classifications from the assessment.

    ``clause`` reshapes the two decisions the applicability subclause projects, for the tests
    that need the applicability rule to answer something the real project cannot make it
    answer.
    """

    pair = pair_between(project, LIVE_A, ENCLOSURE)
    rules = read_verification_rules(package)
    return assess_partial_discharge(
        pair,
        resolve_effective_case(project.defaults, pair),
        rules.partial_discharge,
        clause or rules.solid_insulation_partial_discharge,
        recurring_peak_v=recurring_peak_v,
    )


def without_the_stress_input(
    package: RulePackage,
) -> SolidInsulationPartialDischargeRules:
    """The clause's two decisions, with the applicability asked on the peak alone.

    The real rule states two conditions and the project can supply one of them, so nothing a
    project holds reaches a settled answer today. This drops the condition whose measurement is
    missing, which is what a project with that measurement recorded would look like - and it is
    the only way to show that a settled yes and a settled no both come out of the rule.
    """

    clause = read_verification_rules(package).solid_insulation_partial_discharge
    rule = clause.applicability
    return clause.model_copy(
        update={
            "applicability": rule.model_copy(
                update={
                    "inputs": tuple(
                        item
                        for item in rule.inputs
                        if item.name != SOLID_PARTIAL_DISCHARGE_STRESS_INPUT
                    ),
                    "rows": tuple(
                        row.model_copy(
                            update={
                                "matchers": tuple(
                                    matcher
                                    for matcher in row.matchers
                                    if matcher.input != SOLID_PARTIAL_DISCHARGE_STRESS_INPUT
                                )
                            }
                        )
                        for row in rule.rows
                    ),
                }
            )
        }
    )


def build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


def discharge_row(plan: VerificationPlan, pair: PairCase) -> TestApplication:
    matches = [
        item
        for item in plan.test_applications
        if item.test_kind is TestKind.PARTIAL_DISCHARGE and pair.id in item.covered_pair_ids
    ]
    assert len(matches) == 1, matches
    return matches[0]


# --- what the answer is, and what it never is ----------------------------------------------


def test_a_pair_that_declared_nothing_asks_for_a_declaration_rather_than_saying_no(
    package: RulePackage,
) -> None:
    project = project_with()
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        "has not declared whether solid insulation" in item for item in row.unresolved_inputs
    )


def test_a_pair_with_no_solid_insulation_at_all_has_nothing_to_verify(
    package: RulePackage,
) -> None:
    project = project_with(SolidInsulationTestData(present=False))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.NOT_APPLICABLE
    assert row.unresolved_inputs == ()


def test_a_fully_declared_pair_is_short_one_measurement_rather_than_the_whole_rule(
    package: RulePackage,
) -> None:
    """Everything this project can state is stated, and one measurement is still missing.

    The rule exists and is asked. What it is not given is the voltage stress, because that
    needs the distance between the two parts of different potential and no field records one.
    The block names that measurement, which is a far narrower thing to fix than the rule being
    absent - and the difference has to be legible on the row.
    """
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert row.source_rule_ids == (
        ids.TEST_PARTIAL_DISCHARGE,
        ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        f"{ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE}.classification",
    )
    gap = next(item for item in row.unresolved_inputs if APPLICABILITY_CLAUSE in item)
    assert "distance between the two parts of different potential" in gap
    assert "The measurement is missing, not the rule" in gap


def test_a_rule_given_both_conditions_settles_the_test_as_required(
    package: RulePackage,
) -> None:
    """The settled yes 4.4.7.10.3 states, which nothing in this application could reach before.

    Asked with the condition whose measurement is missing dropped, which is what a project
    recording that distance would produce. The peak is above this fixture's own threshold.
    """
    outcome = assess(
        project_with(declared_solid_insulation()),
        package,
        clause=without_the_stress_input(package),
    )

    assert outcome.applicability is TestApplicability.REQUIRED
    assert outcome.unresolved_inputs == ()


def test_a_rule_given_both_conditions_settles_the_test_as_not_required(
    package: RulePackage,
) -> None:
    """And the settled no, which is the half that keeps the yes from being the only answer."""
    peak = SYNTHETIC_PARTIAL_DISCHARGE_PEAK_THRESHOLD_V - Decimal(1)
    outcome = assess(
        project_with(declared_solid_insulation(), recurring_peak_v=peak),
        package,
        clause=without_the_stress_input(package),
        recurring_peak_v=peak,
    )

    assert outcome.applicability is TestApplicability.NOT_REQUIRED
    assert outcome.unresolved_inputs == ()


# --- the clause's own scope ---------------------------------------------------------------


def test_a_means_that_is_neither_double_nor_reinforced_is_outside_the_clause(
    package: RulePackage,
) -> None:
    """The project already holds the deciding input, so nothing more is asked of it."""
    project = project_with(declared_solid_insulation(), implementation=BASIC)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.NOT_APPLICABLE
    assert row.unresolved_inputs == ()
    assert any("outside that clause by rule" in step for step in row.preparation_steps)


def test_a_clearance_only_pair_is_outside_the_clause_whatever_its_means(
    package: RulePackage,
) -> None:
    project = project_with(
        declared_solid_insulation(present=False, material_pd_exempt=None), implementation=BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.NOT_APPLICABLE
    assert row.unresolved_inputs == ()


def test_double_insulation_is_in_scope_beside_reinforced(package: RulePackage) -> None:
    project = project_with(
        declared_solid_insulation(),
        implementation=ProtectionImplementation.DOUBLE_INSULATION,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(APPLICABILITY_CLAUSE in item for item in row.unresolved_inputs)


def test_a_pair_with_no_means_selected_is_asked_which_one_rather_than_told_no(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation(), implementation=None)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("no protective means selected" in item for item in row.unresolved_inputs)


def test_other_reviewed_means_belongs_to_the_review_that_approved_it(
    package: RulePackage,
) -> None:
    """A means approved elsewhere may or may not be solid insulation; nothing here knows."""
    project = project_with(
        declared_solid_insulation(),
        implementation=ProtectionImplementation.OTHER_REVIEWED_MEANS,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("review that approved the means" in item for item in row.unresolved_inputs)


def test_an_enhanced_means_that_is_not_solid_insulation_is_outside_the_clause(
    package: RulePackage,
) -> None:
    """Enhanced protection is not the scope; the two constructions the clause names are.

    A protective screen with basic insulation is enhanced protection, and 4.4.7.10.1 routes
    its basic insulation to the sibling clause, which asks for no partial-discharge test.
    """
    project = project_with(
        declared_solid_insulation(),
        implementation=ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.NOT_APPLICABLE
    assert row.unresolved_inputs == ()


# --- the classification the clause states -------------------------------------------------


def test_a_single_layer_declaration_owes_a_sample_test_beside_the_type_test(
    package: RulePackage,
) -> None:
    outcome = assess(project_with(declared_solid_insulation(layer_count=1)), package)

    assert outcome.classifications == (TestClassification.TYPE, TestClassification.SAMPLE)
    assert any("single layer of material" in step for step in outcome.preparation_steps)


def test_a_multi_layer_declaration_owes_the_type_test_alone(package: RulePackage) -> None:
    outcome = assess(project_with(declared_solid_insulation(layer_count=3)), package)

    assert outcome.classifications == (TestClassification.TYPE,)
    assert any("is not owed here" in step for step in outcome.preparation_steps)


def test_an_undeclared_layer_count_states_no_classification_and_says_why(
    package: RulePackage,
) -> None:
    outcome = assess(project_with(declared_solid_insulation(layer_count=None)), package)

    assert outcome.classifications == ()
    assert any("no layer count" in item for item in outcome.unresolved_inputs)


def test_a_documented_material_exemption_settles_the_test_as_not_required(
    package: RulePackage,
) -> None:
    project = project_with(
        declared_solid_insulation(material_pd_exempt=True, material_reference="SYN-EXEMPT-1")
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.NOT_REQUIRED
    assert row.unresolved_inputs == ()
    assert any("SYN-EXEMPT-1" in step for step in row.preparation_steps)


def test_a_claimed_exemption_without_a_reference_cannot_be_recorded_at_all() -> None:
    """The model refuses it, so no assessment ever has to decide what an unevidenced one means."""
    with pytest.raises(ValueError, match="material reference"):
        SolidInsulationTestData(present=True, material_pd_exempt=True)


def test_an_unanswered_exemption_is_not_an_exemption(package: RulePackage) -> None:
    project = project_with(declared_solid_insulation(material_pd_exempt=None))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("exempt from partial-discharge testing" in item for item in row.unresolved_inputs)


# --- the inputs the assessment is missing --------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("minimum_thickness_mm", "no minimum thickness"),
        ("layer_count", "no layer count"),
    ],
)
def test_each_missing_declaration_is_named_on_its_own(
    package: RulePackage, field: str, expected: str
) -> None:
    project = project_with(declared_solid_insulation(**{field: None}))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(expected in item for item in row.unresolved_inputs)


# --- the working voltage and the stress it produces -----------------------------------------


def test_a_pair_with_no_working_voltage_is_short_the_rules_first_condition_too(
    package: RulePackage,
) -> None:
    """Both conditions are then unanswered, and both are named."""
    project = project_with(declared_solid_insulation(), recurring_peak_v=None)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("No recurring-peak working voltage" in item for item in row.unresolved_inputs)
    assert any("The measurement is missing" in item for item in row.unresolved_inputs)


def test_the_procedure_tables_own_gate_is_no_longer_read_as_the_tests_applicability(
    package: RulePackage,
) -> None:
    """It answers whether a test *voltage* is declared, which is a different question.

    Reshaping it so it would answer "required" for this pair changes nothing: the assessment
    does not ask it, and what settles the row is the subclause's own decision.
    """
    rules = read_verification_rules(package)
    gate = rules.partial_discharge.applicability
    always_required = rules.partial_discharge.model_copy(
        update={
            "applicability": gate.model_copy(
                update={
                    "rows": tuple(
                        row.model_copy(
                            update={
                                "values": (
                                    DecisionValue(
                                        name=PARTIAL_DISCHARGE_GATE_OUTPUT, categorical="required"
                                    ),
                                )
                            }
                        )
                        for row in gate.rows
                    )
                }
            )
        }
    )
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    outcome = assess_partial_discharge(
        pair,
        resolve_effective_case(project.defaults, pair),
        always_required,
        rules.solid_insulation_partial_discharge,
        recurring_peak_v=RECURRING_PEAK_V,
    )

    assert outcome.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert gate.id not in outcome.source_rule_ids


def test_the_electric_stress_is_reported_and_is_the_declared_thickness_divided_into_it(
    package: RulePackage,
) -> None:
    thickness = Decimal("0.5")
    project = project_with(declared_solid_insulation(minimum_thickness_mm=thickness))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    step = next(
        item for item in row.trace_steps if item.semantic_rule_id == ELECTRIC_STRESS_TRACE_ID
    )
    assert step.output.value == RECURRING_PEAK_V / thickness
    assert step.output.unit == "V/mm"
    assert "neither dimensions nor approves a thickness" in step.reason


def test_no_thickness_means_no_stress_rather_than_a_stress_of_nothing(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation(minimum_thickness_mm=None))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert all(item.semantic_rule_id != ELECTRIC_STRESS_TRACE_ID for item in row.trace_steps)


# --- the high-frequency review this assessment no longer carries --------------------------


def test_no_partial_discharge_warning_is_raised_for_a_pair_above_the_high_frequency_boundary(
    package: RulePackage,
) -> None:
    """The annex that owns that boundary governs the insulation design, not this procedure.

    The review is raised where the pair is dimensioned - see
    ``tests/calculation/test_engine.py`` - and the partial-discharge procedure itself is
    specified at power frequency, so nothing about it belongs on this assessment.
    """
    frequency = PART4_FREQUENCY_THRESHOLD_HZ + Decimal(1)
    project = project_with(declared_solid_insulation(), frequency_hz=frequency)

    assert assess(project, package).warnings == ()


# --- how the plan carries it -------------------------------------------------------------


def test_every_pair_gets_a_partial_discharge_row_and_its_assessment_names_the_answer(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)
    assert assessment.partial_discharge is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert discharge_row(plan, pair).test_id in assessment.test_ids


# --- what the subclause's own decisions will not answer -------------------------------------


def test_a_rule_that_settles_nothing_is_an_open_question_and_never_a_no(
    package: RulePackage,
) -> None:
    """A package whose rule has no row for this case must not read as a permission to skip."""
    clause = without_the_stress_input(package)
    rule = clause.applicability
    narrowed = clause.model_copy(update={"applicability": rule.model_copy(update={"rows": ()})})
    outcome = assess(project_with(declared_solid_insulation()), package, clause=narrowed)

    assert outcome.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("settles no outcome" in item for item in outcome.unresolved_inputs)


def test_a_rule_that_states_no_verdict_settles_nothing_either(package: RulePackage) -> None:
    """A matched row carrying no verdict is an answer that answers the wrong question."""
    clause = without_the_stress_input(package)
    rule = clause.applicability
    silent = clause.model_copy(
        update={
            "applicability": rule.model_copy(
                update={"rows": tuple(row.model_copy(update={"values": ()}) for row in rule.rows)}
            )
        }
    )
    outcome = assess(project_with(declared_solid_insulation()), package, clause=silent)

    assert outcome.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        SOLID_PARTIAL_DISCHARGE_REQUIRED_OUTPUT in item for item in outcome.unresolved_inputs
    )


def test_the_classification_is_the_packages_answer_and_not_this_modules_arithmetic(
    package: RulePackage,
) -> None:
    """Swap what the rule says about a single layer, and the assessment follows it.

    The layer count is the input; which classifications that construction owes is the
    subclause's statement, and it is read from the rule that carries it rather than derived
    here from the same number.
    """
    clause = read_verification_rules(package).solid_insulation_partial_discharge
    rule = clause.classification
    inverted = clause.model_copy(
        update={
            "classification": rule.model_copy(
                update={
                    "rows": tuple(
                        row.model_copy(
                            update={
                                "values": tuple(
                                    value
                                    if value.name != SOLID_PARTIAL_DISCHARGE_SAMPLE_OUTPUT
                                    else value.model_copy(update={"boolean": not value.boolean})
                                    for value in row.values
                                )
                            }
                        )
                        for row in rule.rows
                    )
                }
            )
        }
    )
    outcome = assess(
        project_with(declared_solid_insulation(layer_count=1)), package, clause=inverted
    )

    assert outcome.classifications == (TestClassification.TYPE,)


def test_a_classification_rule_that_states_nothing_leaves_it_unresolved(
    package: RulePackage,
) -> None:
    clause = read_verification_rules(package).solid_insulation_partial_discharge
    silent = clause.model_copy(
        update={
            "classification": clause.classification.model_copy(
                update={"exhaustive": False, "rows": ()}
            )
        }
    )
    outcome = assess(project_with(declared_solid_insulation()), package, clause=silent)

    assert outcome.classifications == ()
    assert any("states no classification" in item for item in outcome.unresolved_inputs)


def test_the_clause_states_the_classification_even_where_the_package_states_none(
    unclassified_package: RulePackage,
) -> None:
    """This is the real package's shape: Table 30 carries no classification at all.

    It does not have to. The applicability clause states the classification itself, and it is
    read from the declared layer count rather than asked of the procedure.
    """
    outcome = assess(project_with(declared_solid_insulation()), unclassified_package)

    assert outcome.classifications == (TestClassification.TYPE, TestClassification.SAMPLE)
    assert not any("states no test classification" in item for item in outcome.unresolved_inputs)
