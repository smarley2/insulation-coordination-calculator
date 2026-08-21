"""Slice E2 closure: nothing is deferred, every required item has a recipe, and the
Rules Manager reports every one of them.

No source content: this reads the recipe registry and the required inventory, both of which
carry identifiers only.
"""

from __future__ import annotations

from pathlib import Path

from insulation_coordination.rules.importer.expectations import package_expectations
from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    DEFERRED_SEMANTIC_IDS,
    REQUIRED_SOURCE_ITEMS,
)
from insulation_coordination.rules.importer.recipes import RECIPES
from insulation_coordination.rules.importer.review import inventory_report
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft

EXPECTATIONS = package_expectations(RECIPES)


def _covers(candidate: str, semantic_id: str) -> bool:
    return candidate == semantic_id or candidate.startswith(f"{semantic_id}.")


def test_the_deferred_set_is_empty_and_every_item_has_a_recipe() -> None:
    """The public half of Issue #34's completeness claim.

    While anything was deferred, a required item without a recipe was reported as deferred
    rather than missing. With the set empty the two halves have to agree: every one of the
    items is declared by a spec, under its own identifier or one of its routes.
    """
    assert DEFERRED_SEMANTIC_IDS == frozenset()
    assert len(REQUIRED_SOURCE_ITEMS) == 36

    declared = frozenset(EXPECTATIONS.typed_results)
    for item in REQUIRED_SOURCE_ITEMS:
        assert any(_covers(candidate, item.semantic_id) for candidate in declared), item.semantic_id


def test_every_declared_route_of_a_required_item_is_expected_to_yield_a_rule() -> None:
    """A route that yields nothing would make an item look covered while carrying no rule."""

    for item in REQUIRED_SOURCE_ITEMS:
        matching = {
            candidate
            for candidate in EXPECTATIONS.typed_results
            if _covers(candidate, item.semantic_id)
        }
        typed = {
            route
            for candidate in matching - EXPECTATIONS.evidence_grid_ids
            for route in EXPECTATIONS.typed_results[candidate]
        }
        assert typed, item.semantic_id
        assert all(_covers(route, item.semantic_id) for route in typed), item.semantic_id


def test_the_rules_manager_reports_every_required_item(qtbot, tmp_path: Path) -> None:
    """A maintainer sees the whole checklist, not the part this draft happens to carry.

    The inventory the window reports comes from the required inventory rather than from the
    draft, so an item a draft skipped is still listed -- which is the only way the count of
    approved items means anything.
    """
    from insulation_coordination.ui.rules_manager import RulesManagerWindow

    window = RulesManagerWindow(rules_dir=tmp_path / "rules")
    qtbot.addWidget(window)
    draft = _draft()

    window.set_draft(draft)

    lines = {
        window._tree.topLevelItem(top).child(child).text(0)
        for top in range(window._tree.topLevelItemCount())
        for child in range(window._tree.topLevelItem(top).childCount())
    }
    inventory = inventory_report(draft)

    assert len(inventory) == len(REQUIRED_SOURCE_ITEMS)
    assert f"required source items: 0 of {len(REQUIRED_SOURCE_ITEMS)} approved, 0 deferred" in lines
    for issue in (35, 36, 37):
        consumed = tuple(status for status in inventory if issue in status.consumer_issue_ids)
        assert f"  issue #{issue}: 0 of {len(consumed)} approved" in lines
