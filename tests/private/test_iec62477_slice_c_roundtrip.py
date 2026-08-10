"""Private reviewed Slice C archive and semantic API proof.

The licensed PDFs are consumed only at runtime.  Assertions are deliberately limited
to semantic IDs, canonical model equality, and evaluation status.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.evaluator import (
    evaluate_piecewise_curve,
    select_curve_variant,
)
from insulation_coordination.rules.importer.approval import approve_draft
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.review import review_curve_variant

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


def _approved_slice_c(reviewed):
    """Approve an already-reviewed draft: the review pass is shared by fixture."""

    variant_ids = tuple(
        variant.id
        for curve in reviewed.curves
        if curve.id == ids.DVC_FAULT_TIME_VOLTAGE
        for variant in curve.variants
    )
    for variant_id in variant_ids:
        reviewed = review_curve_variant(
            reviewed,
            variant_id,
            actor="Private fixture reviewer",
            notes="Verified curve against supplied PDF",
        )
    return approve_draft(
        reviewed,
        approver="Private fixture reviewer",
        notes="Approved reviewed Slice C package",
    )


def test_reviewed_slice_c_round_trips_and_every_selector_evaluates(
    tmp_path: Path,
    reviewed_draft,
) -> None:
    package = _approved_slice_c(reviewed_draft)
    archive = tmp_path / "reviewed-slice-c.icrules"
    write_rule_package(archive, package)
    reloaded = load_rule_package(archive)

    assert tuple(map(canonical_model_sha256, reloaded.curves)) == tuple(
        map(canonical_model_sha256, package.curves)
    )
    curve = next(item for item in reloaded.curves if item.id == ids.DVC_FAULT_TIME_VOLTAGE)
    for variant in curve.variants:
        selection = select_curve_variant(curve, variant.selector)
        assert selection.status == "matched"
        assert selection.variant is not None
        assert canonical_model_sha256(selection.variant) == canonical_model_sha256(variant)
        result = evaluate_piecewise_curve(curve, variant.selector, variant.points[0].x)
        assert result.status == "matched"


def test_table_2_references_resolve_to_single_slice_c_targets(reviewed_draft) -> None:
    package = _approved_slice_c(reviewed_draft)
    references = {
        value.reference
        for decision in package.decisions
        for row in decision.rows
        for value in row.values
        if value.reference is not None
    }
    required = {
        ids.DVC_FAULT_TIME_VOLTAGE,
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
        f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
    }
    targets = (
        *package.tables,
        *package.formulas,
        *package.decisions,
        *package.procedures,
        *package.guidance,
        *package.curves,
    )

    assert required <= references
    assert all(sum(target.id == reference for target in targets) == 1 for reference in required)
