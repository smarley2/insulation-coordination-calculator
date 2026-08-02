from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    approve_draft,
    is_fully_resolved,
)
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    unresolved_equation_items,
    unresolved_mapping_items,
)
from insulation_coordination.ui.rules_manager import RulesManagerWindow
from tests.rules.test_importer import (
    _accept_all_source_artifacts,
    _compound_draft,
    _test_recipes,
    create_geometry_pdf,
)
from tests.rules.test_importer import (
    _review_all as build_reviewed,
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

    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


def test_draft_requires_review_and_blocks_approve(qtbot, rules_manager, supported_pdfs) -> None:
    draft = extract_draft(supported_pdfs)
    rules_manager.set_draft(draft)
    assert rules_manager.review_count == len(draft.review_items)
    assert rules_manager.resolved_count == 0
    assert rules_manager.is_fully_resolved is False
    assert rules_manager.export_approved_enabled is False
    assert rules_manager.can_approve is False


def test_raw_review_gates_build_button(rules_manager, tmp_path: Path) -> None:
    draft = _compound_draft(tmp_path)
    rules_manager.set_draft(draft)

    assert rules_manager.review_tables_enabled is True
    assert rules_manager.build_review_enabled is False

    accepted = accept_raw_table(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )
    accepted = accept_raw_table(
        accepted,
        grid_id="raw-synthetic-part4-table",
        corrections={},
        actor="Maintainer",
        notes="Compared against PDF",
    )
    rules_manager.set_draft(accepted)

    assert rules_manager.review_tables_enabled is False
    assert rules_manager.formula_review_enabled is True
    assert rules_manager.build_review_enabled is False


def test_review_tables_opens_without_global_resolution_notes(
    qtbot,
    rules_manager,
    supported_pdfs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.RawGridReviewDialog.exec",
        lambda _dialog: 0,
    )
    rules_manager.set_draft(extract_draft(supported_pdfs))
    assert rules_manager._review_notes.text() == ""

    qtbot.mouseClick(rules_manager._review_tables_button, Qt.MouseButton.LeftButton)

    assert warnings == []


def test_build_waits_for_equation_and_mapping_review(
    rules_manager,
    supported_pdfs,
) -> None:
    draft = extract_draft(supported_pdfs)
    for grid in draft.raw_grids:
        draft = accept_raw_table(
            draft,
            grid_id=grid.id,
            corrections={},
            actor="Maintainer",
            notes="Verified table",
        )
    rules_manager.set_draft(draft)

    assert rules_manager.formula_review_enabled is True
    assert rules_manager.build_review_enabled is False

    from insulation_coordination.rules.importer.review import accept_equation_mapping

    draft = accept_equation_mapping(
        draft,
        equation_ids=tuple(item.semantic_id for item in unresolved_equation_items(draft)),
        mapping_ids=tuple(item.semantic_id for item in unresolved_mapping_items(draft)),
        actor="Maintainer",
        notes="Verified formulas and mappings",
    )
    rules_manager.set_draft(draft)

    assert rules_manager.formula_review_enabled is False
    assert rules_manager.build_review_enabled is True


def test_build_reviewed_content_unlocks_approval(
    qtbot, rules_manager, supported_pdfs, injected_recipes
) -> None:
    draft = extract_draft(supported_pdfs)
    rules_manager.set_draft(draft)
    assert rules_manager.can_approve is False

    from insulation_coordination.rules.importer.review import build_reviewed_draft

    accepted = _accept_all_source_artifacts(draft)
    reviewed = build_reviewed_draft(accepted, actor="Maintainer", notes="Build rules")
    rules_manager.set_draft(reviewed)
    assert rules_manager.is_fully_resolved is True
    assert rules_manager.can_approve is True


def test_build_reviewed_content_projects_typed_rules_after_source_review(
    qtbot, rules_manager, supported_pdfs, injected_recipes, monkeypatch
) -> None:
    draft = _accept_all_source_artifacts(extract_draft(supported_pdfs))
    rules_manager.set_draft(draft)
    rules_manager._review_notes.setText("Project accepted source artifacts")
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QMessageBox.information",
        lambda *_args: None,
    )

    assert rules_manager.is_fully_resolved is True
    assert rules_manager.build_review_enabled is True
    assert rules_manager._draft is not None
    assert rules_manager._draft.tables == ()

    rules_manager._on_build_review_clicked()

    assert rules_manager._draft is not None
    assert rules_manager._draft.tables
    assert rules_manager._draft.formulas
    assert rules_manager._draft.mappings


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
    partial = reviewed.model_copy(update={"review_resolutions": reviewed.review_resolutions[:-1]})
    rules_manager.set_draft(partial)
    assert rules_manager.is_fully_resolved is False
    assert rules_manager.can_approve is False


def test_domain_is_fully_resolved_accepts_full_review(supported_pdfs, injected_recipes) -> None:
    draft = extract_draft(supported_pdfs)
    reviewed = build_reviewed(draft, recipe_registry.RECIPES)
    assert is_fully_resolved(reviewed)
    approved = approve_draft(reviewed, "Maintainer", "ok")
    assert approved.manifest.approved is True


def test_draft_audit_tree_shows_review_state(
    rules_manager, supported_pdfs, injected_recipes
) -> None:
    rules_manager.set_draft(extract_draft(supported_pdfs))

    assert rules_manager._tree.topLevelItemCount() > 0
    assert rules_manager._tree.topLevelItem(0).text(0) == "Draft review"
