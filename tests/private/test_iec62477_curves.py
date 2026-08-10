"""Private structural and determinism checks for IEC 62477 Figures 5-7.

All source values remain in the maintainer-supplied PDFs.  These tests compare only
canonical hashes and stable semantic identities; they never snapshot extracted data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    canonical_model_sha256,
    extract_draft,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


def _curve_artifact_hashes(draft) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(canonical_model_sha256(figure) for figure in draft.raw_figures),
        tuple(canonical_model_sha256(result) for result in draft.curve_digitizations),
    )


def test_figures_5_to_7_digitize_deterministically(
    extracted_draft,
    supplied_paths: tuple[Path, ...],
) -> None:
    """The shared import against a second, independent one: that comparison is the point."""

    first = extracted_draft
    second = extract_draft(supplied_paths)

    assert {figure.source.figure for figure in first.raw_figures} == {"5", "6", "7"}
    assert len(first.curve_digitizations) == 3
    assert all(not result.blocking_review_items for result in first.curve_digitizations)
    assert _curve_artifact_hashes(first) == _curve_artifact_hashes(second)


def test_unreviewed_curve_proposal_blocks_initial_approval(extracted_draft) -> None:
    draft = extracted_draft
    proposal = next(
        item
        for item in draft.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    )

    assert proposal.state == "proposed"
    assert any(
        item.code == "CURVE_VARIANT_REVIEW_REQUIRED"
        for item in approval_blockers(draft)
    )
