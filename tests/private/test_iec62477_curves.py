"""Private structural checks for source-only IEC 62477 curve import."""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    canonical_model_sha256,
    extract_draft,
)

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


def _figure_hashes(draft) -> tuple[str, ...]:
    return tuple(canonical_model_sha256(figure) for figure in draft.raw_figures)


def test_figures_5_to_7_extract_deterministically(
    extracted_draft,
    supplied_paths: tuple[Path, ...],
) -> None:
    first = extracted_draft
    second = extract_draft(supplied_paths)

    assert {figure.source.figure for figure in first.raw_figures} == {"5", "6", "7"}
    assert first.curves == ()
    assert first.semantic_proposals == ()
    assert _figure_hashes(first) == _figure_hashes(second)


def test_import_creates_one_manual_review_item_per_declared_slot(extracted_draft) -> None:
    curve_items = tuple(
        item for item in extracted_draft.review_items if item.kind == "curve"
    )

    assert len(curve_items) == 8
    assert all(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in curve_items)
    assert len({item.semantic_id for item in curve_items}) == len(curve_items)
    assert all(item.source.geometry is not None for item in curve_items)


def test_unreviewed_manual_curve_slots_block_initial_approval(extracted_draft) -> None:
    blockers = approval_blockers(extracted_draft)
    curve_blockers = tuple(item for item in blockers if item.kind == "curve")

    assert len(curve_blockers) == 8
    assert all(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in curve_blockers)
