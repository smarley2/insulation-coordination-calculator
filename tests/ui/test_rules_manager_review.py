from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    approve_draft,
    is_fully_resolved,
)
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.ui.rules_manager import RulesManagerWindow
from tests.rules.test_importer import (
    _review_all as build_reviewed,
)
from tests.rules.test_importer import (
    create_geometry_pdf,
)


@pytest.fixture
def rules_manager(qtbot, tmp_path: Path) -> RulesManagerWindow:
    window = RulesManagerWindow(rules_dir=tmp_path / "rules")
    qtbot.addWidget(window)
    return window


@pytest.fixture
def supported_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    create_geometry_pdf(
        part1,
        standard="IEC 60664-1",
        edition="2020",
        edition_anchor="Edition 3.0 2020-05",
        topic_anchor="synthetic low-voltage geometry",
        table_anchor="Table S1",
    )
    create_geometry_pdf(
        part4,
        standard="IEC 60664-4",
        edition="2005",
        edition_anchor="first edition 2005",
        topic_anchor="synthetic high-frequency geometry",
        table_anchor="Table S4",
    )
    return part1, part4


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch):
    from tests.rules.test_importer import _test_recipes

    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


def test_draft_requires_review_and_blocks_approve(
    qtbot, rules_manager, supported_pdfs
) -> None:
    draft = extract_draft(supported_pdfs)
    rules_manager.set_draft(draft)
    assert rules_manager.review_count == len(draft.review_items)
    assert rules_manager.resolved_count == 0
    assert rules_manager.is_fully_resolved is False
    assert rules_manager.export_approved_enabled is False
    assert rules_manager.can_approve is False


def test_build_reviewed_content_unlocks_approval(
    qtbot, rules_manager, supported_pdfs, injected_recipes
) -> None:
    draft = extract_draft(supported_pdfs)
    rules_manager.set_draft(draft)
    assert rules_manager.can_approve is False

    from insulation_coordination.rules.importer.review import build_reviewed_draft

    reviewed = build_reviewed_draft(draft, actor="Maintainer", notes="auto review")
    rules_manager.set_draft(reviewed)
    assert rules_manager.is_fully_resolved is True
    assert rules_manager.can_approve is True


def test_resolving_all_items_enables_approval(
    qtbot, rules_manager, supported_pdfs, injected_recipes
) -> None:
    original = extract_draft(supported_pdfs)
    reviewed = build_reviewed(original, recipe_registry.RECIPES)
    rules_manager.set_draft(reviewed)
    assert rules_manager.is_fully_resolved is True
    assert rules_manager.resolved_count == len(reviewed.review_items)
    assert rules_manager.can_approve is True


def test_approve_after_full_review_gates_exported_package(
    qtbot, rules_manager, supported_pdfs, injected_recipes
) -> None:
    original = extract_draft(supported_pdfs)
    reviewed = build_reviewed(original, recipe_registry.RECIPES)
    rules_manager.set_draft(reviewed)
    assert rules_manager.can_approve is True
    rules_manager.approve_reviewed_draft(approver="Maintainer", notes="Reviewed all items")
    assert rules_manager.active_package is not None
    assert rules_manager.active_package.manifest.approved is True
    assert rules_manager.export_approved_enabled is True


def test_partial_resolution_blocks_approval(
    qtbot, rules_manager, supported_pdfs, injected_recipes
) -> None:
    original = extract_draft(supported_pdfs)
    reviewed = build_reviewed(original, recipe_registry.RECIPES)
    partial = reviewed.model_copy(
        update={"review_resolutions": reviewed.review_resolutions[:-1]}
    )
    rules_manager.set_draft(partial)
    assert rules_manager.is_fully_resolved is False
    assert rules_manager.can_approve is False


def test_domain_is_fully_resolved_accepts_full_review(
    supported_pdfs, injected_recipes
) -> None:
    draft = extract_draft(supported_pdfs)
    reviewed = build_reviewed(draft, recipe_registry.RECIPES)
    assert is_fully_resolved(reviewed)
    approved = approve_draft(reviewed, "Maintainer", "ok")
    assert approved.manifest.approved is True
