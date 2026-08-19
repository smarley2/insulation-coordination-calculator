"""DvcGuidanceService: reads DVC facts from a package, never a constant.

Covers the semantic selector contract's structural guarantees plus the service's
availability and degradation behaviour. No IEC value appears here - the fixture
package's numbers are all invented, and so is the shape of its axes.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import get_args

import insulation_coordination
from insulation_coordination.domain.dvc import (
    NOT_APPLICABLE,
    PROTECTION_TARGET_DIMENSIONS,
    READ_ENVIRONMENTS,
    SELECTOR_TOKEN_LABELS,
    VOLTAGE_QUANTITY_DIMENSIONS,
    DvcGuidanceService,
    DvcVoltageQuantity,
    selector_label,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.domain.rules import DecisionRule, RulePackage
from insulation_coordination.rules.importer.axis_selectors import (
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package

#: The fixture's own Table 2 columns, as the selector tokens the adapter labels them by.
#: Named here rather than asserted as text, because the wording deliberately belongs to a
#: single constant in the module under test and is free to change.
RMS_COLUMN = ("working_voltage", "ac_rms", "normal")
MEAN_COLUMN = ("working_voltage", "dc_mean", "normal")
IMPULSE_COLUMN = ("impulse_withstand", "ac_peak_or_dc", "normal")
FAULT_COLUMN = ("fault_voltage", NOT_APPLICABLE, "single_fault_or_abnormal")


def _quantity(
    quantities: tuple[DvcVoltageQuantity, ...], tokens: tuple[str, ...]
) -> DvcVoltageQuantity:
    return next(item for item in quantities if item.label == selector_label(*tokens))


def _without_designation(package: RulePackage, dvc: DecisiveVoltageClass) -> RulePackage:
    """The same package whose DVC rules no longer declare ``dvc`` as a class they carry.

    Built with ``model_copy``, which does not re-validate: the point is a package whose
    declared vocabulary and rows disagree, which is exactly the state the adapter must
    refuse rather than resolve.
    """

    def narrowed(rule: DecisionRule) -> DecisionRule:
        inputs = tuple(
            item.model_copy(
                update={
                    "allowed_values": tuple(
                        value for value in item.allowed_values if value != dvc.value
                    )
                }
            )
            if item.name == "dvc"
            else item
            for item in rule.inputs
        )
        return rule.model_copy(update={"inputs": inputs})

    return package.model_copy(
        update={"decisions": tuple(narrowed(rule) for rule in package.decisions)}
    )


def _without_input(package: RulePackage, name: str) -> RulePackage:
    """The same package whose DVC rules no longer declare one selector dimension at all."""
    return package.model_copy(
        update={
            "decisions": tuple(
                rule.model_copy(
                    update={"inputs": tuple(item for item in rule.inputs if item.name != name)}
                )
                for rule in package.decisions
            )
        }
    )


def _without_rows_for(package: RulePackage, dvc: DecisiveVoltageClass) -> RulePackage:
    """The same package that still declares ``dvc`` but carries no cell for it anywhere."""

    def carries(rule: DecisionRule) -> DecisionRule:
        rows = tuple(
            row
            for row in rule.rows
            if not any(
                matcher.input == "dvc" and dvc.value in matcher.values for matcher in row.matchers
            )
        )
        return rule.model_copy(update={"rows": rows})

    return package.model_copy(
        update={"decisions": tuple(carries(rule) for rule in package.decisions)}
    )


# --- isolation guard: no positional table token survives outside the importer ----------


def test_no_application_module_knows_a_positional_dvc_table_token() -> None:
    """Issue #53A made both DVC tables' runtime contract semantic, and #35 consumes it.

    A physical row or column coordinate is a fact about the document's layout, not about
    the requirement, so no consumer may select by one. The importer and its recipes are
    exempt - there the coordinates are extraction provenance, which is what they are
    allowed to be. This test is the guard that the adapter never grows one back.
    """
    package_root = Path(insulation_coordination.__file__).parent
    pattern = re.compile(r"dvc-\{?\d|voltage-quantity-\{?\d|protection-context-\{?\d")

    offenders = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        if not path.relative_to(package_root).as_posix().startswith("rules/importer/")
        and pattern.search(path.read_text(encoding="utf-8"))
    )

    assert offenders == []


# --- structural guard: the selector contract this module resolves by -------------------


def test_every_dvc_but_not_evaluated_is_its_own_declared_designation() -> None:
    """No mapping table: the enum member's value *is* the designation the package declares."""
    designations = set(get_args(DvcDesignationSelector.model_fields["designation"].annotation))

    assert {
        dvc.value for dvc in DecisiveVoltageClass if dvc is not DecisiveVoltageClass.NOT_EVALUATED
    } == designations


def test_read_environments_are_declared_by_the_row_selector() -> None:
    declared = set(get_args(DvcDesignationSelector.model_fields["environment"].annotation))

    assert set(READ_ENVIRONMENTS) <= declared
    assert len(set(READ_ENVIRONMENTS)) == len(READ_ENVIRONMENTS)


