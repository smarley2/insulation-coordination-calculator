from decimal import Decimal
from uuid import UUID

from insulation_coordination.calculation.engine import CalculationWarning, VerificationRequirement
from insulation_coordination.domain.project import NetClass
from insulation_coordination.report.human_view import build_human_report_view
from insulation_coordination.report.model import build_report_model


def test_human_view_separates_common_values_and_differing_matrices(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    report_model = build_report_model(project, results, groups, rules)
    row = report_model.matrix_rows[0]
    changed_row = row.model_copy(
        update={
            "pair_id": "synthetic-second-pair",
            "net_a": "PE",
            "net_b": "LV%2",
            "frequency": row.frequency.model_copy(update={"value": Decimal(60)}),
        }
    )
    changed_model = report_model.model_copy(
        update={
            "net_classes": (*report_model.net_classes, NetClass(id=UUID(int=5), name="PE")),
            "matrix_rows": (row, changed_row),
        }
    )

    view = build_human_report_view(changed_model)

    assert any(item.name == "Frequency" for item in view.common_values) is False
    frequency = next(item for item in view.comparison_matrices if item.name == "Frequency")
    assert frequency.headers == ("HV_1", "LV%2", "PE")
    assert frequency.values[0][0] == "—"
    assert frequency.values[2][1] == "60 Hz"
    assert any(item.name == "Impulse" for item in view.common_values)
    matrix_names = {item.name for item in view.comparison_matrices}
    assert {
        "Long-term RMS voltage",
        "Steady-state peak voltage",
        "Recurring peak voltage",
        "Temporary overvoltage peak voltage",
    } <= matrix_names
    assert "determined the clearance" in view.groups[0].calculations[0].clearance_explanation
    assert "determined the creepage" in view.groups[0].calculations[0].creepage_explanation
    assert view.groups[0].rules
    assert all(rule.description.endswith(".") for rule in view.groups[0].rules)


def test_human_view_deduplicates_warning_and_matching_verification(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    report_model = build_report_model(project, results, groups, rules)
    warning = CalculationWarning(code="CHECK", message="Confirm the design choice.")
    requirement = VerificationRequirement(code="CHECK", message="Confirm the design choice.")
    changed_model = report_model.model_copy(
        update={
            "warnings": (warning, warning),
            "verification_requirements": (requirement, requirement),
        }
    )

    view = build_human_report_view(changed_model)

    assert [item.code for item in view.advisories] == ["CHECK"]
    assert view.verification_requirements == ()
