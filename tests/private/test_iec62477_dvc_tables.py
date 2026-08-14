"""Private C2 gate: reviewed DVC tables propose; approval stays blocked on curves.

Derives everything from the licensed PDFs at runtime. Never asserts, prints,
snapshots, or serializes licensed values into repository artifacts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    approve_draft,
)
from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelector,
    AxisSelectorProposal,
    ProtectionTargetSelector,
)
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.review import (
    accept_clause_fragment,
    accept_equation_mapping,
    accept_raw_grid,
    accept_raw_table,
    build_reviewed_draft,
    mark_proposal_reviewed,
    review_axis_selector,
    unresolved_clause_items,
    unresolved_equation_items,
    unresolved_mapping_items,
    unresolved_raw_review_items,
    unresolved_table_items,
)
from tests.private.test_iec62477_supply_clause_facts import (
    author_placeholder_supply_clause_facts,
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


#: Table 3's column axis has no public grammar (see ``tables.py``'s ``TABLE_3``), so its six
#: proposals carry no reading and a reviewer must supply one by hand. This inventory is
#: invented for the review chain, not read from the source: it exists only to give each of
#: the six positions a distinct, valid ``ProtectionTargetSelector``. ``index - 1`` below pairs
#: each real physical column with one of them. That pairing is deranged against the licensed
#: column layout -- no column receives the selector the source assigns it -- and is
#: deliberately not that layout displaced by a fixed step, so one recovered pairing yields
#: nothing about the other five. It must not be read as the real column layout.
_PROTECTION_TARGET_INVENTORY: tuple[ProtectionTargetSelector, ...] = (
    ProtectionTargetSelector(
        target="accessible_part",
        pe_relationship="not_connected_to_pe",
        access_context="general_access",
        person_scope="ordinary_or_skilled",
        adjacent_dvc="not_applicable",
    ),
    ProtectionTargetSelector(
        target="adjacent_circuit",
        pe_relationship="not_applicable",
        access_context="not_applicable",
        person_scope="not_applicable",
        adjacent_dvc="dvc_as",
    ),
    ProtectionTargetSelector(
        target="adjacent_circuit",
        pe_relationship="not_applicable",
        access_context="not_applicable",
        person_scope="not_applicable",
        adjacent_dvc="dvc_c",
    ),
    ProtectionTargetSelector(
        target="adjacent_circuit",
        pe_relationship="not_applicable",
        access_context="not_applicable",
        person_scope="not_applicable",
        adjacent_dvc="dvc_b",
    ),
    ProtectionTargetSelector(
        target="accessible_part",
        pe_relationship="connected_to_pe",
        access_context="general_access",
        person_scope="ordinary_or_skilled",
        adjacent_dvc="not_applicable",
    ),
    ProtectionTargetSelector(
        target="accessible_part",
        pe_relationship="not_applicable",
        access_context="service_or_restricted_access",
        person_scope="skilled_only",
        adjacent_dvc="not_applicable",
    ),
)


def _reviewer_supplied_selector(proposal: AxisSelectorProposal) -> AxisSelector:
    """A structural stand-in reading for a proposal the recipe left unread.

    Only the protection-matrix's six column positions currently propose nothing; this
    hands each its own member of the invented inventory above, by physical column index.
    The fallback applies only to that exact axis: silently supplying a stand-in for any
    other missing proposal would hide a genuine "should propose but doesn't" extraction bug
    behind a plausible-looking selector instead of failing loudly.
    """

    if not (proposal.grid_id == f"raw-{ids.DVC_PROTECTION_MATRIX}" and proposal.axis == "column"):
        raise AssertionError(
            f"{proposal.grid_id} {proposal.axis} position {proposal.index} proposed no "
            "selector, and only the protection matrix's column axis is reviewer-supplied"
        )
    return _PROTECTION_TARGET_INVENTORY[proposal.index - 1]


def _review_all_axis_selectors(draft):
    """Confirm the proposal's own reading, or supply one, for every axis position."""

    reviewed = draft
    for proposal in reviewed.axis_selector_proposals:
        reviewed = review_axis_selector(
            reviewed,
            grid_id=proposal.grid_id,
            axis=proposal.axis,
            index=proposal.index,
            selector=proposal.selector or _reviewer_supplied_selector(proposal),
            actor="Maintainer",
            notes="Reviewed axis selector.",
        )
    return reviewed


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
        occurrences = {tuple(map(int, raw.semantic_id.rsplit(":", 3)[1:])) for raw in pending}
        associations = {}
        formulas = {}
        for row, column, source_index in occurrences:
            cell = next(cell for cell in grid.cells if (cell.row, cell.column) == (row, column))
            component_id = cell.compound_component_ids[source_index]
            associations[(row, column, source_index)] = component_id
            # Only a component whose recipe declares a formula route needs one selected;
            # offering a formula where no route exists is refused, by design.
            route = next(
                (
                    formula_id
                    for candidate_id, formula_id in cell.allowed_component_formula_ids
                    if candidate_id == component_id
                ),
                None,
            )
            if route is not None:
                formulas[(row, column, source_index)] = route
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
    reviewed = _review_all_axis_selectors(reviewed)
    # Every non-legacy supply route takes its branches from a reviewed clause fact, so the
    # review pass has to author them before anything can be projected. The statements are
    # local placeholders and live beside the clause-fact lifecycle tests; see that module.
    reviewed = author_placeholder_supply_clause_facts(reviewed)
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


