"""Private C2 gate: reviewed DVC tables propose; approval stays blocked on curves.

Derives everything from the licensed PDFs at runtime. Never asserts, prints,
snapshots, or serializes licensed values into repository artifacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import ApprovalError, approve_draft
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.review import (
    accept_clause_fragment,
    accept_equation_mapping,
    accept_raw_grid,
    accept_raw_table,
    build_reviewed_draft,
    mark_proposal_reviewed,
    unresolved_clause_items,
    unresolved_equation_items,
    unresolved_mapping_items,
    unresolved_raw_review_items,
    unresolved_table_items,
)

pytestmark = pytest.mark.private_standard


@pytest.fixture
def draft(extracted_draft):
    """The shared import from ``conftest``; every review step returns a new draft."""

    return extracted_draft


def test_dvc_grid_shapes_are_structural(draft) -> None:
    grids = {grid.id: grid for grid in draft.raw_grids}
    voltage_limits = grids[f"raw-{ids.DVC_VOLTAGE_LIMITS}"]
    protection = grids[f"raw-{ids.DVC_PROTECTION_MATRIX}"]
    assert (voltage_limits.rows, voltage_limits.columns) == (8, 6)
    assert (protection.rows, protection.columns) == (9, 7)
    assert f"raw-{ids.DVC_FAULT_APPLICABILITY}" in {
        fragment.id for fragment in draft.raw_clause_fragments
    }


def test_initial_draft_proposes_nothing_reviewed(draft) -> None:
    assert all(proposal.state == "proposed" for proposal in draft.semantic_proposals)


def _review_all_c2_proposals(draft):
    reviewed = draft
    for item in unresolved_table_items(reviewed):
        grid_id = f"raw-{item.semantic_id}"
        grid = next(grid for grid in reviewed.raw_grids if grid.id == grid_id)
        pending = tuple(
            raw
            for raw in unresolved_raw_review_items(reviewed)
            if raw.semantic_id.startswith(f"{grid_id}:")
            and raw.code in {"AMBIGUOUS_COMPOUND_CELL", "AMBIGUOUS_COMPONENT_FORMULA"}
        )
        occurrences = {
            tuple(map(int, raw.semantic_id.rsplit(":", 3)[1:]))
            for raw in pending
        }
        associations = {}
        formulas = {}
        for row, column, source_index in occurrences:
            cell = next(
                cell
                for cell in grid.cells
                if (cell.row, cell.column) == (row, column)
            )
            component_id = cell.compound_component_ids[source_index]
            associations[(row, column, source_index)] = component_id
            formulas[(row, column, source_index)] = next(
                formula_id
                for candidate_id, formula_id in cell.allowed_component_formula_ids
                if candidate_id == component_id
            )
        reviewed = accept_raw_table(
            reviewed,
            grid_id=grid_id,
            corrections={},
            component_associations=associations,
            formula_selections=formulas,
            actor="Maintainer",
            notes="Reviewed extracted table.",
        )
    pending = unresolved_raw_review_items(reviewed)
    grid_ids = {item.semantic_id.rsplit(":", 2)[0] for item in pending}
    for grid_id in sorted(grid_ids):
        reviewed = accept_raw_grid(
            reviewed,
            grid_id=grid_id,
            corrections={},
            actor="Maintainer",
            notes="Reviewed raw grid cells.",
        )
    equation_ids = tuple(item.semantic_id for item in unresolved_equation_items(reviewed))
    mapping_ids = tuple(item.semantic_id for item in unresolved_mapping_items(reviewed))
    if equation_ids or mapping_ids:
        reviewed = accept_equation_mapping(
            reviewed,
            equation_ids=equation_ids,
            mapping_ids=mapping_ids,
            actor="Maintainer",
            notes="Reviewed equations and mappings.",
        )
    for item in unresolved_clause_items(reviewed):
        reviewed = accept_clause_fragment(
            reviewed,
            semantic_id=item.semantic_id,
            actor="Maintainer",
            notes="Reviewed clause fragment.",
        )
    built = build_reviewed_draft(reviewed, actor="Maintainer", notes="Build rules.")
    for proposal in tuple(built.semantic_proposals):
        if proposal.semantic_id == ids.DVC_FAULT_TIME_VOLTAGE:
            continue
        built = mark_proposal_reviewed(
            built,
            proposal.semantic_id,
            actor="Maintainer",
            notes="Reviewed projected rule.",
        )
    return built


#: Importing all three licensed documents takes about twenty seconds, most of it
#: rasterizing the source figures, and proving determinism means doing it twice and then
#: reviewing every extracted artifact. That is the work this test exists to do, so it gets
#: room for it rather than a faster but weaker assertion.
@pytest.mark.timeout(600)
def test_deterministic_c2_proposal_hashes(
    reviewed_draft,
    supplied_paths: tuple[Path, ...],
) -> None:
    """Two independent imports must review to identical proposals.

    The shared review pass is one of the two; the second is imported and reviewed fresh
    here, because comparing two separate runs end to end is the assertion.
    """
    first = reviewed_draft
    second = _review_all_c2_proposals(extract_draft(supplied_paths))
    assert [
        (item.semantic_id, item.rule_sha256, item.source_artifact_sha256)
        for item in first.semantic_proposals
    ] == [
        (item.semantic_id, item.rule_sha256, item.source_artifact_sha256)
        for item in second.semantic_proposals
    ]


def test_c2_review_completeness_still_blocks_on_missing_curve(reviewed_draft) -> None:
    reviewed = reviewed_draft
    with pytest.raises(ApprovalError, match="fault_time_voltage"):
        approve_draft(reviewed, "Maintainer", "Approve C2 content.")
