"""Resolution refuses anything that is not an exact, current, unique review."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.approval import approval_blockers, record_correction
from insulation_coordination.rules.importer.axis_selectors import (
    DvcDesignationSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridSegment,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from insulation_coordination.rules.importer.review import (
    AxisResolutionError,
    resolve_confirmed_axis_selectors,
    review_axis_selector,
)
from tests.rules.importer.iec62477_2022.test_axis_proposals import _SOURCE

# voltage_limits_grid, draft_with_axis_proposals and draft_with_unmatched_row are shared
# fixtures; see tests/conftest.py.


@pytest.fixture
def fully_reviewed_draft(draft_with_axis_proposals):
    draft = draft_with_axis_proposals
    for proposal in draft.axis_selector_proposals:
        assert proposal.selector is not None, "this fixture proposes a reading for every position"
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector,
            actor="tester",
            notes="confirmed",
        )
    return draft


def _grid_for(spec) -> RawGrid:
    """A minimal grid for a spec that declares no axis selectors.

    The resolver must return early for such a spec, without reading this grid's cells, so
    the grid carries none.
    """

    return RawGrid(
        id=f"raw-{spec.semantic_id}",
        rows=1,
        columns=1,
        target_unit=spec.target_unit,
        segments=(RawGridSegment(page_number=1, row_start=0, row_count=1, source=_SOURCE),),
        cells=(),
        source=_SOURCE,
    )


def test_a_fully_reviewed_grid_resolves(fully_reviewed_draft, voltage_limits_grid) -> None:
    axes = resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, fully_reviewed_draft)

    assert len(axes.rows) == 4
    assert len(axes.columns) == 5


def test_a_missing_review_refuses(draft_with_axis_proposals, voltage_limits_grid) -> None:
    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft_with_axis_proposals)


def test_a_stale_proposal_hash_refuses(fully_reviewed_draft, voltage_limits_grid) -> None:
    stale = tuple(
        review.model_copy(update={"proposal_sha256": "0" * 64})
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": stale})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_a_stale_evidence_hash_refuses(fully_reviewed_draft, voltage_limits_grid) -> None:
    stale = tuple(
        review.model_copy(update={"evidence_sha256": "0" * 64})
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": stale})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_two_positions_confirmed_alike_are_refused(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    """Two row positions confirmed as the same selector must be refused, not silently served.

    ``evaluate_decision`` returns the first matcher that fits, so two positions resolving to
    equal selectors would collide into one matcher set with no error anywhere.
    """
    row_reviews = [
        review for review in fully_reviewed_draft.axis_selector_reviews if review.axis == "row"
    ]
    duplicate_selector = row_reviews[0].confirmed_selector
    collided = tuple(
        review.model_copy(update={"confirmed_selector": duplicate_selector})
        if review is row_reviews[1]
        else review
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": collided})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_a_wrong_kind_confirmed_selector_refuses_at_resolution(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    """A column selector confirmed on a row position must be refused at resolution.

    Left unchecked, this would surface much later as an ``AttributeError`` from a
    projector's ``cast``, on whichever selector attribute the row's real kind lacks.
    """
    row_review = next(
        review for review in fully_reviewed_draft.axis_selector_reviews if review.axis == "row"
    )
    wrong_kind = Table2QuantitySelector(
        operating_context="normal", quantity="working_voltage", basis="ac_rms"
    )
    mismatched = tuple(
        review.model_copy(update={"confirmed_selector": wrong_kind})
        if review is row_review
        else review
        for review in fully_reviewed_draft.axis_selector_reviews
    )
    draft = fully_reviewed_draft.model_copy(update={"axis_selector_reviews": mismatched})

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_duplicate_reviews_for_one_position_refuse(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    first = fully_reviewed_draft.axis_selector_reviews[0]
    draft = fully_reviewed_draft.model_copy(
        update={"axis_selector_reviews": (*fully_reviewed_draft.axis_selector_reviews, first)}
    )

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)


def test_an_unmatched_position_resolves_once_a_review_supplies_it(
    draft_with_unmatched_row, voltage_limits_grid
) -> None:
    """The reviewer may supply a selector outright. Refusing this would forbid a designed path.

    The supplied reading must stay distinct from every other row's own selector -- rows 4-6
    already confirm ``dvc_as`` (dry and wet) and ``dvc_b`` -- or this would collide with the
    duplicate-selector refusal instead of exercising the supplied-reading path.
    """

    draft = draft_with_unmatched_row
    for proposal in draft.axis_selector_proposals:
        draft = review_axis_selector(
            draft,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector
            or DvcDesignationSelector(designation="dvc_c", environment="not_applicable"),
            actor="tester",
            notes="supplied",
        )

    axes = resolve_confirmed_axis_selectors(TABLE_2, voltage_limits_grid, draft)

    assert len(axes.rows) == 4


def _with_one_corrected_value(draft, grid_id: str):
    """Correct one extracted value in a grid, the way reviewing an ambiguous cell does."""

    grid = next(item for item in draft.raw_grids if item.id == grid_id)
    target = next(cell for cell in grid.cells if cell.value is not None)
    corrected = grid.model_copy(
        update={
            "cells": tuple(
                cell.model_copy(update={"value": cell.value + 1}) if cell is target else cell
                for cell in grid.cells
            )
        }
    )
    return record_correction(
        draft,
        draft.model_copy(
            update={
                "raw_grids": tuple(
                    corrected if item.id == grid_id else item for item in draft.raw_grids
                )
            }
        ),
        actor="tester",
        notes="correct one extracted value",
    )


def test_a_grid_corrected_before_axis_review_still_resolves(
    draft_with_axis_proposals, voltage_limits_grid
) -> None:
    """A correction to a cell outside a position's own evidence must not strand that position.

    A review binds to the digest of exactly the header cells a position's selector is read
    from, not to the whole grid, so a correction to a data cell no axis selector was ever
    read from leaves every position's review current. This is the licensed review order,
    which corrects the ambiguous compound cells of both DVC grids before reviewing their axes.
    """
    draft = _with_one_corrected_value(draft_with_axis_proposals, voltage_limits_grid.id)
    corrected_grid = next(item for item in draft.raw_grids if item.id == voltage_limits_grid.id)
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

    axes = resolve_confirmed_axis_selectors(TABLE_2, corrected_grid, draft)

    assert len(axes.rows) == 4
    assert len(axes.columns) == 5


def _with_one_corrected_header_cell(draft, grid_id: str):
    """Change row position 3's own evidence cell (row 3, column 0).

    Goes through the sanctioned ``record_correction`` API, which accepts this: it freezes a
    cell's raw text, role, source and coordinates but permits its qualifier on any cell,
    header included. What keeps a header out of a reviewer's reach is
    ``correctable_coordinates``, one module over, which filters to ``cell.role == "data"``.
    So this is a correction the audit chain records, not a fabricated draft.
    """

    grid = next(item for item in draft.raw_grids if item.id == grid_id)
    target = next(cell for cell in grid.cells if (cell.row, cell.column) == (3, 0))
    corrected = grid.model_copy(
        update={
            "cells": tuple(
                cell.model_copy(update={"qualifier": "<="}) if cell is target else cell
                for cell in grid.cells
            )
        }
    )
    return record_correction(
        draft,
        draft.model_copy(
            update={
                "raw_grids": tuple(
                    corrected if item.id == grid_id else item for item in draft.raw_grids
                )
            }
        ),
        actor="tester",
        notes="correct one axis position's own evidence cell",
    )


def test_a_grid_correction_reopens_an_already_reviewed_axis(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    """Re-reading a grid whose own evidence changed must not carry the old review over."""

    draft = _with_one_corrected_header_cell(fully_reviewed_draft, voltage_limits_grid.id)
    corrected_grid = next(item for item in draft.raw_grids if item.id == voltage_limits_grid.id)

    with pytest.raises(AxisResolutionError):
        resolve_confirmed_axis_selectors(TABLE_2, corrected_grid, draft)


def test_a_re_review_after_its_own_evidence_changed_clears_the_position(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    """Re-opening a position is only half of it: the re-review must also be able to close it.

    The review has to carry the evidence digest recomputed from the live grid. Written from
    the proposal's stored digest -- which nothing re-derives after a correction -- every
    review this position could ever receive would be stale on arrival, and neither the
    resolver nor ``AXIS_SELECTOR_REVIEW_REQUIRED`` could ever be satisfied again.
    """

    draft = _with_one_corrected_header_cell(fully_reviewed_draft, voltage_limits_grid.id)
    corrected_grid = next(item for item in draft.raw_grids if item.id == voltage_limits_grid.id)
    reopened = next(
        item for item in draft.axis_selector_proposals if item.axis == "row" and item.index == 3
    )
    assert reopened.selector is not None

    draft = review_axis_selector(
        draft,
        grid_id=reopened.grid_id,
        axis=reopened.axis,
        index=reopened.index,
        selector=reopened.selector,
        actor="tester",
        notes="re-confirmed after the correction",
    )

    axes = resolve_confirmed_axis_selectors(TABLE_2, corrected_grid, draft)

    assert len(axes.rows) == 4
    assert len(axes.columns) == 5
    assert "AXIS_SELECTOR_REVIEW_REQUIRED" not in {
        blocker.code for blocker in approval_blockers(draft)
    }


def test_a_stale_review_no_longer_reserves_its_selector(
    fully_reviewed_draft, voltage_limits_grid
) -> None:
    """A review the live evidence has invalidated must not hold another position's reading.

    Distinctness only means anything between the reviews resolution would actually use. A
    stale one left in that comparison reserves its selector for good, so the position that
    legitimately reads it could never be confirmed.
    """

    draft = _with_one_corrected_header_cell(fully_reviewed_draft, voltage_limits_grid.id)
    stale = next(
        item for item in draft.axis_selector_reviews if item.axis == "row" and item.index == 3
    )
    other = next(
        item for item in draft.axis_selector_proposals if item.axis == "row" and item.index != 3
    )

    draft = review_axis_selector(
        draft,
        grid_id=other.grid_id,
        axis=other.axis,
        index=other.index,
        selector=stale.confirmed_selector,
        actor="tester",
        notes="reads what the stale review reserved",
    )

    confirmed = next(
        item
        for item in draft.axis_selector_reviews
        if item.axis == "row" and item.index == other.index
    )
    assert confirmed.confirmed_selector == stale.confirmed_selector


def test_a_spec_without_axis_selectors_resolves_empty(draft_with_axis_proposals) -> None:
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLES

    spec = next(item for item in TABLES if not item.axis_selectors)
    grid = _grid_for(spec)

    axes = resolve_confirmed_axis_selectors(spec, grid, draft_with_axis_proposals)

    assert axes.rows == {}
    assert axes.columns == {}