def test_the_column_dimensions_are_exactly_the_selector_models_own_dimensions() -> None:
    """Drift here would silently drop a dimension from every query the adapter builds."""
    table_2 = set(Table2QuantitySelector.model_fields) - {"selector_kind"}
    table_3 = set(ProtectionTargetSelector.model_fields) - {"selector_kind"}

    assert set(VOLTAGE_QUANTITY_DIMENSIONS) == table_2
    assert set(PROTECTION_TARGET_DIMENSIONS) == table_3


def test_every_selector_token_either_table_can_carry_has_our_own_words() -> None:
    """Read from the selector models, so a widened vocabulary fails here rather than in a UI."""
    tokens = {
        token
        for model in (DvcDesignationSelector, Table2QuantitySelector, ProtectionTargetSelector)
        for name, field in model.model_fields.items()
        if name != "selector_kind"
        for token in get_args(field.annotation)
    } - {NOT_APPLICABLE}

    assert tokens <= set(SELECTOR_TOKEN_LABELS)


def test_a_label_drops_the_dimensions_that_do_not_apply() -> None:
    assert selector_label("working_voltage", NOT_APPLICABLE, "normal") == selector_label(
        "working_voltage", "normal"
    )
    assert selector_label(NOT_APPLICABLE) == "unqualified"


# --- DvcGuidanceService.limits: availability and degradation ------------------------


def test_not_evaluated_has_no_limits_to_show() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.NOT_EVALUATED)
    assert summary.available is False
    assert summary.quantities == ()
    assert summary.reason


def test_no_package_loaded_is_not_available() -> None:
    service = DvcGuidanceService(None)
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    assert summary.available is False
    assert "No rule package is loaded" in summary.reason


def test_unapproved_package_is_not_available() -> None:
    package = synthetic_dvc_rule_package()
    unapproved = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={"approved": False})}
    )
    service = DvcGuidanceService(unapproved)
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    assert summary.available is False
    assert "not approved" in summary.reason


def test_wrong_edition_package_is_refused() -> None:
    package = synthetic_dvc_rule_package(edition="1999")
    service = DvcGuidanceService(package)
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    assert summary.available is False
    assert "1999" in summary.reason


def test_package_missing_the_dvc_rule_is_not_available() -> None:
    package = synthetic_rule_package()  # no DVC rules at all
    service = DvcGuidanceService(package)
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    assert summary.available is False
    assert "iec62477_2022.dvc.voltage_limits" in summary.reason


def test_a_class_the_rule_does_not_declare_is_refused_rather_than_shown_empty() -> None:
    """What ``exhaustive=True`` used to guarantee, now stated by the adapter itself.

    Without this check the class would evaluate to nothing at all and read as a class with
    no limits, rather than as a package that does not carry the class.
    """
    package = _without_designation(synthetic_dvc_rule_package(), DecisiveVoltageClass.DVC_B)
    summary = DvcGuidanceService(package).limits(DecisiveVoltageClass.DVC_B)

    assert summary.available is False
    assert summary.quantities == ()
    assert "does not carry" in summary.reason


def test_a_rule_missing_a_selector_dimension_is_refused_rather_than_resolved() -> None:
    """A package that does not speak the contract cannot be queried against it.

    Guessing the missing dimension, or dropping it from the query, would silently widen
    every matcher and could return a cell belonging to another column.
    """
    package = _without_input(synthetic_dvc_rule_package(), "environment")
    summary = DvcGuidanceService(package).limits(DecisiveVoltageClass.DVC_AS)

    assert summary.available is False
    assert summary.quantities == ()
    assert "does not declare the selector inputs" in summary.reason


def test_protection_relationships_refuse_a_rule_missing_a_target_dimension() -> None:
    package = _without_input(synthetic_dvc_rule_package(), "person_scope")
    summary = DvcGuidanceService(package).protection_relationships(DecisiveVoltageClass.DVC_B)

    assert summary.available is False
    assert summary.relationships == ()
    assert "does not declare the selector inputs" in summary.reason


def test_a_declared_class_with_no_cell_in_any_environment_says_so() -> None:
    """Declared but uncarried is a distinct answer from a class with nothing recorded.

    Both environments in ``READ_ENVIRONMENTS`` are tried before this is concluded, so a
    class the package answers only under its dry reading is not reported this way.
    """
    package = _without_rows_for(synthetic_dvc_rule_package(), DecisiveVoltageClass.DVC_AS)
    summary = DvcGuidanceService(package).limits(DecisiveVoltageClass.DVC_AS)

    assert summary.available is False
    assert summary.quantities == ()
    assert "no reviewed cell" in summary.reason


def test_dvc_as_limits_render_numeric_values_with_their_source() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_AS)
    assert summary.available is True
    rms = _quantity(summary.quantities, RMS_COLUMN)
    assert rms.status == "value"
    assert rms.value == Decimal(11)
    assert rms.unit == "V"
    assert rms.source is not None
    assert rms.source.standard == "IEC 62477-1"


