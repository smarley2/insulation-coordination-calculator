"""DvcGuidanceService: reads DVC facts from a package, never a constant.

Covers the row/column token mapping's structural guarantees plus the service's
availability and degradation behaviour. No IEC value appears here - the fixture
package's numbers are all invented.
"""

from __future__ import annotations

from decimal import Decimal

from insulation_coordination.domain.dvc import (
    PROTECTION_MATRIX_ROW_TOKENS,
    VOLTAGE_LIMITS_ROW_TOKENS,
    VOLTAGE_QUANTITY_COLUMN_TOKENS,
    DvcGuidanceService,
)
from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import (
    TABLE_2,
    TABLE_3,
)
from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package, synthetic_rule_package


def _label(column: int) -> str:
    """Our own label for Table 2's Nth data column, read from the one place it is set.

    Asserting the label text here would pin wording that deliberately belongs to a single
    constant - the source's own headings may not be committed, so ours are free to change.
    """
    return dict(VOLTAGE_QUANTITY_COLUMN_TOKENS)[f"voltage-quantity-{column}"]


# --- structural guard: the row/column token mapping never silently drifts ----------


def test_voltage_limits_rows_are_distinct_and_cover_every_dvc_but_not_evaluated() -> None:
    assert set(VOLTAGE_LIMITS_ROW_TOKENS) == set(DecisiveVoltageClass) - {
        DecisiveVoltageClass.NOT_EVALUATED
    }
    assert len(set(VOLTAGE_LIMITS_ROW_TOKENS.values())) == len(VOLTAGE_LIMITS_ROW_TOKENS)


def test_voltage_limits_rows_stay_within_the_recipe_declared_row_count() -> None:
    for token in VOLTAGE_LIMITS_ROW_TOKENS.values():
        index = int(token.removeprefix("dvc-"))
        assert 1 <= index <= TABLE_2.expected_data_rows


def test_voltage_quantity_columns_are_distinct_and_within_the_recipe_declared_count() -> None:
    tokens = [token for token, _label in VOLTAGE_QUANTITY_COLUMN_TOKENS]
    assert len(set(tokens)) == len(tokens)
    for token in tokens:
        index = int(token.removeprefix("voltage-quantity-"))
        assert 1 <= index <= TABLE_2.expected_data_columns


def test_protection_matrix_rows_are_distinct_and_cover_every_dvc_but_not_evaluated() -> None:
    assert set(PROTECTION_MATRIX_ROW_TOKENS) == set(DecisiveVoltageClass) - {
        DecisiveVoltageClass.NOT_EVALUATED
    }
    assert len(set(PROTECTION_MATRIX_ROW_TOKENS.values())) == len(PROTECTION_MATRIX_ROW_TOKENS)


def test_protection_matrix_rows_stay_within_the_recipe_declared_row_count() -> None:
    for token in PROTECTION_MATRIX_ROW_TOKENS.values():
        index = int(token.removeprefix("dvc-"))
        assert 1 <= index <= TABLE_3.expected_data_rows


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


def test_dvc_as_limits_render_numeric_values_with_their_source() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_AS)
    assert summary.available is True
    rms = next(q for q in summary.quantities if q.label == _label(1))
    assert rms.status == "value"
    assert rms.value == Decimal(11)
    assert rms.unit == "V"
    assert rms.source is not None
    assert rms.source.standard == "IEC 62477-1"


def test_dvc_b_impulse_withstand_renders_as_a_reference_not_a_number() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    impulse = next(q for q in summary.quantities if q.label == _label(4))
    assert impulse.status == "reference"
    assert impulse.value is None
    assert impulse.reference_rule_id == "iec62477_2022.supply.impulse_by_system_voltage_ovc"


def test_dvc_b_fault_condition_column_renders_as_a_curve_reference() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_B)
    fault = next(q for q in summary.quantities if q.label == _label(5))
    assert fault.status == "reference"
    assert fault.reference_rule_id == "iec62477_2022.dvc.fault_time_voltage"


def test_dvc_c_not_applicable_cell_says_so_without_a_number() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_C)
    fault = next(q for q in summary.quantities if q.label == _label(5))
    assert fault.status == "not_applicable"
    assert fault.value is None


def test_dvc_c_uncovered_cell_is_unavailable_rather_than_guessed() -> None:
    """The fixture only covers one column for DVC C; the rest must not be invented."""
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.limits(DecisiveVoltageClass.DVC_C)
    mean = next(q for q in summary.quantities if q.label == _label(3))
    assert mean.status == "unavailable"
    assert mean.value is None


# --- DvcGuidanceService.protection_relationships ------------------------------------


def test_protection_relationships_render_with_their_source() -> None:
    service = DvcGuidanceService(synthetic_dvc_rule_package())
    summary = service.protection_relationships(DecisiveVoltageClass.DVC_B)
    assert summary.available is True
    contexts = {item.protection_context: item.requirement for item in summary.relationships}
    assert contexts == {
        "protection-context-1": "basic_protection",
        "protection-context-2": "none",
    }
    assert all(item.source is not None for item in summary.relationships)


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
