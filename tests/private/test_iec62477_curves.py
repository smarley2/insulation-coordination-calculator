"""Private structural checks for source-only IEC 62477 curve import."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import CurvePoint
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.evaluator import evaluate_piecewise_curve
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import approval_blockers, approve_draft
from insulation_coordination.rules.importer.curves import ManualPlotCalibration
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    canonical_model_sha256,
    extract_draft,
)
from insulation_coordination.rules.importer.review import (
    replace_manual_curve_variant,
    review_curve_variant,
    set_manual_curve_calibration,
)

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


def _figure_hashes(draft) -> tuple[str, ...]:
    return tuple(canonical_model_sha256(figure) for figure in draft.raw_figures)


def _complete_manual_curve_review(draft):
    """Use local placeholder inputs to prove the manual-review path, not IEC values."""
    for raw_figure in draft.raw_figures:
        draft = set_manual_curve_calibration(
            draft,
            figure=raw_figure.source.figure,
            calibration=ManualPlotCalibration(
                figure_artifact_sha256=raw_figure.artifact_sha256,
                x_min=Decimal(1),
                x_max=Decimal(10),
                y_min=Decimal(1),
                y_max=Decimal(10),
            ),
            actor="Private fixture reviewer",
            notes="Reviewed local plot calibration.",
        )
    curve_items = tuple(item for item in draft.review_items if item.kind == "curve")
    points = (
        CurvePoint(x=Decimal(1), y=Decimal(10)),
        CurvePoint(x=Decimal(10), y=Decimal(1)),
    )
    for item in curve_items:
        draft = replace_manual_curve_variant(
            draft,
            variant_id=item.semantic_id,
            source_points=points,
            actor="Private fixture reviewer",
            notes="Entered local review points.",
            input_origin="empty",
        )
    for item in curve_items:
        draft = review_curve_variant(
            draft,
            item.semantic_id,
            actor="Private fixture reviewer",
            notes="Verified local curve review.",
        )
    return draft


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

    expected_slots = sum(
        len(spec.variant_slots)
        for recipe in recipe_registry.RECIPES
        if recipe.id in {identity.recipe_id for identity in extracted_draft.source_identities}
        for spec in recipe.curves
    )
    assert len(curve_items) == expected_slots
    assert all(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in curve_items)
    assert len({item.semantic_id for item in curve_items}) == len(curve_items)
    assert all(item.source.geometry is not None for item in curve_items)


def test_unreviewed_manual_curve_slots_block_initial_approval(extracted_draft) -> None:
    blockers = approval_blockers(extracted_draft)
    curve_blockers = tuple(item for item in blockers if item.kind == "curve")

    assert len(curve_blockers) == sum(
        len(spec.variant_slots)
        for recipe in recipe_registry.RECIPES
        if recipe.id in {identity.recipe_id for identity in extracted_draft.source_identities}
        for spec in recipe.curves
    )
    assert all(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in curve_blockers)


def test_manual_curve_review_approves_round_trips_and_evaluates(
    reviewed_draft,
    tmp_path: Path,
) -> None:
    """Local manual input completes every slot without recording source values."""
    reviewed = _complete_manual_curve_review(reviewed_draft)
    package = approve_draft(
        reviewed,
        approver="Private fixture reviewer",
        notes="Approved local manual curve review.",
    )
    archive = tmp_path / "manual-curve-review.icrules"
    write_rule_package(archive, package)
    reloaded = load_rule_package(archive)

    assert tuple(map(canonical_model_sha256, reloaded.curves)) == tuple(
        map(canonical_model_sha256, package.curves)
    )
    for curve in reloaded.curves:
        for variant in curve.variants:
            result = evaluate_piecewise_curve(curve, variant.selector, variant.points[0].x)
            assert result.status == "matched"
            assert result.value is not None
            assert result.value == variant.points[0].y
