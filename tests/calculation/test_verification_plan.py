"""What a dielectric verification plan asks for, and what it refuses to invent.

Every figure, band, name and reference here is this module's or its fixture's own. Nothing
reproduces a value, a table, a heading or any wording from any standard: what is under test is
the routing - which rule answers which question for which pair - and the refusal that follows
when the package cannot answer it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from insulation_coordination.calculation.engine import derive_project_supply
from insulation_coordination.calculation.high_frequency import altitude_correction_band
from insulation_coordination.calculation.test_topology import (
    CONFLICTING_APPLICATION_WARNING,
)
from insulation_coordination.calculation.verification_plan import (
    DVC_AS_HIGHER_PORTION_STEP,
    ENHANCED_SPACING_MISMATCH_WARNING,
    HF_TRANSFORMER_SHOWING_WARNING,
    PROTECTION_REQUIREMENT_UNMET_WARNING,
    SPD_MONITORING_OWED_WARNING,
    PairVerificationAssessment,
    VerificationPlan,
    VerificationPlanService,
)
from insulation_coordination.calculation.verification_rules import (
    VerificationRulesUnavailable,
)
from insulation_coordination.domain.enums import (
    DecisiveVoltageClass,
    FieldCondition,
    InsulationType,
    ReviewState,
)
from insulation_coordination.domain.project import PairCase, PairVoltage, Project
from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.verification import (
    EvidenceApprovalState,
    ProtectionImplementation,
    TestApplicability,
    TestApplication,
    TestClassification,
    TestKind,
    TestReferenceKind,
    VerificationStatus,
    VoltageEvidence,
    VoltageEvidenceMethod,
    VoltageQuantityKind,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from tests.fixtures.synthetic_rules import (
    merged_rule_package,
    synthetic_part1_rule_package,
    synthetic_supply_rule_package,
    synthetic_verification_rule_package,
)
from tests.fixtures.verification_topologies import (
    COVER,
    ENCLOSURE,
    IMPULSE_SYSTEM_VOLTAGE_V,
    LIVE_A,
    LIVE_B,
    LIVE_C,
    SYSTEM_VOLTAGE_V,
    TOUCHABLE,
    TOV_SYSTEM_VOLTAGE_V,
    dielectric_cell,
    it_mains_configuration,
    mains_configuration,
    pair_between,
    single_column_dielectric_package,
    verification_and_supply_package,
    verification_topology,
    with_protection_matrix,
)

RECORDED_AT = datetime(2026, 5, 6, 7, 8, 9, tzinfo=UTC)
BASIC = ProtectionImplementation.BASIC_INSULATION
REINFORCED = ProtectionImplementation.REINFORCED_INSULATION
#: A reviewed answer that this pair carries no temporary overvoltage, which is the one state
#: of the three that sends a non-mains pair to the no-overvoltage table.
NO_OVERVOLTAGE = PairVoltage.not_applicable("Reviewed for this fixture: none is present.")
#: The fixture band ``SYSTEM_VOLTAGE_V`` falls into, which is what a route refusing
#: interpolation reads instead of a value between two rows.
UPPER_BAND_INDEX = 2


@pytest.fixture
def package(tmp_path: Path) -> RulePackage:
    return verification_and_supply_package(tmp_path / "merged.icrules")


@pytest.fixture
def project() -> Project:
    return with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )


def with_protection(
    project: Project,
    implementation: ProtectionImplementation,
    *,
    review: ReviewState = ReviewState.USER_CONFIRMED,
) -> Project:
    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(
                    update={
                        "protection_implementation": implementation,
                        "protection_review_state": review,
                    }
                )
                for pair in project.pairs
            )
        }
    )


def with_class(
    project: Project,
    net_id: UUID,
    dvc: DecisiveVoltageClass = DecisiveVoltageClass.DVC_C,
) -> Project:
    """The same project with one circuit reclassified, which is what moves a Table 3 row."""

    return project.model_copy(
        update={
            "net_classes": tuple(
                net.model_copy(update={"decisive_voltage_class": dvc}) if net.id == net_id else net
                for net in project.net_classes
            )
        }
    )


def build(project: Project, package: RulePackage) -> VerificationPlan:
    return VerificationPlanService().build(
        project, package, derive_project_supply(project, package)
    )


def applications_for(
    plan: VerificationPlan, pair: PairCase, kind: TestKind
) -> tuple[TestApplication, ...]:
    return tuple(
        item
        for item in plan.test_applications
        if item.test_kind is kind and pair.id in item.covered_pair_ids
    )


def one(
    plan: VerificationPlan, pair: PairCase, kind: TestKind, **fields: object
) -> TestApplication:
    matches = [
        item
        for item in applications_for(plan, pair, kind)
        if all(getattr(item, name) == value for name, value in fields.items())
    ]
    assert len(matches) == 1, matches
    return matches[0]


def assessment_for(plan: VerificationPlan, pair: PairCase) -> PairVerificationAssessment:
    return next(item for item in plan.pair_assessments if item.pair_id == pair.id)


def dielectric_route(application: TestApplication) -> str:
    """The one dielectric table a row was read from, out of everything else it cites.

    A row cites the gates it asked as well as the table it read, so a test about which route
    answered says so rather than pinning the whole list and failing the day a row asks one
    more question.
    """

    routes = [
        item
        for item in application.source_rule_ids
        if ids.TEST_MAINS_DIELECTRIC_VALUES in item or ids.TEST_NON_MAINS_DIELECTRIC_VALUES in item
    ]
    assert len(routes) == 1, application.source_rule_ids
    return routes[0]


# --- the plan's identity and its shape ------------------------------------------------------


def test_a_plan_names_the_package_it_was_built_from(project: Project, package: RulePackage) -> None:
    plan = build(project, package)
    assert plan.rule_package.sha256 == package.package_sha256
    assert plan.rule_package.version == package.manifest.version


def test_a_plan_is_the_same_plan_when_it_is_built_twice(
    project: Project, package: RulePackage
) -> None:
    """Plans are recomputed and never stored, so two runs have to be comparable."""
    first = build(project, package)
    second = build(project, package)
    assert [item.test_id for item in first.test_applications] == [
        item.test_id for item in second.test_applications
    ]


def test_a_package_that_cannot_answer_blocks_rather_than_planning_around_it(
    project: Project,
) -> None:
    with pytest.raises(VerificationRulesUnavailable):
        VerificationPlanService().build(project, synthetic_supply_rule_package(), None)


def test_every_pair_that_is_a_test_gets_an_assessment_naming_its_rows(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assessment_for(plan, pair)
    assert assessment.reference_kind is TestReferenceKind.PE_BONDED_ACCESSIBLE_PART
    assert assessment.test_ids
    covering = {item.test_id for item in plan.test_applications if pair.id in item.covered_pair_ids}
    assert set(assessment.test_ids) == covering


def test_a_pair_of_two_reference_parts_is_assessed_as_nothing_at_all(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    pair = pair_between(project, ENCLOSURE, COVER)
    assert all(item.pair_id != pair.id for item in plan.pair_assessments)


# --- impulse planning -------------------------------------------------------------------------


def test_the_impulse_is_the_stress_issue_36_resolved_and_is_never_derived_again(
    project: Project, package: RulePackage
) -> None:
    supply = derive_project_supply(project, package)
    assert supply is not None
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = VerificationPlanService().build(project, package, supply)
    application = one(plan, pair, TestKind.IMPULSE_WITHSTAND)
    scenario = supply.governing.scenarios[0]
    assert application.voltage is not None
    assert application.voltage.value == scenario.rated_impulse_v


def test_a_reinforced_pair_is_tested_at_the_treated_stress_and_it_is_not_treated_twice(
    package: RulePackage,
) -> None:
    basic = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.BASIC
        ),
        BASIC,
    )
    reinforced = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        REINFORCED,
    )
    untreated = one(
        build(basic, package), pair_between(basic, LIVE_A, ENCLOSURE), TestKind.IMPULSE_WITHSTAND
    ).voltage
    treated = one(
        build(reinforced, package),
        pair_between(reinforced, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    ).voltage
    assert untreated is not None and treated is not None
    supply = derive_project_supply(reinforced, package)
    assert supply is not None
    resolution_value = supply.governing.impulse_v
    assert resolution_value is not None
    assert treated.value > untreated.value
    # The treatment came from the resolution, not from anything multiplied here.
    assert untreated.value == resolution_value


def test_a_reinforced_pair_reads_the_reinforced_procedure_variant(
    package: RulePackage,
) -> None:
    reinforced = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        REINFORCED,
    )
    pair = pair_between(reinforced, LIVE_A, ENCLOSURE)
    application = one(build(reinforced, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert f"{ids.TEST_IMPULSE_PROCEDURE}.insulation_reinforced" in application.source_rule_ids


def test_a_basic_pair_reads_the_basic_procedure_variant(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert f"{ids.TEST_IMPULSE_PROCEDURE}.insulation_basic" in application.source_rule_ids


def test_a_pair_with_no_protection_implementation_asks_for_one_rather_than_guessing(
    package: RulePackage,
) -> None:
    project = verification_topology(supply_configurations=(mains_configuration(),))
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert all(ids.TEST_IMPULSE_PROCEDURE not in item for item in application.source_rule_ids)
    assert any("no protection implementation" in item for item in application.unresolved_inputs)


def test_the_impulse_never_chooses_between_the_alternative_ac_and_dc_verifications(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any("does not choose between them" in step for step in application.preparation_steps)


def test_the_impulse_says_which_verification_it_is_and_which_it_is_not(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any(
        "Solid insulation between them is a separate verification" in step
        for step in application.preparation_steps
    )


@pytest.mark.parametrize("altitude_m", [Decimal(0), Decimal(2500)])
def test_every_planned_voltage_is_uncorrected_because_the_test_site_is_unknown(
    package: RulePackage, altitude_m: Decimal
) -> None:
    """The correction is keyed on the altitude of the test, not on the pair's own.

    A pair dimensioned at sea level is the pair the correction is actually written for, and the
    plan used to say nothing at all about it; a pair dimensioned high up was told its voltage
    was uncorrected for a reason no rule states.
    """
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), altitude_m=altitude_m
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any(
        "keyed on the altitude at which the test is carried out" in item
        for item in application.unresolved_inputs
    )
    assert any(
        ids.ALTITUDE_TEST_VOLTAGE_CORRECTION in item for item in application.unresolved_inputs
    )


def test_the_uncorrected_statement_excepts_impulse_testing_of_solid_insulation(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any(
        "not applied to impulse testing of solid insulation" in item
        for item in application.unresolved_inputs
    )


def test_a_package_stating_no_clearance_correction_cannot_place_the_pair_in_a_band(
    project: Project, package: RulePackage
) -> None:
    """Without the boundary the package states, whether the alternative is open is unknown."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any(
        "states no approved clearance altitude correction" in item
        for item in application.unresolved_inputs
    )
    assert not any("in reverse" in step for step in application.preparation_steps)


