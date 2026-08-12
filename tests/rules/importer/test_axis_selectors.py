"""Axis selector models: identity, totality, and hash stability."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelectorProposal,
    AxisSelectorReview,
    ConfirmedAxes,
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
    selector_sha256,
)
from insulation_coordination.rules.importer.identify import AxisKeywordRule, AxisSelectorSpec


def test_every_dimension_is_total_so_no_input_is_ever_omitted() -> None:
    """A structurally irrelevant dimension is not_applicable, never absent.

    evaluate_decision requires every declared input, so an optional field here would
    become an unanswerable runtime contract.
    """
    quantity = Table2QuantitySelector(
        operating_context="normal",
        quantity="impulse_withstand",
        basis="not_applicable",
    )
    target = ProtectionTargetSelector(
        target="adjacent_circuit",
        pe_relationship="not_applicable",
        access_context="not_applicable",
        person_scope="not_applicable",
        adjacent_dvc="dvc_b",
    )

    assert quantity.selector_kind == "table2_quantity"
    assert target.selector_kind == "protection_target"


def test_the_curve_basis_vocabulary_is_not_reused() -> None:
    """dc_mean is a Table 2 quantity; the curve's dc is a Figure 5 basis. #50 pinned that."""

    with pytest.raises(ValidationError):
        Table2QuantitySelector(
            operating_context="normal",
            quantity="working_voltage",
            basis="ac_unspecified",
        )


def test_no_column_needs_an_operating_context_of_not_applicable() -> None:
    """Every column of that table falls under one of two operating conditions.

    Confirmed against the licensed source. A not_applicable operating context would assert a
    third condition the source does not state.
    """

    with pytest.raises(ValidationError):
        Table2QuantitySelector(
            operating_context="not_applicable",
            quantity="impulse_withstand",
            basis="not_applicable",
        )


def test_a_keyword_rule_of_another_kind_than_its_axis_is_refused() -> None:
    """An axis and its grammar must agree, or the position it proposes for is unconfirmable.

    Extraction would propose a selector of a kind the axis does not declare, and the
    review-time kind check would then refuse the reviewer's attempt to confirm the very
    reading extraction proposed. Every recipe is consistent today; nothing kept it that way.
    """

    with pytest.raises(ValidationError):
        AxisSelectorSpec(
            axis="row",
            expected_positions=1,
            selector_kind="dvc_designation",
            keyword_rules=(
                AxisKeywordRule(
                    keywords=("rms",),
                    selector=Table2QuantitySelector(
                        operating_context="normal", quantity="working_voltage", basis="ac_rms"
                    ),
                ),
            ),
        )


def test_the_union_round_trips_by_its_discriminator() -> None:
    designation = DvcDesignationSelector(designation="dvc_as", environment="dry")
    proposal = AxisSelectorProposal(
        grid_id="raw-iec62477_2022.dvc.voltage_limits",
        axis="row",
        index=3,
        selector=designation,
        selector_kind="dvc_designation",
        proposal_sha256="a" * 64,
        evidence_sha256="b" * 64,
    )

    restored = AxisSelectorProposal.model_validate(proposal.model_dump(mode="json"))

    assert restored.selector == designation
    assert restored == proposal


def test_an_unmatched_position_is_representable() -> None:
    """Table 3's columns have no grammar, so a proposal must be able to carry no selector."""

    proposal = AxisSelectorProposal(
        grid_id="raw-iec62477_2022.dvc.protection_matrix",
        axis="column",
        index=1,
        selector=None,
        selector_kind="protection_target",
        proposal_sha256="c" * 64,
        evidence_sha256="d" * 64,
    )

    assert proposal.selector is None


def test_selector_hash_is_stable_and_distinguishes_dimensions() -> None:
    first = DvcDesignationSelector(designation="dvc_as", environment="dry")
    same = DvcDesignationSelector(designation="dvc_as", environment="dry")
    other = DvcDesignationSelector(designation="dvc_as", environment="wet_and_saltwater_wet")

    assert selector_sha256(first) == selector_sha256(same)
    assert selector_sha256(first) != selector_sha256(other)


