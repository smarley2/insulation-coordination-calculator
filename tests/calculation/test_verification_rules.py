"""The verification rule adapter's blocking behaviour. Synthetic packages only; no IEC content."""

from __future__ import annotations

import pytest

from insulation_coordination.calculation.verification_rules import (
    DIELECTRIC_PURPOSES,
    FOIL_APPLICABILITY_ROUTE,
    IMPULSE_PROCEDURE_VARIANTS,
    IMPULSE_SELECTION_COLUMN_LABELS,
    IMPULSE_SELECTION_PAIRS,
    PACKAGE_CLASSIFICATIONS,
    PARTIAL_DISCHARGE_APPLICABILITY_ROUTE,
    PRECONDITIONING_APPLICABILITY_ROUTE,
    PRECONDITIONING_ELECTRICAL_ROUTE,
    PRECONDITIONING_MATERIAL_ROUTE,
    PROTECTION_REQUIREMENT_OUTPUT,
    READ_SEMANTIC_IDS,
    RULES_READ_ELSEWHERE,
    VOLTAGE_FORMS,
    VerificationRuleBlockCode,
    VerificationRulesUnavailable,
    classifications_of,
    dielectric_column_label,
    read_verification_rules,
    verification_rule_blocks,
)
from insulation_coordination.domain.dvc import DVC_INPUT, PROTECTION_TARGET_DIMENSIONS
from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionRule,
    ProcedureRule,
    RulePackage,
    Table,
    TableAxis,
)
from insulation_coordination.domain.verification import TestClassification
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION
from tests.fixtures.synthetic_rules import synthetic_verification_rule_package
from tests.fixtures.verification_topologies import with_protection_matrix


@pytest.fixture
def verification_package() -> RulePackage:
    return with_protection_matrix(synthetic_verification_rule_package())


def _blocks(
    package: RulePackage | None,
) -> tuple[tuple[VerificationRuleBlockCode, str | None], ...]:
    return tuple(
        (block.code, block.semantic_rule_id) for block in verification_rule_blocks(package)
    )


def _decision(package: RulePackage, rule_id: str) -> DecisionRule:
    return next(rule for rule in package.decisions if rule.id == rule_id)


def _procedure(package: RulePackage, rule_id: str) -> ProcedureRule:
    return next(rule for rule in package.procedures if rule.id == rule_id)


def _table(package: RulePackage, table_id: str) -> Table:
    return next(item for item in package.tables if item.id == table_id)


def _replace(package: RulePackage, field: str, rule: object) -> RulePackage:
    existing: tuple[object, ...] = getattr(package, field)
    return package.model_copy(
        update={
            field: tuple(
                rule if item.id == rule.id else item  # type: ignore[attr-defined]
                for item in existing
            )
        }
    )


def _without(package: RulePackage, field: str, rule_id: str) -> RulePackage:
    existing: tuple[object, ...] = getattr(package, field)
    return package.model_copy(
        update={
            field: tuple(item for item in existing if item.id != rule_id)  # type: ignore[attr-defined]
        }
    )


# --- the accept path ------------------------------------------------------------------


def test_an_approved_package_resolves_every_required_identifier(
    verification_package: RulePackage,
) -> None:
    rules = read_verification_rules(verification_package)

    assert rules.dvc_voltage_limits.id == ids.DVC_VOLTAGE_LIMITS
    assert rules.dvc_protection_matrix.id == ids.DVC_PROTECTION_MATRIX
    assert rules.dvc_fault_time_voltage.id == ids.DVC_FAULT_TIME_VOLTAGE
    assert rules.working_voltage_determination.id == ids.TEST_WORKING_VOLTAGE_DETERMINATION
    assert rules.internal_spd_monitoring.id == ids.TEST_INTERNAL_SPD_MONITORING
    assert rules.assembled_routine_exemption.id == ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION
    assert rules.partial_discharge.procedure.id == ids.TEST_PARTIAL_DISCHARGE
    assert rules.accessible_surface_foil.procedure.id == ids.TEST_ACCESSIBLE_SURFACE_FOIL
    assert rules.dielectric_disconnection.id == ids.TEST_DIELECTRIC_DISCONNECTION
    assert rules.dielectric_topology_selection.id == ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION
    assert rules.dielectric_application_duration.id == ids.TEST_DIELECTRIC_APPLICATION_DURATION
    assert rules.dielectric_acceptance.id == ids.TEST_DIELECTRIC_ACCEPTANCE
    assert verification_rule_blocks(verification_package) == ()


