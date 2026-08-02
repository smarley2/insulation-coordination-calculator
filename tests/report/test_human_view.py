from decimal import Decimal
from uuid import UUID

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