def test_confirmed_axes_reads_back_by_axis_and_index() -> None:
    axes = ConfirmedAxes(
        rows={3: DvcDesignationSelector(designation="dvc_b", environment="not_applicable")},
        columns={
            1: Table2QuantitySelector(
                operating_context="normal",
                quantity="working_voltage",
                basis="ac_rms",
            )
        },
    )

    assert axes.row(3).designation == "dvc_b"
    assert axes.column(1).basis == "ac_rms"
    with pytest.raises(KeyError):
        axes.row(4)


def test_the_draft_digest_covers_axis_reviews() -> None:
    """A review recorded without a digest change would be invisible to correction auditing."""

    from insulation_coordination.rules.importer.extract import canonical_model_sha256
    from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft

    synthetic_draft = _draft()
    review = AxisSelectorReview(
        grid_id="raw-iec62477_2022.dvc.voltage_limits",
        axis="row",
        index=3,
        proposal_sha256="a" * 64,
        evidence_sha256="b" * 64,
        confirmed_selector=DvcDesignationSelector(
            designation="dvc_b", environment="not_applicable"
        ),
        actor="tester",
        recorded_at=datetime(2026, 8, 11, tzinfo=UTC),
        notes="synthetic",
    )
    changed = synthetic_draft.model_copy(update={"axis_selector_reviews": (review,)})

    assert canonical_model_sha256(changed) != canonical_model_sha256(synthetic_draft)


def _axis_review() -> AxisSelectorReview:
    return AxisSelectorReview(
        grid_id="raw-iec62477_2022.dvc.voltage_limits",
        axis="row",
        index=3,
        proposal_sha256="a" * 64,
        evidence_sha256="b" * 64,
        confirmed_selector=DvcDesignationSelector(
            designation="dvc_b", environment="not_applicable"
        ),
        actor="tester",
        recorded_at=datetime(2026, 8, 11, tzinfo=UTC),
        notes="synthetic",
    )


def _correction_ready_draft():
    """A minimal `_draft()` plus the single extraction audit `record_correction` requires."""
    from insulation_coordination.domain.rules import ApprovalRecord
    from insulation_coordination.rules.importer.extract import IMPORTER_VERSION, _content_digest
    from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft

    draft = _draft()
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        raw_grids=draft.raw_grids,
        raw_clause_fragments=draft.raw_clause_fragments,
        source_documents=draft.manifest.source_documents,
        source_identities=draft.source_identities,
    )
    record = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 11, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (record,)})}
    )


def test_a_recorded_axis_review_is_detected_as_changed_by_the_correction_path() -> None:
    """Without axis fields in the change-detection tuple, this correction would be a no-op."""
    from insulation_coordination.rules.importer.approval import record_correction

    original = _correction_ready_draft()
    changed = original.model_copy(update={"axis_selector_reviews": (_axis_review(),)})

    corrected = record_correction(
        original,
        changed,
        actor="Synthetic Reviewer",
        notes="Recorded one axis selector review.",
    )

    assert corrected.axis_selector_reviews == changed.axis_selector_reviews


def test_the_rebuilt_content_digest_differs_when_only_an_axis_review_changes() -> None:
    """The audit trail's before/after digest must move, or the review is invisible to it."""
    import re

    from insulation_coordination.rules.importer.approval import record_correction

    original = _correction_ready_draft()
    changed = original.model_copy(update={"axis_selector_reviews": (_axis_review(),)})

    corrected = record_correction(
        original,
        changed,
        actor="Synthetic Reviewer",
        notes="Recorded one axis selector review.",
    )

    record = corrected.manifest.approval_records[-1]
    match = re.match(r"content:([0-9a-f]{64})->([0-9a-f]{64});", record.notes)
    assert match is not None
    before, after = match.groups()
    assert before != after