# --- the body of clause 5.2.3.4 --------------------------------------------------------


DIELECTRIC_CLAUSE_IDS = (
    ids.TEST_DIELECTRIC_DISCONNECTION,
    ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION,
    ids.TEST_DIELECTRIC_APPLICATION_DURATION,
    ids.TEST_DIELECTRIC_ACCEPTANCE,
)


def test_a_package_predating_the_current_importer_blocks_with_every_rule_named(
    verification_package: RulePackage,
) -> None:
    """A package built before these rules existed cannot carry them, and says so by name.

    Never a crash and never a silent pass: the four identifiers were declared with the
    importer version this application resolves against, so a package from before it is missing
    all four and its Table 27 routes still label their columns by position.
    """
    older = verification_package.model_copy(
        update={
            "procedures": tuple(
                item
                for item in verification_package.procedures
                if item.id not in DIELECTRIC_CLAUSE_IDS
            ),
            "decisions": tuple(
                item
                for item in verification_package.decisions
                if item.id not in DIELECTRIC_CLAUSE_IDS
            ),
            "tables": tuple(
                item.model_copy(
                    update={
                        "column_axis": item.column_axis.model_copy(
                            update={
                                "labels": tuple(
                                    f"selected_test_voltage_col{index + 2}_v"
                                    for index in range(len(item.column_axis.labels))
                                )
                            }
                        )
                    }
                )
                if item.id.startswith(ids.TEST_IMPULSE_SELECTION)
                else item
                for item in verification_package.tables
            ),
        }
    )
    blocks = verification_rule_blocks(older)
    missing = {
        block.semantic_rule_id
        for block in blocks
        if block.code is VerificationRuleBlockCode.RULE_MISSING
    }
    assert missing == set(DIELECTRIC_CLAUSE_IDS)
    assert any(
        block.code is VerificationRuleBlockCode.UNEXPECTED_SHAPE
        and "labels no column" in block.message
        for block in blocks
    )
    with pytest.raises(VerificationRulesUnavailable):
        read_verification_rules(older)


def test_a_duration_rule_stating_no_duration_is_refused(
    verification_package: RulePackage,
) -> None:
    """It is resolved for its duration, so one that states none answers nothing."""
    blank = verification_package.model_copy(
        update={
            "procedures": tuple(
                item.model_copy(update={"duration": None})
                if item.id == ids.TEST_DIELECTRIC_APPLICATION_DURATION
                else item
                for item in verification_package.procedures
            )
        }
    )
    blocks = verification_rule_blocks(blank)
    assert any(
        block.semantic_rule_id == ids.TEST_DIELECTRIC_APPLICATION_DURATION
        and block.code is VerificationRuleBlockCode.UNEXPECTED_SHAPE
        for block in blocks
    )


def test_a_selection_rule_declaring_another_input_is_refused(
    verification_package: RulePackage,
) -> None:
    """Five inputs are supplied, so a rule declaring a sixth can be asked nothing at all."""
    from insulation_coordination.domain.rules import DecisionInput

    widened = verification_package.model_copy(
        update={
            "decisions": tuple(
                item.model_copy(
                    update={
                        "inputs": (
                            *item.inputs,
                            DecisionInput(name="something_else", kind="boolean"),
                        )
                    }
                )
                if item.id == ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION
                else item
                for item in verification_package.decisions
            )
        }
    )
    assert any(
        block.semantic_rule_id == ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION
        and block.code is VerificationRuleBlockCode.UNEXPECTED_SHAPE
        for block in verification_rule_blocks(widened)
    )


