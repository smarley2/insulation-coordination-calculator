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
    ELECTRIC_STRESS_TRACE_ID,
    GATE_INPUT_TRACE_ID,
    HIGH_FREQUENCY_REVIEW_WARNING,
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
) -> Project:
    """The verification topology with one protection implementation and one declaration."""

    project = verification_topology(
        supply_configurations=(mains_configuration(),),
        recurring_peak_v=recurring_peak_v,
        frequency_hz=frequency_hz,
    )
    return with_pair_fields(project, protection_implementation=BASIC, solid_insulation=solid)


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


def test_a_fully_declared_pair_is_told_the_test_is_required(package: RulePackage) -> None:
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.REQUIRED
    assert row.unresolved_inputs == ()
    assert row.source_rule_ids == (
        ids.TEST_PARTIAL_DISCHARGE,
        f"{ids.TEST_PARTIAL_DISCHARGE}.applicability",
    )


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


def test_layers_nobody_said_were_separately_testable_are_an_open_question(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation(layer_count=3))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("tested separately" in item for item in row.unresolved_inputs)


def test_separately_testable_layers_are_each_tested_and_the_construction_with_them(
    package: RulePackage,
) -> None:
    project = project_with(
        declared_solid_insulation(layer_count=3, separately_testable_layers=True)
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert row.applicability is TestApplicability.REQUIRED
    assert any("test each layer" in step for step in row.preparation_steps)


def test_layers_that_cannot_be_separated_say_no_result_belongs_to_one_of_them(
    package: RulePackage,
) -> None:
    project = project_with(
        declared_solid_insulation(layer_count=2, separately_testable_layers=False)
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, package), pair)
    assert any("attributable to one layer" in step for step in row.preparation_steps)


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


# --- the high-frequency review ---------------------------------------------------------------


def test_a_pair_above_the_part_4_boundary_carries_a_prominent_review_warning(
    package: RulePackage,
) -> None:
    frequency = PART4_FREQUENCY_THRESHOLD_HZ + Decimal(1)
    project = project_with(declared_solid_insulation(), frequency_hz=frequency)
    plan = build(project, package)
    warnings = [item for item in plan.warnings if item.code == HIGH_FREQUENCY_REVIEW_WARNING]
    assert warnings
    assert "IEC 60664-4" in warnings[0].message


def test_a_pair_at_the_boundary_is_not_above_it(package: RulePackage) -> None:
    project = project_with(declared_solid_insulation(), frequency_hz=PART4_FREQUENCY_THRESHOLD_HZ)
    plan = build(project, package)
    assert all(item.code != HIGH_FREQUENCY_REVIEW_WARNING for item in plan.warnings)


def test_the_review_warning_is_raised_even_where_the_test_itself_does_not_apply(
    package: RulePackage,
) -> None:
    """A pair assessed against a part this application does not apply is still a pair assessed."""
    project = project_with(
        SolidInsulationTestData(present=False),
        frequency_hz=PART4_FREQUENCY_THRESHOLD_HZ + Decimal(1),
    )
    plan = build(project, package)
    assert any(item.code == HIGH_FREQUENCY_REVIEW_WARNING for item in plan.warnings)


# --- how the plan carries it -------------------------------------------------------------


def test_every_pair_gets_a_partial_discharge_row_and_its_assessment_names_the_answer(
    package: RulePackage,
) -> None:
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    assessment = next(item for item in plan.pair_assessments if item.pair_id == pair.id)
    assert assessment.partial_discharge is TestApplicability.REQUIRED
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


def test_a_package_stating_no_classification_is_asked_for_one_rather_than_given_one(
    unclassified_package: RulePackage,
) -> None:
    """This is the real package's shape, and it is why a plan against it is never settled here."""
    project = project_with(declared_solid_insulation())
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    row = discharge_row(build(project, unclassified_package), pair)
    assert row.classifications == ()
    assert row.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("states no test classification" in item for item in row.unresolved_inputs)
