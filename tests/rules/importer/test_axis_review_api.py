"""Recording axis reviews, and the gate that requires them."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.approval import ApprovalError, approval_blockers
from insulation_coordination.rules.importer.axis_selectors import (
    DvcDesignationSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.review import (
    AxisResolutionError,
    review_axis_selector,
)

# draft_with_axis_proposals is a shared fixture; see tests/conftest.py.


def test_an_unreviewed_axis_position_blocks_approval(draft_with_axis_proposals) -> None:
    codes = {item.code for item in approval_blockers(draft_with_axis_proposals)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" in codes


def test_confirming_every_position_clears_the_blocker(draft_with_axis_proposals) -> None:
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

    codes = {item.code for item in approval_blockers(draft)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" not in codes


def test_a_review_records_the_reviewers_correction_not_the_proposal(
    draft_with_axis_proposals,
) -> None:
    """The reviewer is the authority; a hash-only record could not express this."""

    proposal = draft_with_axis_proposals.axis_selector_proposals[0]
    corrected = DvcDesignationSelector(designation="dvc_c", environment="not_applicable")

    draft = review_axis_selector(
        draft_with_axis_proposals,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=corrected,
        actor="tester",
        notes="corrected",
    )

    review = next(
        item
        for item in draft.axis_selector_reviews
        if item.axis == proposal.axis and item.index == proposal.index
    )
    assert review.confirmed_selector == corrected
    assert review.proposal_sha256 == proposal.proposal_sha256


def test_a_second_review_of_one_position_replaces_the_first(draft_with_axis_proposals) -> None:
    proposal = draft_with_axis_proposals.axis_selector_proposals[0]
    draft = review_axis_selector(
        draft_with_axis_proposals,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
        actor="tester",
        notes="first",
    )
    draft = review_axis_selector(
        draft,
        grid_id=proposal.grid_id,
        axis=proposal.axis,
        index=proposal.index,
        selector=DvcDesignationSelector(designation="dvc_c", environment="not_applicable"),
        actor="tester",
        notes="second",
    )

    matching = [
        item
        for item in draft.axis_selector_reviews
        if item.axis == proposal.axis and item.index == proposal.index
    ]

    assert len(matching) == 1
    assert matching[0].confirmed_selector.designation == "dvc_c"


def test_actor_and_notes_are_required(draft_with_axis_proposals) -> None:
    proposal = draft_with_axis_proposals.axis_selector_proposals[0]

    with pytest.raises(ApprovalError):
        review_axis_selector(
            draft_with_axis_proposals,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
            actor="  ",
            notes="",
        )


def test_a_selector_of_the_wrong_kind_is_refused_at_review(draft_with_axis_proposals) -> None:
    """A column kind confirmed on a row position must die here, not at resolution.

    Resolution refuses it too, but only once the whole axis is complete; and a draft left
    holding it makes the review dialog read an attribute the position's own kind lacks.
    """

    proposal = next(
        item for item in draft_with_axis_proposals.axis_selector_proposals if item.axis == "row"
    )

    with pytest.raises(AxisResolutionError):
        review_axis_selector(
            draft_with_axis_proposals,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=Table2QuantitySelector(
                operating_context="normal", quantity="working_voltage", basis="ac_rms"
            ),
            actor="tester",
            notes="wrong kind",
        )


def test_reviewing_an_unknown_position_is_refused(draft_with_axis_proposals) -> None:
    with pytest.raises(ValueError):
        review_axis_selector(
            draft_with_axis_proposals,
            grid_id="raw-iec62477_2022.dvc.voltage_limits",
            axis="row",
            index=99,
            selector=DvcDesignationSelector(designation="dvc_b", environment="not_applicable"),
            actor="tester",
            notes="no such position",
        )