def test_the_impulse_selection_routes_label_both_insulation_class_columns(
    verification_package: RulePackage,
) -> None:
    """Selecting a column by class is only possible where the route names the classes."""
    routes = read_verification_rules(verification_package).impulse_selection
    for pair in (routes.mains_circuits, routes.non_mains_circuits):
        for form in ("ac", "dc"):
            labels = pair.for_form(form).column_axis.labels
            assert set(IMPULSE_SELECTION_COLUMN_LABELS) <= set(labels)


def test_a_dielectric_route_labelling_its_column_otherwise_is_refused(
    verification_package: RulePackage,
) -> None:
    """A route read by label answers nothing where the label is not the one it declares."""
    relabelled = verification_package.model_copy(
        update={
            "tables": tuple(
                item.model_copy(
                    update={
                        "column_axis": item.column_axis.model_copy(
                            update={"labels": ("some-other-column",)}
                        )
                    }
                )
                if item.id.startswith(ids.TEST_MAINS_DIELECTRIC_VALUES)
                else item
                for item in verification_package.tables
            )
        }
    )
    assert any(
        block.code is VerificationRuleBlockCode.UNEXPECTED_SHAPE
        and "labels no column" in block.message
        for block in verification_rule_blocks(relabelled)
    )


def test_each_dielectric_route_labels_its_own_data_column(
    verification_package: RulePackage,
) -> None:
    """One column, still named rather than taken at whichever position it sits."""
    rules = read_verification_rules(verification_package)
    for tables in (rules.mains_dielectric_values, rules.non_mains_dielectric_values):
        for purpose in DIELECTRIC_PURPOSES:
            pair = getattr(tables, purpose)
            for form in ("ac", "dc"):
                assert dielectric_column_label(purpose, form) in (
                    pair.for_form(form).column_axis.labels
                )


def test_the_read_identifiers_are_the_seventeen_the_issue_requires() -> None:
    # Every identifier this adapter resolves is a required inventory item, and none of the
    # ones it deliberately leaves to another consumer is also claimed here. Thirteen from the
    # issue's own list, plus the four the body of clause 5.2.3.4 was given.
    from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
        REQUIRED_SEMANTIC_IDS,
    )

    assert len(READ_SEMANTIC_IDS) == 17
    assert READ_SEMANTIC_IDS <= REQUIRED_SEMANTIC_IDS
    assert RULES_READ_ELSEWHERE <= REQUIRED_SEMANTIC_IDS
    assert not READ_SEMANTIC_IDS & RULES_READ_ELSEWHERE


def test_each_impulse_variant_resolves_its_own_procedure(
    verification_package: RulePackage,
) -> None:
    procedures = read_verification_rules(verification_package).impulse_procedure

    assert {
        procedures.insulation_basic.id,
        procedures.insulation_reinforced.id,
        procedures.transient_reduction.id,
    } == {f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}" for variant in IMPULSE_PROCEDURE_VARIANTS}


def test_each_selection_route_resolves_its_own_ac_and_dc_table(
    verification_package: RulePackage,
) -> None:
    selection = read_verification_rules(verification_package).impulse_selection

    assert selection.mains_circuits.for_form("ac").id == (
        f"{ids.TEST_IMPULSE_SELECTION}.mains_circuits.ac"
    )
    assert selection.non_mains_circuits.for_form("dc").id == (
        f"{ids.TEST_IMPULSE_SELECTION}.non_mains_circuits.dc"
    )
    assert selection.mains_circuits.ac.id != selection.non_mains_circuits.ac.id


def test_an_enhanced_type_value_is_never_the_routine_and_basic_one(
    verification_package: RulePackage,
) -> None:
    rules = read_verification_rules(verification_package)

    for tables in (rules.mains_dielectric_values, rules.non_mains_dielectric_values):
        assert tables.enhanced_type.ac.id != tables.routine_and_basic_type.ac.id
    assert (
        rules.mains_dielectric_values.enhanced_type.ac.id
        != rules.non_mains_dielectric_values.enhanced_type.ac.id
    )