def test_dvc_b_impulse_withstand_renders_as_a_reference_not_a_number() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    impulse = _quantity(summary.quantities, IMPULSE_COLUMN)
    assert impulse.status == "reference"
    assert impulse.value is None
    assert impulse.reference_rule_id == "iec62477_2022.supply.impulse_by_system_voltage_ovc"


def test_dvc_b_fault_condition_column_renders_as_a_curve_reference() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    fault = _quantity(summary.quantities, FAULT_COLUMN)
    assert fault.status == "reference"
    assert fault.reference_rule_id == "iec62477_2022.dvc.fault_time_voltage"


def test_dvc_c_not_applicable_cell_says_so_without_a_number() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_C)
    fault = _quantity(summary.quantities, FAULT_COLUMN)
    assert fault.status == "not_applicable"
    assert fault.value is None


def test_a_class_split_by_environment_is_read_at_its_dry_condition() -> None:
    """The fixture splits DVC C; only the dry reading may reach a consumer.

    Maintainer's ruling 2026-08-11: a wet or salt-water-wet reading has no enum member, so
    nothing here can select it - and nothing here may substitute it either.
    """
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_C)

    assert _quantity(summary.quantities, RMS_COLUMN).value == Decimal(88)
    assert all(item.value != Decimal(99) for item in summary.quantities)
    # The wet reading also carries a mean-basis cell that the dry reading does not; reading
    # the dry row must not quietly borrow it.
    assert selector_label(*MEAN_COLUMN) not in {item.label for item in summary.quantities}


def test_a_combination_no_reviewed_column_carries_is_omitted_not_reported_as_a_gap() -> None:
    """Most combinations of the declared vocabularies are not cells of the table at all.

    Under the positional contract there were five known columns, so an uncovered one was
    worth naming. Under the semantic contract the adapter enumerates the cartesian product
    of the declared dimensions, and listing that as missing data would bury the cells that
    do exist.
    """
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_C)

    assert {item.label for item in summary.quantities} == {
        selector_label(*RMS_COLUMN),
        selector_label(*FAULT_COLUMN),
    }


# --- DvcGuidanceService.protection_relationships ------------------------------------


def test_protection_relationships_are_read_from_the_package_for_the_class() -> None:
    """Nothing is withheld any more: the class is selected by its own designation."""
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.protection_relationships(DecisiveVoltageClass.DVC_C)

    assert summary.available is True
    assert [item.requirement for item in summary.relationships] == [
        "enhanced_protection",
        "basic_protection",
    ]
    assert all(item.source.standard == "IEC 62477-1" for item in summary.relationships)
    assert len({item.label for item in summary.relationships}) == 2


def test_every_cell_carries_the_selector_tokens_its_label_was_built_from() -> None:
    """A consumer that selects a column needs the reading, not the prose assembled from it.

    The label drops a dimension that does not apply, so nothing can be recovered from it -
    and a verification plan choosing which column answers for a pair has to select on the
    package's own tokens or it would be reading a second Table 3 of its own.
    """
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.protection_relationships(DecisiveVoltageClass.DVC_C)

    by_target = {item.target: item for item in summary.relationships}
    assert set(by_target) == {"accessible_part", "adjacent_circuit"}
    assert by_target["accessible_part"].pe_relationship == "connected_to_pe"
    assert by_target["adjacent_circuit"].adjacent_dvc == "dvc_b"
    for item in summary.relationships:
        assert item.label == selector_label(
            item.target,
            item.pe_relationship,
            item.access_context,
            item.person_scope,
            item.adjacent_dvc,
        )


def test_an_incoherent_protection_combination_answers_no_match_rather_than_raising() -> None:
    """The behaviour change #53A forced: the matrix is no longer an exhaustive rule.

    The fixture declares two targets over five dimensions, so the adapter asks about far
    more combinations than the two the reviewed columns carry. Every other combination
    answers ``no_match``, and none of them may become a rendered requirement.
    """
    service = DvcGuidanceService(synthetic_dvc_rule_package())

    for dvc in (
        DecisiveVoltageClass.DVC_AS,
        DecisiveVoltageClass.DVC_B,
        DecisiveVoltageClass.DVC_C,
    ):
        summary = service.protection_relationships(dvc)
        assert summary.available is True
        assert len(summary.relationships) == 2


def test_protection_relationships_not_evaluated_has_nothing_to_show() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.protection_relationships(DecisiveVoltageClass.NOT_EVALUATED)
    assert summary.available is False
    assert summary.relationships == ()


def test_protection_relationships_missing_rule_is_not_available() -> None:
    service = DvcGuidanceService(synthetic_rule_package())
    summary = service.protection_relationships(DecisiveVoltageClass.DVC_AS)
    assert summary.available is False
    assert "iec62477_2022.dvc.protection_matrix" in summary.reason


def test_protection_relationships_refuse_a_class_the_rule_does_not_declare() -> None:
    package = _without_designation(synthetic_dvc_rule_package(), DecisiveVoltageClass.DVC_C)
    summary = DvcGuidanceService(package).protection_relationships(DecisiveVoltageClass.DVC_C)

    assert summary.available is False
    assert summary.relationships == ()
    assert "does not carry" in summary.reason