def test_a_clearance_above_the_frequency_threshold_states_the_derivation_alternative(
    package: RulePackage,
) -> None:
    """A permission, so it is stated and never selected: the voltage is still the pair's."""
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), frequency_hz=Decimal(40000)
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    alternative = [step for step in application.preparation_steps if "in reverse" in step]
    assert len(alternative) == 1
    assert "above the high-frequency threshold" in alternative[0]
    assert "does not choose it" in alternative[0]


def test_a_clearance_dimensioned_above_the_packages_reference_altitude_states_it_too(
    tmp_path: Path,
) -> None:
    """The band boundary comes from the package's own correction table, never from a literal."""
    package = merged_rule_package(
        single_column_dielectric_package(),
        synthetic_supply_rule_package(),
        synthetic_part1_rule_package(),
        path=tmp_path / "with-altitude.icrules",
    )
    reference_m, _ = altitude_correction_band(package)
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), altitude_m=reference_m + Decimal(500)
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    alternative = [step for step in application.preparation_steps if "in reverse" in step]
    assert len(alternative) == 1
    assert "above the altitude the package's clearance correction is referred to" in alternative[0]


def test_a_project_with_no_supply_arrangement_asks_for_a_stress_rather_than_inventing_one(
    package: RulePackage,
) -> None:
    project = with_protection(verification_topology(), BASIC)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = VerificationPlanService().build(project, package, None)
    application = one(plan, pair, TestKind.IMPULSE_WITHSTAND)
    assert application.voltage is None
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any("No impulse stress is resolved" in item for item in application.unresolved_inputs)


# --- the protection requirement -------------------------------------------------------------


