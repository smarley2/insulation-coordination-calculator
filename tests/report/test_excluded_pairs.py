from uuid import UUID

import pytest

from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    PairVoltage,
    PairVoltages,
)
from insulation_coordination.report.human_view import build_human_report_view
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, build_report_model

_REASON = "Net classes cannot come near each other in this assembly."


def _excluded_pair(net_a: UUID, net_b: UUID) -> PairCase:
    not_applicable = PairVoltage.not_applicable(_REASON)
    return PairCase(
        key=f"{net_a}::{net_b}",
        net_a=net_a,
        net_b=net_b,
        voltages=PairVoltages(
            long_term_rms_v=not_applicable,
            steady_state_peak_v=not_applicable,
            recurring_peak_v=not_applicable,
            temporary_overvoltage_peak_v=not_applicable,
        ),
        notes="Far apart by construction.",
    )


@pytest.fixture
def inputs_with_excluded_pair(report_inputs):
    """The synthetic project plus a third net class whose two pairs are excluded."""
    project, results, groups, rules = report_inputs
    far = UUID(int=99)
    high, low = project.net_classes[0].id, project.net_classes[1].id
    project = project.model_copy(
        update={
            "net_classes": (
                *project.net_classes,
                NetClass(id=far, name="FAR", description="Physically remote net"),
            ),
            "pairs": (
                *project.pairs,
                _excluded_pair(high, far),
                _excluded_pair(low, far),
            ),
        }
    )
    return project, results, groups, rules


def test_excluded_pairs_are_reported_without_a_calculation(inputs_with_excluded_pair) -> None:
    model = build_report_model(*inputs_with_excluded_pair)

    assert len(model.matrix_rows) == 1
    assert {(pair.net_a, pair.net_b) for pair in model.excluded_pairs} == {
        ("HV_1", "FAR"),
        ("LV%2", "FAR"),
    }
    assert all(pair.notes == "Far apart by construction." for pair in model.excluded_pairs)
    # Excluded pairs must not leak into the grouped calculations.
    grouped = {pair_id for group in model.groups for pair_id in group.pair_ids}
    assert grouped == {row.pair_id for row in model.matrix_rows}


def test_excluded_pairs_get_their_own_report_section(inputs_with_excluded_pair) -> None:
    tex = render_latex(build_report_model(*inputs_with_excluded_pair))

    assert "Pairs Excluded from the Analysis" in tex
    assert "Far apart by construction." in tex
    # The hardcoded N/A justification has no UI field, so it stays out of the table.
    assert _REASON not in tex


def test_comparison_matrices_mark_excluded_pairs_as_na(inputs_with_excluded_pair) -> None:
    model = build_report_model(*inputs_with_excluded_pair)

    view = build_human_report_view(model)

    matrix = view.comparison_matrices[0]
    far = matrix.headers.index("FAR")
    high = matrix.headers.index("HV_1")
    assert matrix.values[far][high] == "N/A"
    # The diagonal stays an em dash: a net class is not excluded from itself.
    assert matrix.values[far][far] == "—"


def test_report_refuses_a_project_where_every_pair_is_excluded(report_inputs) -> None:
    project, _results, _groups, rules = report_inputs
    pair = project.pairs[0]
    project = project.model_copy(update={"pairs": (_excluded_pair(pair.net_a, pair.net_b),)})

    with pytest.raises(ReportBuildError, match="every pair is excluded"):
        build_report_model(project, (), (), rules)
