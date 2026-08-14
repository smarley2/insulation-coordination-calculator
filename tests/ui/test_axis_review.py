"""The axis review surface: proposals in, decisions out. No review logic in Qt.

Every position is reviewed in the raw grid review dialog, beside the row or column it
describes, so the editor's tests drive that dialog. What lives here on its own is the model:
which positions a draft carries, and whether each one's review is still current.
"""

from __future__ import annotations

from typing import get_args

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.axis_selectors import (
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import review_axis_selector
from insulation_coordination.ui import axis_review
from insulation_coordination.ui.axis_review import AxisReviewModel, AxisReviewRow
from insulation_coordination.ui.raw_grid_review import RawGridReviewDialog
from tests.rules.importer.test_axis_resolution import _with_one_corrected_header_cell

# Stated here independently of the UI's own mapping, so these tests prove the editor offers the
# kind the axis declares rather than agreeing with whatever the dialog decided.
_SELECTOR_MODELS = {
    "dvc_designation": DvcDesignationSelector,
    "table2_quantity": Table2QuantitySelector,
    "protection_target": ProtectionTargetSelector,
}


def _expected_options(selector_kind: str) -> dict[str, tuple[str, ...]]:
    return {
        name: get_args(field.annotation)
        for name, field in _SELECTOR_MODELS[selector_kind].model_fields.items()
        if name != "selector_kind"
    }


def _unproposed_position(model: AxisReviewModel) -> AxisReviewRow:
    return next(row for row in model.rows() if row.proposed is None)


def _position(model: AxisReviewModel, axis: str) -> AxisReviewRow:
    return next(row for row in model.rows() if row.axis == axis and row.proposed is not None)


def _grid_dialog(qtbot, draft: ImportedRuleDraft, actor: str = "maintainer") -> RawGridReviewDialog:
    """The dialog the selector is now edited in, beside the grid it belongs to."""

    dialog = RawGridReviewDialog(draft, actor=actor)
    qtbot.addWidget(dialog)
    return dialog


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


def test_confirm_starts_disabled_when_no_position_has_been_selected(
    qtbot, draft_with_axis_proposals
) -> None:
    """Nothing is selected when the dialog opens, so nothing else would ever disable this."""

    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)

    assert dialog._axis_editor.dimension_options == {}
    assert dialog._confirm_axis_button.isEnabled() is False


def test_a_grid_with_no_axis_positions_offers_no_selector_editor(
    qtbot, draft_with_axis_proposals
) -> None:
    """A grid whose rows and columns carry no declared selector must offer nothing to confirm."""

    empty = draft_with_axis_proposals.model_copy(update={"axis_selector_proposals": ()})
    dialog = _grid_dialog(qtbot, empty)

    dialog.show_axis_position("row", 3)

    assert dialog._axis_editor.dimension_options == {}
    assert dialog._confirm_axis_button.isEnabled() is False
    assert "no axis selector position" in dialog._axis_position_label.text()


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


def test_selecting_a_row_header_shows_that_row_positions_selector_editor(
    qtbot, draft_with_axis_proposals
) -> None:
    """A row's selector is edited against the row itself, at the position it describes."""

    row = _position(AxisReviewModel(draft_with_axis_proposals), "row")
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)

    dialog._table.verticalHeader().sectionClicked.emit(row.index)

    assert dialog._axis_editor.dimension_options == _expected_options(row.selector_kind)
    assert dialog._axis_position == ("row", row.index)


def test_selecting_a_column_header_shows_that_columns_selector_editor(
    qtbot, draft_with_axis_proposals
) -> None:
    """The column axis of the same grid declares its own kind, and gets its own editor."""

    column = _position(AxisReviewModel(draft_with_axis_proposals), "column")
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)

    dialog._table.horizontalHeader().sectionClicked.emit(column.index)

    assert dialog._axis_editor.dimension_options == _expected_options(column.selector_kind)
    assert dialog._axis_position == ("column", column.index)


def test_each_position_shows_its_status_against_its_own_row_or_column(
    qtbot, draft_with_axis_proposals
) -> None:
    """The reviewer sees what is still pending without leaving the table."""

    model = AxisReviewModel(draft_with_axis_proposals)
    row = _position(model, "row")
    column = _position(model, "column")
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)

    assert dialog._table.verticalHeaderItem(row.index).text().endswith("needs_review")
    assert dialog._table.horizontalHeaderItem(column.index).text().endswith("needs_review")
    # A row the grid carries but the axis does not declare stays unannotated rather than
    # reading as a position that needs a decision.
    unlabelled = next(
        index
        for index in range(dialog._table.rowCount())
        if index not in {item.index for item in model.rows() if item.axis == "row"}
    )
    assert "needs_review" not in dialog._table.verticalHeaderItem(unlabelled).text()


def test_confirming_the_selected_position_records_a_review(
    qtbot, draft_with_axis_proposals
) -> None:
    """Without this no draft with axis selectors can be approved."""

    row = _position(AxisReviewModel(draft_with_axis_proposals), "row")
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals, actor="Maintainer")
    changed: list[ImportedRuleDraft] = []
    dialog.draft_changed.connect(changed.append)
    dialog.show_axis_position("row", row.index)

    qtbot.mouseClick(dialog._confirm_axis_button, Qt.MouseButton.LeftButton)

    assert dialog.axis_status_text == "Selector confirmed for this position."
    assert dialog._table.verticalHeaderItem(row.index).text().endswith("reviewed")
    assert len(dialog.reviewed_draft.axis_selector_reviews) == 1
    assert dialog.reviewed_draft.axis_selector_reviews[0].actor == "Maintainer"
    assert changed == [dialog.reviewed_draft]