def test_the_requirement_comes_from_the_package_and_not_from_what_was_selected(
    package: RulePackage,
) -> None:
    """The whole point: change the implementation and the requirement must not follow it.

    A requirement derived from the construction an engineer chose is a requirement that can
    never be failed, which is what the pair page showed before anything was behind that row.
    """
    base = verification_topology(supply_configurations=(mains_configuration(),))
    stated = {
        implementation: assessment_for(
            build(with_protection(base, implementation), package),
            pair_between(base, LIVE_A, ENCLOSURE),
        ).required_protection
        for implementation in (BASIC, REINFORCED, ProtectionImplementation.FUNCTIONAL_INSULATION)
    }
    assert set(stated.values()) == {"basic_protection"}


def test_a_requirement_the_selected_construction_meets_is_reported_as_met(
    project: Project, package: RulePackage
) -> None:
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert assessment.required_protection == "basic_protection"
    assert assessment.protection_satisfied is True
    assert assessment.requirement_columns
    assert not assessment.unresolved_inputs


def test_a_construction_above_the_required_level_meets_it(package: RulePackage) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        REINFORCED,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert assessment.required_protection == "basic_protection"
    assert assessment.protection_satisfied is True


def test_a_construction_below_the_required_level_is_a_finding_and_not_an_exception(
    package: RulePackage,
) -> None:
    """A wrong implementation is a finding about a project, so the schedule is still built."""
    project = with_protection(
        with_class(verification_topology(supply_configurations=(mains_configuration(),)), LIVE_A),
        BASIC,
    )
    plan = build(project, package)
    assessment = assessment_for(plan, pair_between(project, LIVE_A, ENCLOSURE))

    assert assessment.required_protection == "enhanced_protection"
    assert assessment.protection_satisfied is False
    assert assessment.status is VerificationStatus.ENGINEERING_REVIEW_REQUIRED
    assert any("does not meet the requirement" in item for item in assessment.unresolved_inputs)
    assert PROTECTION_REQUIREMENT_UNMET_WARNING in {warning.code for warning in plan.warnings}
    assert plan.test_applications


def test_two_circuits_are_asked_in_both_directions_and_the_more_demanding_governs(
    package: RulePackage,
) -> None:
    """Each circuit is protected from the other, and one insulation answers for both."""
    project = with_protection(
        with_class(verification_topology(supply_configurations=(mains_configuration(),)), LIVE_C),
        BASIC,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, LIVE_C))

    # The fixture states basic protection reading from the DVC C circuit and enhanced reading
    # from the DVC B one, so a plan that asked once could report either.
    assert assessment.required_protection == "enhanced_protection"
    assert assessment.protection_satisfied is False


def test_columns_that_disagree_on_something_the_project_does_not_record_settle_nothing(
    package: RulePackage,
) -> None:
    """An insulating surface is neither bonded nor unbonded, so both columns answer.

    Where they say different things there is no requirement to report: the project records no
    access context and no person scope either, and picking one column would state a demand the
    source did not make of this equipment.
    """
    project = with_protection(
        with_class(
            verification_topology(supply_configurations=(mains_configuration(),)),
            LIVE_A,
            DecisiveVoltageClass.DVC_AS,
        ),
        BASIC,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, COVER))

    assert assessment.required_protection is None
    assert assessment.protection_satisfied is None
    assert any("more than one requirement" in item for item in assessment.unresolved_inputs)


def test_a_relationship_no_reviewed_column_carries_is_reported_rather_than_assumed(
    package: RulePackage,
) -> None:
    project = with_protection(
        with_class(
            verification_topology(supply_configurations=(mains_configuration(),)),
            LIVE_B,
            DecisiveVoltageClass.DVC_AS,
        ),
        BASIC,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, LIVE_B))

    assert assessment.required_protection is None
    assert assessment.protection_satisfied is None
    assert any("no reviewed column" in item for item in assessment.unresolved_inputs)


def test_a_circuit_with_no_decisive_voltage_class_names_itself(package: RulePackage) -> None:
    project = with_protection(
        with_class(
            verification_topology(supply_configurations=(mains_configuration(),)),
            LIVE_A,
            DecisiveVoltageClass.NOT_EVALUATED,
        ),
        BASIC,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))

    assert assessment.required_protection is None
    assert any(
        "No decisive voltage class is assigned to Live A" in item
        for item in assessment.unresolved_inputs
    )


