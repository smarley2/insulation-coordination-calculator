"""The axis review surface: proposals in, decisions out. No review logic in Qt."""

from __future__ import annotations

from typing import get_args

import pytest

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.axis_selectors import (
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.review import review_axis_selector
from insulation_coordination.ui import axis_review
from insulation_coordination.ui.axis_review import AxisReviewDialog, AxisReviewModel
from tests.rules.importer.test_axis_resolution import _with_one_corrected_header_cell

# Stated here independently of the UI's own mapping, so these tests prove the editor offers the
# kind the axis declares rather than agreeing with whatever the dialog decided.
_SELECTOR_MODELS = {
    "dvc_designation": DvcDesignationSelector,
    "table2_quantity": Table2QuantitySelector,
    "protection_target": ProtectionTargetSelector,
}
_STATUS_COLUMN = 4


def _expected_options(selector_kind: str) -> dict[str, tuple[str, ...]]:
    return {
        name: get_args(field.annotation)
        for name, field in _SELECTOR_MODELS[selector_kind].model_fields.items()
        if name != "selector_kind"
    }


def _unproposed_position(model: AxisReviewModel) -> int:
    return next(position for position, row in enumerate(model.rows()) if row.proposed is None)


class _DriftedSelector(DvcDesignationSelector):
    """A selector kind one of whose dimensions is no longer a total ``Literal`` of strings."""

    designation: str  # type: ignore[assignment]


def test_a_dimension_without_a_string_vocabulary_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent degradation here is unconfirmable positions and an approval blocked with no message.

    ``get_args`` returns nothing for a plain annotation, so the dimension's combo would hold
    only its blank placeholder, Confirm would never enable, and this test's own
    ``_expected_options`` helper mirrors the same call and so could never catch it.
    """

    monkeypatch.setitem(axis_review._SELECTOR_MODELS, "dvc_designation", _DriftedSelector)

    with pytest.raises(RulePackageError, match="designation"):
        axis_review._dimensions("dvc_designation")


def test_confirm_starts_disabled_when_there_is_no_position_to_select(
    qtbot, draft_with_axis_proposals
) -> None:
    """With no rows the dialog never selects one, so nothing else would ever disable this."""

    empty = draft_with_axis_proposals.model_copy(update={"axis_selector_proposals": ()})
    dialog = AxisReviewDialog(AxisReviewModel(empty))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 0
    assert dialog.confirm_button.isEnabled() is False


def test_the_model_lists_every_position_with_its_status(draft_with_axis_proposals) -> None:
    model = AxisReviewModel(draft_with_axis_proposals)

    rows = model.rows()

    assert len(rows) == len(draft_with_axis_proposals.axis_selector_proposals)
    assert all(row.status == "needs_review" for row in rows)


def test_a_reviewer_supplied_position_reports_no_proposal(draft_with_unmatched_row) -> None:
    model = AxisReviewModel(draft_with_unmatched_row)

    unmatched = [row for row in model.rows() if row.proposed is None]

    assert unmatched
    assert all(row.status == "needs_review" for row in unmatched)


def test_confirming_updates_the_status_and_the_draft(draft_with_axis_proposals) -> None:
    model = AxisReviewModel(draft_with_axis_proposals)
    first = model.rows()[0]

    model.confirm(
        first.grid_id,
        first.axis,
        first.index,
        DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
        actor="tester",
        notes="confirmed",
    )

    updated = next(
        row
        for row in model.rows()
        if (row.grid_id, row.axis, row.index) == (first.grid_id, first.axis, first.index)
    )
    assert updated.status == "reviewed"
    assert model.draft.axis_selector_reviews


def test_a_position_whose_own_evidence_changed_reads_as_needing_review(
    draft_with_axis_proposals, voltage_limits_grid
) -> None:
    """This surface must agree with the gate that blocks approval, or it misdirects the reviewer.

    Comparing against the proposal's stored evidence hash instead of the live one showed every
    position as reviewed while approval stayed blocked on the corrected one.
    """

    draft = draft_with_axis_proposals
    for proposal in draft.axis_selector_proposals:
        assert proposal.selector is not None
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="tester",
            notes="confirmed",
        )
    corrected = _with_one_corrected_header_cell(draft, voltage_limits_grid.id)

    rows = {(row.axis, row.index): row.status for row in AxisReviewModel(corrected).rows()}

    assert rows[("row", 3)] == "needs_review"
    assert all(status == "reviewed" for key, status in rows.items() if key != ("row", 3))


def test_the_dialog_shows_one_row_per_position(qtbot, draft_with_axis_proposals) -> None:
    dialog = AxisReviewDialog(AxisReviewModel(draft_with_axis_proposals))
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == len(draft_with_axis_proposals.axis_selector_proposals)
    assert dialog.table.columnCount() == 5


def test_confirming_the_selected_position_records_a_review(
    qtbot, draft_with_axis_proposals
) -> None:
    """Without this the dialog is read-only and no draft with axis selectors can be approved."""

    model = AxisReviewModel(draft_with_axis_proposals)
    dialog = AxisReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(0)

    dialog.confirm_selected()

    assert dialog.table.item(0, _STATUS_COLUMN).text() == "reviewed"
    assert len(model.draft.axis_selector_reviews) == 1
    assert model.draft.axis_selector_reviews[0].actor == "maintainer"


def test_a_position_with_no_proposal_can_be_supplied_through_the_dialog(
    qtbot, draft_with_unmatched_row
) -> None:
    """Table 3's whole column axis is reviewer-supplied, so this is the only way to approve it.

    The supplied reading is deliberately distinct from every other position's on this grid, or
    the duplicate-selector refusal would fire instead of the supplied-reading path.
    """

    model = AxisReviewModel(draft_with_unmatched_row)
    dialog = AxisReviewDialog(model)
    qtbot.addWidget(dialog)
    position = _unproposed_position(model)
    dialog.table.selectRow(position)

    assert dialog.dimension_options == _expected_options("dvc_designation")
    dialog.dimension_combo("designation").setCurrentText("dvc_c")
    dialog.dimension_combo("environment").setCurrentText("not_applicable")
    dialog.confirm_selected()

    assert dialog.table.item(position, _STATUS_COLUMN).text() == "reviewed"
    assert model.draft.axis_selector_reviews[0].confirmed_selector == DvcDesignationSelector(
        designation="dvc_c", environment="not_applicable"
    )


def test_confirming_stays_disabled_while_any_dimension_is_unchosen(
    qtbot, draft_with_unmatched_row
) -> None:
    """A position nothing was proposed for starts unchosen rather than on a first option."""

    model = AxisReviewModel(draft_with_unmatched_row)
    dialog = AxisReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(_unproposed_position(model))

    assert dialog.confirm_button.isEnabled() is False
    dialog.dimension_combo("designation").setCurrentText("dvc_c")
    assert dialog.confirm_button.isEnabled() is False
    dialog.dimension_combo("environment").setCurrentText("not_applicable")
    assert dialog.confirm_button.isEnabled() is True


def test_each_combo_offers_exactly_its_fields_vocabulary(qtbot, draft_with_axis_proposals) -> None:
    """The editor is built from the selector models, so a wrong-kind editor cannot be offered."""

    model = AxisReviewModel(draft_with_axis_proposals)
    dialog = AxisReviewDialog(model)
    qtbot.addWidget(dialog)

    offered = []
    for position, row in enumerate(model.rows()):
        dialog.table.selectRow(position)
        offered.append((row.selector_kind, dialog.dimension_options))

    assert {kind for kind, _options in offered} == {"dvc_designation", "table2_quantity"}
    assert all(options == _expected_options(kind) for kind, options in offered)


def test_a_duplicate_selector_is_surfaced_rather_than_raised(
    qtbot, draft_with_axis_proposals
) -> None:
    """Two positions of one axis confirming the same selector is refused at review time."""

    model = AxisReviewModel(draft_with_axis_proposals)
    dialog = AxisReviewDialog(model)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(0)
    dialog.confirm_selected()
    confirmed = model.rows()[0].confirmed
    assert isinstance(confirmed, DvcDesignationSelector)

    dialog.table.selectRow(1)
    dialog.dimension_combo("designation").setCurrentText(confirmed.designation)
    dialog.dimension_combo("environment").setCurrentText(confirmed.environment)
    dialog.confirm_selected()

    assert "refused" in dialog.status_text
    assert dialog.table.item(1, _STATUS_COLUMN).text() == "needs_review"
    assert len(model.draft.axis_selector_reviews) == 1


def test_the_button_is_enabled_by_axis_state_not_by_curve_content(
    qtbot, draft_with_axis_proposals
) -> None:
    """Axis review is its own approval gate.

    A draft can declare axis selectors without carrying any curve content, and the reviewer must
    still be able to reach the gate that blocks its approval.
    """
    from insulation_coordination.ui.rules_manager import RulesManagerWindow

    # Create a draft with axis proposals but no curves
    draft_without_curves = draft_with_axis_proposals.model_copy(
        update={"curves": (), "curve_digitizations": ()}
    )

    # Verify the fixture setup is correct
    assert draft_without_curves.axis_selector_proposals
    assert not draft_without_curves.curves
    assert not draft_without_curves.curve_digitizations

    # Load the draft and verify the axis button is enabled
    window = RulesManagerWindow()
    qtbot.addWidget(window)
    window.set_draft(draft_without_curves)

    assert window.axis_review_enabled is True
    assert window.curve_review_enabled is False