def test_a_position_with_no_proposal_can_be_supplied_beside_its_row(
    qtbot, draft_with_unmatched_row
) -> None:
    """Table 3's whole column axis is reviewer-supplied, so this is the only way to approve it.

    The supplied reading is deliberately distinct from every other position's on this grid, or
    the duplicate-selector refusal would fire instead of the supplied-reading path.
    """

    position = _unproposed_position(AxisReviewModel(draft_with_unmatched_row))
    dialog = _grid_dialog(qtbot, draft_with_unmatched_row)
    dialog.show_axis_position(position.axis, position.index)

    assert dialog._axis_editor.dimension_options == _expected_options("dvc_designation")
    dialog._axis_editor.dimension_combo("designation").setCurrentText("dvc_c")
    dialog._axis_editor.dimension_combo("environment").setCurrentText("not_applicable")
    qtbot.mouseClick(dialog._confirm_axis_button, Qt.MouseButton.LeftButton)

    assert dialog._table.verticalHeaderItem(position.index).text().endswith("reviewed")
    assert dialog.reviewed_draft.axis_selector_reviews[
        0
    ].confirmed_selector == DvcDesignationSelector(
        designation="dvc_c", environment="not_applicable"
    )


def test_confirming_stays_disabled_while_any_dimension_is_unchosen(
    qtbot, draft_with_unmatched_row
) -> None:
    """A position nothing was proposed for starts unchosen rather than on a first option."""

    position = _unproposed_position(AxisReviewModel(draft_with_unmatched_row))
    dialog = _grid_dialog(qtbot, draft_with_unmatched_row)
    dialog.show_axis_position(position.axis, position.index)

    assert dialog._confirm_axis_button.isEnabled() is False
    dialog._axis_editor.dimension_combo("designation").setCurrentText("dvc_c")
    assert dialog._confirm_axis_button.isEnabled() is False
    dialog._axis_editor.dimension_combo("environment").setCurrentText("not_applicable")
    assert dialog._confirm_axis_button.isEnabled() is True


def test_each_combo_offers_exactly_its_fields_vocabulary(qtbot, draft_with_axis_proposals) -> None:
    """The editor is built from the selector models, so a wrong-kind editor cannot be offered."""

    model = AxisReviewModel(draft_with_axis_proposals)
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)

    offered = []
    for row in model.rows():
        dialog.show_axis_position(row.axis, row.index)
        offered.append((row.selector_kind, dialog._axis_editor.dimension_options))

    assert {kind for kind, _options in offered} == {"dvc_designation", "table2_quantity"}
    assert all(options == _expected_options(kind) for kind, options in offered)


def test_a_duplicate_selector_is_surfaced_rather_than_raised(
    qtbot, draft_with_axis_proposals
) -> None:
    """Two positions of one axis confirming the same selector is refused at review time."""

    model = AxisReviewModel(draft_with_axis_proposals)
    first, second = [row for row in model.rows() if row.axis == "row" and row.proposed is not None][
        :2
    ]
    dialog = _grid_dialog(qtbot, draft_with_axis_proposals)
    dialog.show_axis_position("row", first.index)
    qtbot.mouseClick(dialog._confirm_axis_button, Qt.MouseButton.LeftButton)
    confirmed = dialog.reviewed_draft.axis_selector_reviews[0].confirmed_selector
    assert isinstance(confirmed, DvcDesignationSelector)

    dialog.show_axis_position("row", second.index)
    dialog._axis_editor.dimension_combo("designation").setCurrentText(confirmed.designation)
    dialog._axis_editor.dimension_combo("environment").setCurrentText(confirmed.environment)
    qtbot.mouseClick(dialog._confirm_axis_button, Qt.MouseButton.LeftButton)

    assert "refused" in dialog.axis_status_text
    assert dialog._table.verticalHeaderItem(second.index).text().endswith("needs_review")
    assert len(dialog.reviewed_draft.axis_selector_reviews) == 1


def test_table_review_stays_reachable_while_a_position_is_unreviewed(
    qtbot, draft_with_axis_proposals
) -> None:
    """Axis review is its own approval gate, and table review is the only door to it.

    A selector is confirmed inside the grid dialog, beside the row or column it describes. This
    draft's tables carry nothing pending, so enabling that button on table state alone would
    leave approval blocked on positions the reviewer has no way to reach.
    """
    from insulation_coordination.ui.rules_manager import RulesManagerWindow

    window = RulesManagerWindow()
    qtbot.addWidget(window)

    window.set_draft(draft_with_axis_proposals)

    assert window.review_tables_enabled is True
    # Axis positions are not curve content: this draft carries no curves at all.
    assert window.curve_review_enabled is False

    reviewed = draft_with_axis_proposals
    for proposal in draft_with_axis_proposals.axis_selector_proposals:
        assert proposal.selector is not None
        reviewed = review_axis_selector(
            reviewed,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="tester",
            notes="confirmed",
        )
    window.set_draft(reviewed)

    assert window.review_tables_enabled is False