def test_a_construction_this_application_does_not_rank_is_a_judgement_not_a_pass(
    package: RulePackage,
) -> None:
    """Supplementary insulation alone is added *to* basic insulation, not a level by itself."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.SUPPLEMENTARY_INSULATION,
    )
    plan = build(project, package)
    assessment = assessment_for(plan, pair_between(project, LIVE_A, ENCLOSURE))

    assert assessment.required_protection == "basic_protection"
    assert assessment.protection_satisfied is None
    assert any("engineering judgement" in item for item in assessment.unresolved_inputs)
    assert PROTECTION_REQUIREMENT_UNMET_WARNING not in {warning.code for warning in plan.warnings}


def test_the_plan_names_the_rule_the_requirement_was_read_from(
    project: Project, package: RulePackage
) -> None:
    assert ids.DVC_PROTECTION_MATRIX in build(project, package).source_rule_ids


# --- enhanced protection ------------------------------------------------------------------


def test_double_insulation_is_not_collapsed_into_one_reinforced_path(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        ProtectionImplementation.DOUBLE_INSULATION,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any(
        "two separately assessed protective means" in item for item in application.unresolved_inputs
    )


def test_enhanced_protection_dimensioned_on_a_lesser_path_is_reported_not_planned_around(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.BASIC
        ),
        REINFORCED,
    )
    plan = build(project, package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(plan, pair, TestKind.IMPULSE_WITHSTAND)
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert ENHANCED_SPACING_MISMATCH_WARNING in {warning.code for warning in plan.warnings}


def test_a_protective_impedance_stays_a_disclosed_engineering_item(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.PROTECTIVE_IMPEDANCE,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(build(project, package), pair, TestKind.IMPULSE_WITHSTAND)
    assert any("protective impedance" in item for item in application.unresolved_inputs)


# --- AC and DC dielectric -----------------------------------------------------------------


def test_a_mains_circuit_is_read_from_the_mains_table_on_its_system_voltage(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert dielectric_route(application) == (
        f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    )
    assert application.voltage is not None
    assert application.voltage.value == _interpolated(
        ids.TEST_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", SYSTEM_VOLTAGE_V
    )


def test_a_mains_row_is_keyed_on_the_temporary_overvoltage_system_voltage(
    package: RulePackage,
) -> None:
    """One arrangement answers the two system-voltage questions with two different measures.

    What this test verifies is withstand of the temporary overvoltage, so the measure that
    keys its row is the temporary-overvoltage one. Here, as for the arrangement the source
    names, the impulse measure is the lower of the two, so a row keyed on it plans the test
    below the row the package states for the circuit.
    """
    project = with_protection(
        verification_topology(supply_configurations=(it_mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is not None
    assert application.voltage.value == _interpolated(
        ids.TEST_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", TOV_SYSTEM_VOLTAGE_V
    )
    assert application.voltage.value != _interpolated(
        ids.TEST_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", IMPULSE_SYSTEM_VOLTAGE_V
    )


def test_a_circuit_behind_a_barrier_is_not_a_mains_circuit(package: RulePackage) -> None:
    """The barrier is exactly what makes the non-mains table the one that applies."""
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), temporary_overvoltage=NO_OVERVOLTAGE
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, ENCLOSURE)
    plan = build(project, package)
    application = one(
        plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,)
    )
    assert dielectric_route(application) == (
        f"{ids.TEST_NON_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    )
    assert not assessment_for(plan, pair).mains_connected


def test_a_pair_reaching_a_mains_circuit_at_all_is_a_mains_case(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, LIVE_C)
    assert assessment_for(build(project, package), pair).mains_connected


def test_a_non_mains_pair_carrying_a_temporary_overvoltage_does_not_read_the_table(
    package: RulePackage,
) -> None:
    """The no-overvoltage table is not the route for a circuit that has an overvoltage.

    The package projects one non-mains dielectric route and it is the table's. Nothing in it
    derives a test voltage from a temporary overvoltage, so the pair gets an unresolved input
    naming what is missing - never the table's lower answer read anyway.
    """
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),),
            recurring_peak_v=Decimal(15),
            temporary_overvoltage=PairVoltage.applicable(Decimal(250)),
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, TOUCHABLE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is None
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        "temporary overvoltage" in item and ids.TEST_NON_MAINS_DIELECTRIC_VALUES in item
        for item in application.unresolved_inputs
    )


def test_a_non_mains_pair_whose_overvoltage_state_is_unknown_does_not_fall_through(
    package: RulePackage,
) -> None:
    """A blank entry is a question nobody answered, and it is not a "no"."""
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),),
            recurring_peak_v=Decimal(15),
            temporary_overvoltage=PairVoltage.blank(),
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, TOUCHABLE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is None
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        "whether a temporary overvoltage is present" in item
        for item in application.unresolved_inputs
    )


def test_a_non_mains_circuit_is_keyed_on_its_recurring_peak_working_voltage(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),),
            recurring_peak_v=Decimal(15),
            temporary_overvoltage=NO_OVERVOLTAGE,
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, TOUCHABLE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is not None
    assert application.voltage.value == _interpolated(
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", Decimal(15)
    )


def test_an_approved_evidence_entry_above_the_pair_entry_is_what_keys_the_row(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),),
            recurring_peak_v=Decimal(15),
            temporary_overvoltage=NO_OVERVOLTAGE,
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, TOUCHABLE)
    project = project.model_copy(update={"voltage_evidence": (_evidence(pair.id, Decimal(35)),)})
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is not None
    assert application.voltage.value == _interpolated(
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", Decimal(35)
    )


def test_a_non_mains_circuit_with_no_working_voltage_at_all_asks_for_one(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),),
            recurring_peak_v=None,
            temporary_overvoltage=NO_OVERVOLTAGE,
        ),
        BASIC,
    )
    pair = pair_between(project, LIVE_C, TOUCHABLE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is None
    assert application.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(
        "No recurring-peak working voltage is established" in item
        for item in application.unresolved_inputs
    )


def test_both_voltage_forms_are_planned_where_the_package_states_both(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    kinds = {
        item.test_kind
        for item in plan_applications(build(project, package), pair)
        if item.test_kind in {TestKind.AC_DIELECTRIC, TestKind.DC_DIELECTRIC}
    }
    assert kinds == {TestKind.AC_DIELECTRIC, TestKind.DC_DIELECTRIC}


def test_the_type_and_routine_tests_are_separate_applications(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    applications = applications_for(build(project, package), pair, TestKind.AC_DIELECTRIC)
    assert {item.classifications for item in applications} == {
        (TestClassification.TYPE,),
        (TestClassification.ROUTINE,),
    }
    assert len({item.test_id for item in applications}) == 2


def test_an_enhanced_type_test_is_read_from_its_own_route_and_not_from_the_routine_one(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        REINFORCED,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    type_test = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.TYPE,))
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert dielectric_route(type_test) == f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.enhanced_type.ac"
    assert dielectric_route(routine) == (
        f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    )
    assert type_test.voltage != routine.voltage


def test_a_basic_pair_takes_both_from_the_route_whose_own_name_covers_both(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    routes = {
        dielectric_route(item) for item in applications_for(plan, pair, TestKind.AC_DIELECTRIC)
    }
    assert routes == {f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"}


@pytest.mark.parametrize("reference", [TOUCHABLE, COVER])
def test_a_basic_pair_against_an_unbonded_surface_type_tests_at_the_enhanced_column(
    project: Project, package: RulePackage, reference: UUID
) -> None:
    """The column is a question about the topology, not only about what the engineer built.

    The package's own label for the enhanced column names this topology beside enhanced
    protection. Selecting the column from the selected construction alone planned a
    basic-protection pair against an unbonded accessible surface at the lower column.
    """
    pair = pair_between(project, LIVE_A, reference)
    plan = build(project, package)
    type_test = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.TYPE,))
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert dielectric_route(type_test) == f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.enhanced_type.ac"
    assert dielectric_route(routine) == (
        f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    )


def test_a_basic_pair_against_a_pe_bonded_part_stays_on_the_basic_column(
    project: Project, package: RulePackage
) -> None:
    """The topology the clause excludes from the enhanced column has to stay excluded."""
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    routes = {
        dielectric_route(item) for item in applications_for(plan, pair, TestKind.AC_DIELECTRIC)
    }
    assert routes == {f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"}


@pytest.mark.parametrize("reference", [ENCLOSURE, TOUCHABLE, COVER])
def test_a_dvc_as_circuit_is_excepted_from_the_test_against_an_accessible_part(
    package: RulePackage, reference: UUID
) -> None:
    """The rule excepts it and settles the case elsewhere, so the row is not planned."""
    project = with_class(
        with_protection(
            verification_topology(supply_configurations=(mains_configuration(),)), BASIC
        ),
        LIVE_C,
        DecisiveVoltageClass.DVC_AS,
    )
    pair = pair_between(project, LIVE_C, reference)
    applications = applications_for(build(project, package), pair, TestKind.AC_DIELECTRIC)
    assert applications
    assert {item.applicability for item in applications} == {TestApplicability.NOT_APPLICABLE}
    assert all(item.voltage is None for item in applications)
    assert all(not item.unresolved_inputs for item in applications)
    assert all(
        any("except a DVC A-s one" in step for step in item.preparation_steps)
        for item in applications
    )


# --- the DVC A-s adjacency --------------------------------------------------------------


#: The pair's own recurring peak in the DVC A-s fixtures below, and the three circuits' own.
#: All inside the fixture's band axis, all different, and the pair's deliberately unequal to
#: any of them: a row keyed on the pair rather than on the higher-voltage circuit reads a
#: different cell and can be told apart by the value alone.
PAIR_PEAK_V = Decimal(15)
CIRCUIT_PEAKS_V: dict[UUID, Decimal] = {
    LIVE_A: Decimal(18),
    LIVE_B: Decimal(12),
    LIVE_C: Decimal(25),
}


def dvc_as_topology(
    *,
    implementation: ProtectionImplementation = BASIC,
    classes: tuple[UUID, ...] = (LIVE_C,),
    peaks: tuple[UUID, ...] = (LIVE_A, LIVE_B, LIVE_C),
) -> Project:
    """Three circuits with no supply arrangement, so every pair takes the non-mains route.

    ``classes`` names the circuits reclassified as DVC A-s and ``peaks`` the circuits given an
    approved working voltage of their own, so a test can withhold exactly one of them.
    """

    project = with_protection(
        verification_topology(temporary_overvoltage=NO_OVERVOLTAGE, recurring_peak_v=PAIR_PEAK_V),
        implementation,
    )
    for net_id in classes:
        project = with_class(project, net_id, DecisiveVoltageClass.DVC_AS)
    return project.model_copy(
        update={
            "voltage_evidence": tuple(
                _net_evidence(net_id, CIRCUIT_PEAKS_V[net_id], index)
                for index, net_id in enumerate(peaks)
            )
        }
    )


def test_a_pair_facing_a_dvc_as_circuit_is_its_own_relationship(package: RulePackage) -> None:
    project = dvc_as_topology()
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    assert assessment_for(plan, pair).reference_kind is TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT


def test_the_dvc_as_adjacency_type_test_reads_the_enhanced_column(package: RulePackage) -> None:
    """A basic-protection pair, so the column cannot be coming from the construction."""
    project = dvc_as_topology()
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    type_test = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.TYPE,))
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert dielectric_route(type_test) == (
        f"{ids.TEST_NON_MAINS_DIELECTRIC_VALUES}.enhanced_type.ac"
    )
    assert dielectric_route(routine) == (
        f"{ids.TEST_NON_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    )


def test_the_dvc_as_adjacency_row_is_keyed_on_the_higher_voltage_circuit(
    package: RulePackage,
) -> None:
    """Not on the circuit under test and not on the voltage across the pair."""
    project = dvc_as_topology()
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert routine.voltage is not None
    assert routine.voltage.value == _interpolated(
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
        "routine_and_basic_type",
        "ac",
        max(CIRCUIT_PEAKS_V[LIVE_A], CIRCUIT_PEAKS_V[LIVE_C]),
    )
    assert routine.voltage.value != _interpolated(
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", PAIR_PEAK_V
    )


def test_a_dvc_as_adjacency_refuses_a_row_it_cannot_decide_the_higher_circuit_of(
    package: RulePackage,
) -> None:
    project = dvc_as_topology(peaks=(LIVE_A, LIVE_B))
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert routine.voltage is None
    assert any(
        "which of them is the higher cannot be decided" in item
        for item in routine.unresolved_inputs
    )


def test_functional_insulation_between_two_dvc_as_circuits_is_not_tested(
    package: RulePackage,
) -> None:
    project = dvc_as_topology(
        implementation=ProtectionImplementation.FUNCTIONAL_INSULATION,
        classes=(LIVE_A, LIVE_B, LIVE_C),
    )
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    applications = applications_for(plan, pair, TestKind.AC_DIELECTRIC)
    assert applications
    assert {item.applicability for item in applications} == {TestApplicability.NOT_APPLICABLE}


def test_basic_insulation_between_two_dvc_as_circuits_is_still_tested(
    package: RulePackage,
) -> None:
    """The other half of the same rule: only the functional case is excused."""
    project = dvc_as_topology(classes=(LIVE_A, LIVE_B, LIVE_C))
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert routine.applicability is not TestApplicability.NOT_APPLICABLE
    assert routine.voltage is not None


@pytest.mark.parametrize(
    ("classes", "implementation"),
    [
        ((LIVE_C,), BASIC),
        ((LIVE_A, LIVE_B, LIVE_C), ProtectionImplementation.FUNCTIONAL_INSULATION),
    ],
)
def test_a_dvc_as_row_states_what_a_higher_voltage_portion_does_to_the_spacing(
    package: RulePackage,
    classes: tuple[UUID, ...],
    implementation: ProtectionImplementation,
) -> None:
    """The one place a single-fault consideration reaches a spacing, stated where it applies.

    A portion above the class limits is admitted on a single-fault assessment, and the same
    paragraph requires that portion's voltages to go on dimensioning the circuit's clearance
    and creepage to its surroundings. A reader told that single fault is not an operating
    condition of the working voltage has to be told this in the same breath.
    """
    project = dvc_as_topology(implementation=implementation, classes=classes)
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = VerificationPlanService().build(project, package, None)
    routine = one(plan, pair, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,))
    assert any(DVC_AS_HIGHER_PORTION_STEP in step for step in routine.preparation_steps), (
        routine.preparation_steps
    )


def test_a_route_that_states_no_duration_says_so_rather_than_leaving_it_blank(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.duration is None
    assert any("states no duration" in item for item in application.unresolved_inputs)


def test_a_banded_route_reads_the_band_rather_than_interpolating_into_it(
    tmp_path: Path,
) -> None:
    """Whether a value between two rows may be interpolated is the package's statement."""
    package = verification_and_supply_package(tmp_path / "banded.icrules", interpolation="none")
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    application = one(
        build(project, package),
        pair,
        TestKind.AC_DIELECTRIC,
        classifications=(TestClassification.ROUTINE,),
    )
    assert application.voltage is not None
    assert application.voltage.value == dielectric_cell(
        ids.TEST_MAINS_DIELECTRIC_VALUES, "routine_and_basic_type", "ac", UPPER_BAND_INDEX
    )