def test_a_gated_procedure_arrives_with_the_gate_it_points_at(
    verification_package: RulePackage,
) -> None:
    rules = read_verification_rules(verification_package)

    assert rules.partial_discharge.applicability.id == PARTIAL_DISCHARGE_APPLICABILITY_ROUTE
    assert rules.accessible_surface_foil.applicability.id == FOIL_APPLICABILITY_ROUTE
    assert rules.preconditioning.applicability.id == PRECONDITIONING_APPLICABILITY_ROUTE
    assert rules.preconditioning.electrical_tests.id == PRECONDITIONING_ELECTRICAL_ROUTE
    assert rules.preconditioning.material.id == PRECONDITIONING_MATERIAL_ROUTE


def test_classifications_are_translated_out_of_the_package_vocabulary(
    verification_package: RulePackage,
) -> None:
    rules = read_verification_rules(verification_package)

    assert classifications_of(rules.working_voltage_determination) == (TestClassification.TYPE,)
    assert set(classifications_of(rules.impulse_procedure.insulation_basic)) == {
        TestClassification.TYPE,
        TestClassification.SAMPLE,
    }
    # A procedure the package leaves unclassified stays unclassified: this seam never picks one.
    assert classifications_of(rules.accessible_surface_foil.procedure) == ()
    assert set(PACKAGE_CLASSIFICATIONS.values()) == set(TestClassification)


# --- the blocking path ----------------------------------------------------------------


def test_no_package_blocks_and_never_returns_a_value() -> None:
    assert _blocks(None) == ((VerificationRuleBlockCode.NO_PACKAGE, None),)

    with pytest.raises(VerificationRulesUnavailable) as error:
        read_verification_rules(None)

    assert error.value.codes == (VerificationRuleBlockCode.NO_PACKAGE,)


@pytest.mark.parametrize(
    "flag, code",
    (
        ("approved", VerificationRuleBlockCode.PACKAGE_NOT_APPROVED),
        ("compatible", VerificationRuleBlockCode.PACKAGE_NOT_COMPATIBLE),
    ),
)
def test_an_untrusted_package_is_refused_whole(
    verification_package: RulePackage, flag: str, code: VerificationRuleBlockCode
) -> None:
    untrusted = verification_package.model_copy(
        update={"manifest": verification_package.manifest.model_copy(update={flag: False})}
    )

    # One block, not fourteen: the one thing to fix is the approval, not the content.
    assert _blocks(untrusted) == ((code, None),)
    with pytest.raises(VerificationRulesUnavailable):
        read_verification_rules(untrusted)


def test_a_wrong_edition_package_carries_the_right_identifiers_and_still_blocks() -> None:
    wrong = with_protection_matrix(synthetic_verification_rule_package(edition=f"{EDITION}-draft"))

    codes = {code for code, _rule_id in _blocks(wrong)}
    blocked_ids = {rule_id for _code, rule_id in _blocks(wrong)}

    assert codes == {VerificationRuleBlockCode.WRONG_EDITION}
    assert ids.TEST_WORKING_VOLTAGE_DETERMINATION in blocked_ids
    assert ids.DVC_FAULT_TIME_VOLTAGE in blocked_ids


