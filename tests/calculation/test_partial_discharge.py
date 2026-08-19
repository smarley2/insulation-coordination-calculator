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
    GATE_INPUT_TRACE_ID,
    PartialDischargeOutcome,
    assess_partial_discharge,
)
from insulation_coordination.calculation.verification_plan import (
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.calculation.verification_rules import (
    PARTIAL_DISCHARGE_GATE_OUTPUT,
    GatedProcedure,
    read_verification_rules,
)
from insulation_coordination.domain.project import PairCase, Project
from insulation_coordination.domain.rules import DecisionOutput, DecisionValue, RulePackage
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


def assess(project: Project, package: RulePackage) -> PartialDischargeOutcome:
    """The assessment of one pair, read without the schedule row in the way.

    The classification the applicability clause states is read here rather than off a schedule
    row, because the row still takes its classifications from the procedure the package
    declares. That is a call site outside this module.
    """

    pair = pair_between(project, LIVE_A, ENCLOSURE)
    return assess_partial_discharge(
        pair,
        resolve_effective_case(project.defaults, pair),
        read_verification_rules(package).partial_discharge,
        recurring_peak_v=RECURRING_PEAK_V,
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


def test_a_fully_declared_pair_still_names_the_two_conditions_nobody_can_be_asked(
    package: RulePackage,
) -> None:
    """Everything this project can state is stated, and the clause's own test is still open.

    Answering "required" here would credit the package with the two conditions
    4.4.7.10.3 states, which it does not carry. Answering "not required" would be worse.
    """
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert row.source_rule_ids == (
        ids.TEST_PARTIAL_DISCHARGE,
        f"{ids.TEST_PARTIAL_DISCHARGE}.applicability",
    )
    gap = next(item for item in row.unresolved_inputs if APPLICABILITY_CLAUSE in item)
    assert "recurring-peak working voltage across the insulation" in gap
    assert "electric stress derived from it" in gap
    assert "states no rule for either condition" in gap


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


def test_the_recurring_peak_answers_the_gate_and_the_trace_says_it_is_a_stand_in(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    step = next(item for item in row.trace_steps if item.semantic_rule_id == GATE_INPUT_TRACE_ID)
    assert "records no partial-discharge test voltage of its own" in step.reason


def test_a_pair_with_no_working_voltage_leaves_the_gate_unsettled(package: RulePackage) -> None:
    project = project_with(declared_solid_insulation(), recurring_peak_v=None)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("owes an engineering input" in item for item in row.unresolved_inputs)


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


# --- what the gate will not answer -----------------------------------------------------------


def assess_against(package: RulePackage, gated: GatedProcedure) -> PartialDischargeOutcome:
    """Assess one fully declared pair against a gate this test module reshaped."""

    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    return assess_partial_discharge(
        pair,
        resolve_effective_case(project.defaults, pair),
        gated,
        recurring_peak_v=None,
    )


def test_a_gate_that_settles_nothing_is_an_open_question_and_never_a_no(
    package: RulePackage,
) -> None:
    """A package whose gate has no row for this case must not read as a permission to skip."""
    gated = read_verification_rules(package).partial_discharge
    rows = tuple(
        row
        for row in gated.applicability.rows
        if not any(matcher.boolean is False for matcher in row.matchers)
    )
    narrowed = gated.model_copy(
        update={"applicability": gated.applicability.model_copy(update={"rows": rows})}
    )
    outcome = assess_against(package, narrowed)
    assert outcome.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        "open engineering question rather than a no" in item for item in outcome.unresolved_inputs
    )


def test_an_outcome_this_application_has_no_reading_for_is_reported_not_rounded(
    package: RulePackage,
) -> None:
    gated = read_verification_rules(package).partial_discharge
    gate = gated.applicability
    unknown = "synthetic_unmapped_outcome"
    narrowed = gated.model_copy(
        update={
            "applicability": gate.model_copy(
                update={
                    "outputs": (
                        DecisionOutput(
                            name=PARTIAL_DISCHARGE_GATE_OUTPUT,
                            kind="categorical",
                            allowed_values=(unknown,),
                        ),
                    ),
                    "rows": tuple(
                        row.model_copy(
                            update={
                                "values": (
                                    DecisionValue(
                                        name=PARTIAL_DISCHARGE_GATE_OUTPUT, categorical=unknown
                                    ),
                                )
                            }
                        )
                        for row in gate.rows
                    ),
                }
            )
        }
    )
    outcome = assess_against(package, narrowed)
    assert outcome.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(unknown in item for item in outcome.unresolved_inputs)


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