def test_a_route_stating_more_than_one_column_is_refused_rather_than_guessed_at() -> None:
    """The package labels a column by the source column it came from and nothing more."""
    project = with_protection(verification_topology(temporary_overvoltage=NO_OVERVOLTAGE), BASIC)
    plan = VerificationPlanService().build(
        project, _identified(with_protection_matrix(synthetic_verification_rule_package())), None
    )
    application = next(
        item for item in plan.test_applications if item.test_kind is TestKind.AC_DIELECTRIC
    )
    assert application.voltage is None
    assert any("says which one applies" in item for item in application.unresolved_inputs)


# --- topology and deduplication in the whole plan --------------------------------------------


def test_one_row_covers_every_pair_of_a_connected_group(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    against_a = pair_between(project, LIVE_A, ENCLOSURE)
    against_b = pair_between(project, LIVE_B, ENCLOSURE)
    application = one(
        plan, against_a, TestKind.AC_DIELECTRIC, classifications=(TestClassification.ROUTINE,)
    )
    assert set(application.covered_pair_ids) == {against_a.id, against_b.id}
    assert assessment_for(plan, against_b).test_ids


def test_all_four_test_topologies_reach_the_schedule(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    assert {item.reference_kind for item in plan.test_applications} == {
        TestReferenceKind.WITHIN_CIRCUIT,
        TestReferenceKind.ADJACENT_CIRCUIT,
        TestReferenceKind.PE_BONDED_ACCESSIBLE_PART,
        TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART,
        TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL,
    }


def test_within_circuit_reaches_the_schedule_through_a_determination_of_a_net(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    within = [
        item
        for item in plan.test_applications
        if item.reference_kind is TestReferenceKind.WITHIN_CIRCUIT
    ]
    assert {item.test_kind for item in within} == {TestKind.WORKING_VOLTAGE_DETERMINATION}
    assert {item.high_side_net_ids for item in within} == {(LIVE_A,), (LIVE_B,), (LIVE_C,)}
    assert all(item.low_side_net_ids == () for item in within)
    assert all(item.covered_pair_ids == () for item in within)


def test_an_override_at_one_pair_of_a_group_does_not_lower_the_group_s_test(
    package: RulePackage,
) -> None:
    """A recorded reduction applies where it was recorded; the group is still tested as one."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    reduced = pair_between(project, LIVE_A, ENCLOSURE)
    project = _with_override(project, reduced.id, Decimal(50))
    plan = build(project, package)
    application = one(plan, reduced, TestKind.IMPULSE_WITHSTAND)
    assert application.voltage is not None
    assert application.voltage.value > Decimal(50)
    assert CONFLICTING_APPLICATION_WARNING in {warning.code for warning in plan.warnings}


def test_a_reduction_recorded_on_an_internal_device_carries_its_monitoring_dependency(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    project = _with_override(project, pair.id, Decimal(50), spd=True)
    plan = build(project, package)
    assessment = assessment_for(plan, pair)
    dependency = assessment.spd_monitoring_dependency
    assert dependency is not None
    assert dependency.required_type_test_semantic_id == ids.TEST_INTERNAL_SPD_MONITORING
    assert SPD_MONITORING_OWED_WARNING in {warning.code for warning in plan.warnings}
    assert any(ids.TEST_INTERNAL_SPD_MONITORING in item for item in plan.unresolved_inputs)


def test_a_verified_reduction_does_not_take_the_pair_s_insulation_impulse_test_away(
    package: RulePackage,
) -> None:
    """Both are owed: the insulation test at the pair's construction, and the reduction's own.

    Verifying that a reduction does what is claimed for it is a separate type test applied to
    the equipment. Selecting its procedure in place of the construction procedure deleted a
    verification from the schedule for every pair whose stress somebody had reduced.
    """
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    project = _with_override(project, pair.id, Decimal(50))
    plan = build(project, package)
    insulation = one(plan, pair, TestKind.IMPULSE_WITHSTAND)
    assert f"{ids.TEST_IMPULSE_PROCEDURE}.insulation_basic" in insulation.source_rule_ids
    reduction = one(plan, pair, TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION)
    assert reduction.source_rule_ids == (f"{ids.TEST_IMPULSE_PROCEDURE}.transient_reduction",)
    assert any(
        "the primary to enclosure insulation" in item for item in reduction.preparation_steps
    )


def test_the_reduction_verification_is_not_planned_at_the_reduced_voltage(
    package: RulePackage,
) -> None:
    """Its voltage is not the pair's, and the package projects no route that states it."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    project = _with_override(project, pair.id, Decimal(50))
    reduction = one(build(project, package), pair, TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION)
    assert reduction.voltage is None
    assert reduction.applicability is TestApplicability.ENGINEERING_INPUT_REQUIRED
    assert any(ids.TEST_IMPULSE_SELECTION in item for item in reduction.unresolved_inputs)


def test_a_pair_with_no_reduction_owes_no_reduction_verification(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    assert applications_for(plan, pair, TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION) == ()


def test_a_pair_with_no_reduction_carries_no_monitoring_dependency(
    project: Project, package: RulePackage
) -> None:
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assert assessment_for(build(project, package), pair).spd_monitoring_dependency is None


# --- obligations no projected rule carries ---------------------------------------------------
#
# Each of these is a requirement of the standard whose subclause the active package projects no
# rule for, so none of them can arrive on a source rule id and every one of them reached the
# schedule as nothing at all before this. What the assertions pin is that the obligation is in
# the row a test house reads, and that its own deciding input - where the project holds one -
# narrows it to the pairs it belongs to.


def voltage_rows(plan: VerificationPlan, pair: PairCase) -> tuple[TestApplication, ...]:
    """Every AC and DC dielectric row covering ``pair``, in whatever order the plan sorted."""

    return tuple(
        item
        for item in plan.test_applications
        if pair.id in item.covered_pair_ids
        and item.test_kind in (TestKind.AC_DIELECTRIC, TestKind.DC_DIELECTRIC)
    )


def states(application: TestApplication, *fragments: str) -> bool:
    """Whether one preparation step of ``application`` carries every one of ``fragments``."""

    return any(
        all(fragment in step for fragment in fragments) for step in application.preparation_steps
    )


def homogeneous(project: Project) -> Project:
    """The same project dimensioned for a homogeneous field, which is a project default."""

    return project.model_copy(
        update={
            "defaults": project.defaults.model_copy(
                update={"field_condition": FieldCondition.HOMOGENEOUS}
            )
        }
    )


def test_a_homogeneous_clearance_is_impulse_tested_across_the_clearance_itself(
    project: Project, package: RulePackage
) -> None:
    """The reduction is permitted at a price, and the price is a test at the distance."""
    plan = build(homogeneous(project), package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    impulse = one(plan, pair, TestKind.IMPULSE_WITHSTAND)
    assert states(impulse, "4.4.7.4.4", "5.2.2.1", "as close to that distance")


def test_an_inhomogeneous_clearance_is_not_told_to_test_at_the_distance(
    project: Project, package: RulePackage
) -> None:
    """The condition is one the project answers, so it narrows rather than being stated always."""
    impulse = one(
        build(project, package),
        pair_between(project, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    )
    assert not states(impulse, "dimensioned for a homogeneous field")


def test_a_homogeneous_field_under_a_reinforced_construction_is_reported_as_a_finding(
    package: RulePackage,
) -> None:
    """The subclause offers that reduction to basic and supplementary insulation only."""
    project = homogeneous(
        with_protection(
            verification_topology(
                supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
            ),
            REINFORCED,
        )
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assessment_for(build(project, package), pair)
    assert any(
        "4.4.7.4.4" in item and "not available here" in item
        for item in assessment.unresolved_inputs
    )


def test_the_layer_removal_is_stated_on_both_tests_that_carry_it(
    project: Project, package: RulePackage
) -> None:
    """A layer below basic insulation would carry part of the test voltage in either test."""
    plan = build(project, package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    rows = (one(plan, pair, TestKind.IMPULSE_WITHSTAND), *voltage_rows(plan, pair))
    assert rows
    for row in rows:
        assert states(row, "4.4.7.4.4", "does not reach at least basic insulation")


def test_the_unmeasurable_distance_situation_is_stated_rather_than_answered(
    project: Project, package: RulePackage
) -> None:
    """Nothing in the project says whether a distance can be measured, so the plan says so."""
    impulse = one(
        build(project, package),
        pair_between(project, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    )
    assert states(impulse, "5.2.2.1", "neither measured nor inspected")


def test_every_voltage_test_is_performed_with_the_enclosure_closed(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    rows = voltage_rows(plan, pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    for row in rows:
        assert states(row, "5.2.3.4.4", "doors shut")
        assert states(row, "5.2.3.4.4", "leaves no opening giving access")


def test_the_enclosure_condition_is_not_stated_on_the_impulse_row(
    project: Project, package: RulePackage
) -> None:
    """It belongs to the voltage test, and a row carrying every obligation carries none usefully."""
    impulse = one(
        build(project, package),
        pair_between(project, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    )
    assert not states(impulse, "doors shut")


def test_a_screened_construction_keeps_its_screen_connected_through_the_voltage_test(
    package: RulePackage,
) -> None:
    """The screen is what makes the construction enhanced; a test without it verifies another."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.PROTECTIVE_SCREEN_PLUS_BASIC,
    )
    rows = voltage_rows(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    for row in rows:
        assert states(row, "screen combined with basic insulation", "5.2.3.4.4", "bond")


def test_a_pair_with_no_screen_is_told_nothing_about_one(
    project: Project, package: RulePackage
) -> None:
    rows = voltage_rows(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    assert not any(states(row, "screen combined with basic insulation") for row in rows)


def test_a_recorded_reducing_device_is_disconnected_and_its_connection_restored(
    package: RulePackage,
) -> None:
    """Both are mandatory, and the restoration is the half that keeps the equipment protected."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    rows = voltage_rows(
        build(_with_override(project, pair.id, Decimal(50), spd=True), package), pair
    )
    assert rows
    for row in rows:
        assert states(row, "5.2.3.4.3", "reduces impulse voltages", "Disconnect it")
        assert states(row, "5.2.3.4.3", "restore that connection with care")


def test_a_pair_with_no_reducing_device_is_told_nothing_to_disconnect(
    project: Project, package: RulePackage
) -> None:
    rows = voltage_rows(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    assert not any(states(row, "reduces impulse voltages is recorded") for row in rows)
    assert not any(states(row, "restore that connection with care") for row in rows)


def test_the_monitoring_circuits_that_must_be_disconnected_are_reported_not_guessed(
    project: Project, package: RulePackage
) -> None:
    """The obligation is unconditional; which nets it names is not something #35 records."""
    rows = voltage_rows(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    for row in rows:
        assert any(
            "5.2.3.4.3" in item and "monitoring or protection circuit" in item
            for item in row.unresolved_inputs
        )


def test_the_component_that_may_be_disconnected_stays_a_permission(
    project: Project, package: RulePackage
) -> None:
    rows = voltage_rows(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert rows
    for row in rows:
        assert states(row, "5.2.3.4.3", "permission and not a requirement")


def test_a_protective_impedance_states_both_routes_and_the_two_tests_it_owes(
    package: RulePackage,
) -> None:
    """Treating it as a disclosure dropped a type test and a routine test the standard names."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.PROTECTIVE_IMPEDANCE,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    plan = build(project, package)
    rows = voltage_rows(plan, pair)
    assert rows
    for row in rows:
        assert states(row, "5.2.3.4.3", "included in the test", "carefully restored")
    assert any(
        "5.2.3.6" in item and "type test" in item and "routine test" in item
        for item in assessment_for(plan, pair).unresolved_inputs
    )


def test_an_enhanced_component_is_tested_before_it_is_assembled(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(
            supply_configurations=(mains_configuration(),), insulation=InsulationType.REINFORCED
        ),
        REINFORCED,
    )
    impulse = one(
        build(project, package),
        pair_between(project, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    )
    assert states(impulse, "5.2.3.2", "before it is assembled")


def test_a_basic_pair_is_told_nothing_about_testing_before_assembly(
    project: Project, package: RulePackage
) -> None:
    impulse = one(
        build(project, package),
        pair_between(project, LIVE_A, ENCLOSURE),
        TestKind.IMPULSE_WITHSTAND,
    )
    assert not states(impulse, "before it is assembled")


def test_every_electrical_row_names_the_clause_that_requires_it(
    project: Project, package: RulePackage
) -> None:
    """The requirement is gated, and a requirement asserted without its gate is not traceable."""
    plan = build(project, package)
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    rows = (one(plan, pair, TestKind.IMPULSE_WITHSTAND), *voltage_rows(plan, pair))
    assert rows
    for row in rows:
        assert states(row, "5.2.3.1", "4.4.7.4", "4.4.7.8")


def test_another_reviewed_means_carries_the_failure_analysis_its_permission_attaches(
    package: RulePackage,
) -> None:
    """The member is not one of 4.4.5.1's; what permits it also conditions it."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.OTHER_REVIEWED_MEANS,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert any(
        "4.4.2.7" in item and "failure analysis" in item and "4.1 and 4.4" in item
        for item in assessment.unresolved_inputs
    )


def test_supplementary_insulation_alone_is_questioned_rather_than_planned_from(
    package: RulePackage,
) -> None:
    """It is defined as applied in addition to basic insulation, so alone it names half a means."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        ProtectionImplementation.SUPPLEMENTARY_INSULATION,
    )
    assessment = assessment_for(build(project, package), pair_between(project, LIVE_A, ENCLOSURE))
    assert any(
        "4.4.4.5" in item and "4.4.4.1" in item and "additional to" in item
        for item in assessment.unresolved_inputs
    )


def test_a_transformer_attenuation_raises_the_showing_it_owes(package: RulePackage) -> None:
    """#36 resolves the permission and records the method; the obligation lands in this plan."""
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    # Across the verified barrier: the attenuation permission is refused anywhere else, which is
    # #36's own gate and not this plan's.
    pair = pair_between(project, LIVE_A, LIVE_C)
    project = _with_override(
        project,
        pair.id,
        Decimal(200),
        basis=ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER,
    )
    plan = build(project, package)
    assert HF_TRANSFORMER_SHOWING_WARNING in {warning.code for warning in plan.warnings}
    reduction = one(plan, pair, TestKind.TRANSIENT_OVERVOLTAGE_REDUCTION)
    assert states(reduction, "4.4.7.2.6", "shown by the impulse test", "SYN-RED-1")


def test_a_reduction_on_another_basis_owes_no_transformer_showing(package: RulePackage) -> None:
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)), BASIC
    )
    pair = pair_between(project, LIVE_A, LIVE_C)
    plan = build(_with_override(project, pair.id, Decimal(200)), package)
    assert HF_TRANSFORMER_SHOWING_WARNING not in {warning.code for warning in plan.warnings}


# --- status ---------------------------------------------------------------------------------


def test_a_selection_nobody_confirmed_keeps_the_pair_under_review(
    package: RulePackage,
) -> None:
    project = with_protection(
        verification_topology(supply_configurations=(mains_configuration(),)),
        BASIC,
        review=ReviewState.NEEDS_REVIEW,
    )
    pair = pair_between(project, LIVE_A, ENCLOSURE)
    assessment = assessment_for(build(project, package), pair)
    assert assessment.status is VerificationStatus.ENGINEERING_REVIEW_REQUIRED


def test_a_plan_with_anything_outstanding_is_not_complete(
    project: Project, package: RulePackage
) -> None:
    plan = build(project, package)
    assert not plan.is_complete
    assert plan.unresolved_inputs


def plan_applications(plan: VerificationPlan, pair: PairCase) -> tuple[TestApplication, ...]:
    return tuple(item for item in plan.test_applications if pair.id in item.covered_pair_ids)


def _interpolated(base_id: str, purpose: str, form: str, row: Decimal) -> Decimal:
    """What a linear route gives at ``row``, computed from the fixture's own bands."""

    from tests.fixtures.verification_topologies import DIELECTRIC_ROW_BANDS

    lower_index = max(index for index, band in enumerate(DIELECTRIC_ROW_BANDS) if band <= row)
    if DIELECTRIC_ROW_BANDS[lower_index] == row:
        return dielectric_cell(base_id, purpose, form, lower_index)
    upper_index = lower_index + 1
    lower, upper = DIELECTRIC_ROW_BANDS[lower_index], DIELECTRIC_ROW_BANDS[upper_index]
    weight = (row - lower) / (upper - lower)
    low_value = dielectric_cell(base_id, purpose, form, lower_index)
    high_value = dielectric_cell(base_id, purpose, form, upper_index)
    return low_value + (high_value - low_value) * weight


def _identified(package: RulePackage) -> RulePackage:
    """The same package with a SHA-256 identity, which a generated test id is derived from."""

    return package.model_copy(update={"package_sha256": "b" * 64})


def _net_evidence(net_id: UUID, value_v: Decimal, index: int) -> VoltageEvidence:
    """One circuit's own approved working voltage, which is what keys a DVC A-s adjacency."""

    return VoltageEvidence(
        id=UUID(int=910 + index),
        net_id=net_id,
        quantity_kind=VoltageQuantityKind.RECURRING_PEAK,
        value_v=value_v,
        method=VoltageEvidenceMethod.CALCULATION,
        operating_condition="rated load",
        source_reference=f"SYN-NET-EV-{index}",
        recorded_at=RECORDED_AT,
        approval_state=EvidenceApprovalState.APPROVED_FOR_DESIGN,
    )


def _evidence(pair_id: UUID, value_v: Decimal) -> VoltageEvidence:
    return VoltageEvidence(
        id=UUID(int=901),
        pair_id=pair_id,
        quantity_kind=VoltageQuantityKind.RECURRING_PEAK,
        value_v=value_v,
        method=VoltageEvidenceMethod.CALCULATION,
        operating_condition="rated load",
        source_reference="SYN-EV-1",
        recorded_at=RECORDED_AT,
        approval_state=EvidenceApprovalState.APPROVED_FOR_DESIGN,
    )


def _with_override(
    project: Project,
    pair_id: UUID,
    value_v: Decimal,
    *,
    spd: bool = False,
    basis: ImpulseOverrideBasis | None = None,
) -> Project:
    """One pair carrying a recorded reduction, on whichever basis the caller is testing.

    ``spd`` is the shorthand for the device basis, which needs a placement and a degradability
    beside it; ``basis`` names any other. Both are here rather than in two helpers because the
    only thing that differs between them is what the model requires alongside the basis.
    """

    device = spd or basis is ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER
    resolved = basis or (
        ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER
        if spd
        else ImpulseOverrideBasis.VERIFIED_CIRCUIT_CHARACTERISTIC
    )
    transformer = resolved is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER
    override = VerifiedImpulseOverride(
        value_v=value_v,
        basis=resolved,
        verification_method=ReductionVerificationMethod.TEST,
        justification="Synthetic reduction for this test module.",
        evidence_reference="SYN-RED-1",
        affected_location="the primary to enclosure insulation",
        transformer_frequency_hz=Decimal(45678) if transformer else None,
        spd_device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT if device else None,
        spd_device_degradable=True if device else None,
    )
    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"impulse_override": override})
                if pair.id == pair_id
                else pair
                for pair in project.pairs
            )
        }
    )