@pytest.mark.parametrize(
    "field, rule_id",
    (
        ("decisions", ids.DVC_VOLTAGE_LIMITS),
        ("decisions", ids.DVC_PROTECTION_MATRIX),
        ("decisions", ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION),
        ("decisions", PARTIAL_DISCHARGE_APPLICABILITY_ROUTE),
        ("decisions", FOIL_APPLICABILITY_ROUTE),
        ("decisions", PRECONDITIONING_APPLICABILITY_ROUTE),
        ("procedures", ids.TEST_WORKING_VOLTAGE_DETERMINATION),
        ("procedures", ids.TEST_INTERNAL_SPD_MONITORING),
        ("procedures", ids.TEST_PARTIAL_DISCHARGE),
        ("procedures", ids.TEST_ACCESSIBLE_SURFACE_FOIL),
        ("procedures", PRECONDITIONING_ELECTRICAL_ROUTE),
        ("procedures", PRECONDITIONING_MATERIAL_ROUTE),
        ("procedures", f"{ids.TEST_IMPULSE_PROCEDURE}.insulation_reinforced"),
        ("tables", f"{ids.TEST_IMPULSE_SELECTION}.mains_circuits.dc"),
        ("tables", f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.enhanced_type.ac"),
        ("tables", f"{ids.TEST_NON_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.dc"),
        ("curves", ids.DVC_FAULT_TIME_VOLTAGE),
    ),
)
def test_every_missing_rule_blocks_by_name(
    verification_package: RulePackage, field: str, rule_id: str
) -> None:
    incomplete = _without(verification_package, field, rule_id)

    assert (VerificationRuleBlockCode.RULE_MISSING, rule_id) in _blocks(incomplete)
    with pytest.raises(VerificationRulesUnavailable):
        read_verification_rules(incomplete)


def test_every_reason_is_reported_at_once_rather_than_the_first(
    verification_package: RulePackage,
) -> None:
    broken = _without(verification_package, "procedures", ids.TEST_WORKING_VOLTAGE_DETERMINATION)
    broken = _without(broken, "curves", ids.DVC_FAULT_TIME_VOLTAGE)
    broken = _without(broken, "tables", f"{ids.TEST_IMPULSE_SELECTION}.non_mains_circuits.ac")
    broken = _without(broken, "decisions", ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION)

    reported = {rule_id for _code, rule_id in _blocks(broken)}

    assert reported == {
        ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        ids.DVC_FAULT_TIME_VOLTAGE,
        f"{ids.TEST_IMPULSE_SELECTION}.non_mains_circuits.ac",
        ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    }
    with pytest.raises(VerificationRulesUnavailable) as error:
        read_verification_rules(broken)
    assert len(error.value.blocks) == 4


# --- shape refusals -------------------------------------------------------------------


def test_a_decision_declaring_one_extra_input_is_refused_on_equality(
    verification_package: RulePackage,
) -> None:
    # Not containment: the evaluator answers input_required for any declared input a caller
    # omits, so one extra declared input makes every query return nothing at all.
    rule = _decision(verification_package, ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION)
    widened = rule.model_copy(
        update={
            "inputs": (*rule.inputs, DecisionInput(name="synthetic_extra_input", kind="boolean"))
        }
    )

    assert (
        VerificationRuleBlockCode.UNEXPECTED_SHAPE,
        ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    ) in _blocks(_replace(verification_package, "decisions", widened))


def test_the_protection_matrix_is_resolved_by_the_dimensions_the_guidance_service_reads_it_by(
    verification_package: RulePackage,
) -> None:
    """One reading of Table 3, so a plan's requirement and a guidance page cannot disagree."""
    rule = _decision(verification_package, ids.DVC_PROTECTION_MATRIX)

    assert {item.name for item in rule.inputs} == {DVC_INPUT, *PROTECTION_TARGET_DIMENSIONS}
    assert PROTECTION_REQUIREMENT_OUTPUT in {item.name for item in rule.outputs}


def test_a_protection_matrix_shaped_for_another_question_is_refused(
    verification_package: RulePackage,
) -> None:
    """A plan asks this rule what protection is required, so presence is no longer enough."""
    rule = _decision(verification_package, ids.DVC_PROTECTION_MATRIX)
    renamed = rule.model_copy(
        update={
            "inputs": tuple(
                item.model_copy(update={"name": "synthetic_other_dimension"})
                if item.name == "person_scope"
                else item
                for item in rule.inputs
            )
        }
    )

    assert (VerificationRuleBlockCode.UNEXPECTED_SHAPE, ids.DVC_PROTECTION_MATRIX) in _blocks(
        _replace(verification_package, "decisions", renamed)
    )


def test_a_decision_missing_an_output_this_application_reads_is_refused(
    verification_package: RulePackage,
) -> None:
    rule = _decision(verification_package, FOIL_APPLICABILITY_ROUTE)
    narrowed = rule.model_copy(
        update={
            "outputs": tuple(item for item in rule.outputs if item.name != "foil_wrap_required"),
            "rows": tuple(
                row.model_copy(
                    update={
                        "values": tuple(
                            value for value in row.values if value.name != "foil_wrap_required"
                        )
                    }
                )
                for row in rule.rows
            ),
        }
    )

    assert (VerificationRuleBlockCode.UNEXPECTED_SHAPE, FOIL_APPLICABILITY_ROUTE) in _blocks(
        _replace(verification_package, "decisions", narrowed)
    )


def test_a_procedure_that_performs_a_different_test_is_refused(
    verification_package: RulePackage,
) -> None:
    rule = _procedure(verification_package, ids.TEST_INTERNAL_SPD_MONITORING)
    mislabelled = rule.model_copy(update={"test_kind": "synthetic_other_test"})

    assert (
        VerificationRuleBlockCode.UNEXPECTED_SHAPE,
        ids.TEST_INTERNAL_SPD_MONITORING,
    ) in _blocks(_replace(verification_package, "procedures", mislabelled))


def test_a_classification_this_application_cannot_read_is_refused_not_dropped(
    verification_package: RulePackage,
) -> None:
    # Silently ignoring it would report a test as unclassified, which is what the package says
    # when it means "the source does not state one" - two different answers, one appearance.
    rule = _procedure(verification_package, ids.TEST_WORKING_VOLTAGE_DETERMINATION)
    unknown = rule.model_copy(update={"classifications": ("synthetic_unknown_classification",)})

    assert (
        VerificationRuleBlockCode.UNEXPECTED_SHAPE,
        ids.TEST_WORKING_VOLTAGE_DETERMINATION,
    ) in _blocks(_replace(verification_package, "procedures", unknown))


def test_a_procedure_gated_on_a_different_rule_is_refused(
    verification_package: RulePackage,
) -> None:
    rule = _procedure(verification_package, ids.TEST_PARTIAL_DISCHARGE)
    misdirected = rule.model_copy(
        update={"applicability_rule_id": PRECONDITIONING_APPLICABILITY_ROUTE}
    )

    assert (VerificationRuleBlockCode.UNEXPECTED_SHAPE, ids.TEST_PARTIAL_DISCHARGE) in _blocks(
        _replace(verification_package, "procedures", misdirected)
    )


@pytest.mark.parametrize(
    "update",
    (
        {"unit": "mm"},
        {"row_axis": TableAxis(id="synthetic_other_axis", unit="V", values=(1,), labels=("a",))},
        {"column_axis": TableAxis(id="synthetic_other", unit="1", values=(1,), labels=("a",))},
    ),
    ids=("unit", "row-axis", "column-axis"),
)
def test_a_table_keyed_or_denominated_differently_is_refused(
    verification_package: RulePackage, update: dict[str, object]
) -> None:
    table_id = f"{ids.TEST_MAINS_DIELECTRIC_VALUES}.routine_and_basic_type.ac"
    table = _table(verification_package, table_id)
    # A cell count that no longer matches a narrowed axis is irrelevant here: what is under
    # test is that the adapter refuses a table it cannot key its question by.
    altered = table.model_copy(update=update | {"cells": table.cells[:1]})

    assert (VerificationRuleBlockCode.UNEXPECTED_SHAPE, table_id) in _blocks(
        _replace(verification_package, "tables", altered)
    )


def test_the_route_names_cover_every_table_the_package_projects(
    verification_package: RulePackage,
) -> None:
    # The variant, pair and purpose names are built here from the base identifiers, not
    # imported from the importer recipe. This is the test that says so.
    expected = {
        f"{ids.TEST_IMPULSE_SELECTION}.{pair}.{form}"
        for pair in IMPULSE_SELECTION_PAIRS
        for form in VOLTAGE_FORMS
    } | {
        f"{base_id}.{purpose}.{form}"
        for base_id in (ids.TEST_MAINS_DIELECTRIC_VALUES, ids.TEST_NON_MAINS_DIELECTRIC_VALUES)
        for purpose in DIELECTRIC_PURPOSES
        for form in VOLTAGE_FORMS
    }

    assert {table.id for table in verification_package.tables} == expected