def test_the_licensed_tables_propose_every_axis_position(draft) -> None:
    """Real extraction must enumerate all eighteen positions across both DVC tables."""

    proposals = draft.axis_selector_proposals
    by_grid: dict[str, int] = {}
    for item in proposals:
        by_grid[item.grid_id] = by_grid.get(item.grid_id, 0) + 1

    assert by_grid[f"raw-{ids.DVC_VOLTAGE_LIMITS}"] == 9
    assert by_grid[f"raw-{ids.DVC_PROTECTION_MATRIX}"] == 9
    # Every position except the protection matrix's reviewer-supplied column axis must
    # actually propose a reading. Counting positions alone would not catch a keyword
    # grammar that enumerates a position but never matches its header text.
    assert all(
        item.selector is not None
        for item in proposals
        if not (item.grid_id == f"raw-{ids.DVC_PROTECTION_MATRIX}" and item.axis == "column")
    )


def test_the_protection_matrix_columns_await_the_reviewer(draft) -> None:
    """That axis has no public grammar, so the licensed run proposes nothing for it."""

    columns = [
        item
        for item in draft.axis_selector_proposals
        if item.grid_id == f"raw-{ids.DVC_PROTECTION_MATRIX}" and item.axis == "column"
    ]

    assert len(columns) == 6
    assert all(item.selector is None for item in columns)


def test_an_unreviewed_axis_blocks_approval_of_the_licensed_draft(draft) -> None:
    codes = {item.code for item in approval_blockers(draft)}

    assert "AXIS_SELECTOR_REVIEW_REQUIRED" in codes


def test_reviewed_licensed_tables_project_semantic_selectors_only(reviewed_draft) -> None:
    """The full chain: licensed extraction, reviewed axes, semantic projection.

    ``reviewed_draft`` already carries every axis position confirmed -- see
    ``_review_all_axis_selectors`` above -- and its projected decisions are what this
    checks: the runtime contract for both DVC tables carries semantic selector values
    only, never the positional placeholders a pre-#53 package would have served.
    """

    for rule in reviewed_draft.decisions:
        if rule.id.startswith(ids.DVC_VOLTAGE_LIMITS) or rule.id == ids.DVC_PROTECTION_MATRIX:
            for declared in rule.inputs:
                for value in declared.allowed_values:
                    assert not re.fullmatch(
                        r"dvc-\d+|voltage-quantity-\d+|protection-context-\d+", value
                    )
