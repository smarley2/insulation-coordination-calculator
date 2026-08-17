"""Saving, autosaving and resuming a draft from the Rules Manager.

Drafts here are extracted from the synthetic PDFs the importer tests build, so nothing licensed
is written to disk and every ``.icdraft`` file stays inside ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.rules.draft_archive import load_rule_draft
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    draft_review_digest,
    unresolved_table_items,
)
from insulation_coordination.ui.rules_manager import RulesManagerWindow
from tests.rules.test_importer import _test_recipes
from tests.ui.test_rules_manager_review import supported_pdfs as _supported_pdfs


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


@pytest.fixture
def source_pdfs(tmp_path: Path) -> tuple[Path, ...]:
    """The three synthetic standards, built by the fixture the review tests already use."""
    return _supported_pdfs.__wrapped__(tmp_path)


@pytest.fixture
def rules_manager(qtbot, tmp_path: Path) -> RulesManagerWindow:
    window = RulesManagerWindow(rules_dir=tmp_path / "rules")
    qtbot.addWidget(window)
    return window


def _select_files(monkeypatch: pytest.MonkeyPatch, paths: tuple[Path, ...]) -> None:
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QFileDialog.getOpenFileNames",
        lambda *_args, **_kwargs: ([str(path) for path in paths], "PDF files (*.pdf)"),
    )


def _extracted(
    window: RulesManagerWindow,
    monkeypatch: pytest.MonkeyPatch,
    source_pdfs: tuple[Path, ...],
) -> None:
    _select_files(monkeypatch, source_pdfs)
    window._on_extract_draft_clicked()


def _save_to(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(path), "Draft Under Review (*.icdraft)"),
    )


def _resume_from(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "Draft Under Review (*.icdraft)"),
    )


def test_saving_needs_a_draft_and_becomes_available_with_one(
    qtbot, rules_manager, monkeypatch: pytest.MonkeyPatch, source_pdfs: tuple[Path, ...]
) -> None:
    assert rules_manager._save_draft_button.isEnabled() is False
    assert rules_manager._resume_draft_button.isEnabled() is True

    _extracted(rules_manager, monkeypatch, source_pdfs)

    assert rules_manager._save_draft_button.isEnabled() is True
    assert rules_manager.draft_path is None


def test_saved_draft_resumes_in_another_window_with_review_state_intact(
    qtbot,
    rules_manager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_pdfs: tuple[Path, ...],
) -> None:
    _extracted(rules_manager, monkeypatch, source_pdfs)
    path = tmp_path / "under-review.icdraft"
    _save_to(monkeypatch, path)

    qtbot.mouseClick(rules_manager._save_draft_button, Qt.MouseButton.LeftButton)

    assert path.exists()
    assert rules_manager.draft_path == path
    saved = rules_manager.draft
    assert saved is not None

    resumed_window = RulesManagerWindow(rules_dir=tmp_path / "rules")
    qtbot.addWidget(resumed_window)
    _resume_from(monkeypatch, path)

    qtbot.mouseClick(resumed_window._resume_draft_button, Qt.MouseButton.LeftButton)

    reopened = resumed_window.draft
    assert reopened is not None
    assert draft_review_digest(reopened) == draft_review_digest(saved)
    assert approval_blockers(reopened) == approval_blockers(saved)
    assert resumed_window.resolved_count == rules_manager.resolved_count
    assert resumed_window.review_count == rules_manager.review_count
    # The source pages a table review shows come back with the draft.
    assert set(resumed_window._draft_pdfs.values()) == set(source_pdfs)


def test_autosave_after_a_correction_reaches_the_saved_file(
    qtbot,
    rules_manager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_pdfs: tuple[Path, ...],
) -> None:
    _extracted(rules_manager, monkeypatch, source_pdfs)
    path = tmp_path / "under-review.icdraft"
    _save_to(monkeypatch, path)
    qtbot.mouseClick(rules_manager._save_draft_button, Qt.MouseButton.LeftButton)
    before = rules_manager.resolved_count
    draft = rules_manager.draft
    assert draft is not None
    pending = unresolved_table_items(draft)
    assert pending

    # Exactly what a review dialog does: it hands the corrected draft back through set_draft.
    rules_manager.set_draft(
        accept_raw_table(
            draft,
            grid_id=f"raw-{pending[0].semantic_id}",
            corrections={},
            actor="Maintainer",
            notes="Compared the extracted table with the PDF",
        )
    )

    assert rules_manager.resolved_count > before
    autosaved = load_rule_draft(path).draft
    assert autosaved == rules_manager.draft
    assert len(autosaved.review_resolutions) > len(draft.review_resolutions)


def test_resume_asks_before_replacing_the_draft_under_review(
    qtbot,
    rules_manager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_pdfs: tuple[Path, ...],
) -> None:
    _extracted(rules_manager, monkeypatch, source_pdfs)
    path = tmp_path / "under-review.icdraft"
    _save_to(monkeypatch, path)
    qtbot.mouseClick(rules_manager._save_draft_button, Qt.MouseButton.LeftButton)
    other = extract_draft(source_pdfs)
    rules_manager.set_draft(other)
    assert rules_manager.draft_path is None

    from PySide6.QtWidgets import QMessageBox

    asked: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QMessageBox.question",
        lambda _parent, _title, message: asked.append(message) or QMessageBox.StandardButton.No,
    )
    _resume_from(monkeypatch, path)

    qtbot.mouseClick(rules_manager._resume_draft_button, Qt.MouseButton.LeftButton)

    assert len(asked) == 1
    assert rules_manager.draft is not None
    assert rules_manager.draft.manifest.package_id == other.manifest.package_id

    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QMessageBox.question",
        lambda _parent, _title, _message: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(rules_manager._resume_draft_button, Qt.MouseButton.LeftButton)

    assert rules_manager.draft is not None
    assert rules_manager.draft.manifest.package_id != other.manifest.package_id
    assert rules_manager.draft_path == path


def test_a_second_extraction_never_autosaves_over_another_drafts_file(
    qtbot,
    rules_manager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_pdfs: tuple[Path, ...],
) -> None:
    _extracted(rules_manager, monkeypatch, source_pdfs)
    path = tmp_path / "under-review.icdraft"
    _save_to(monkeypatch, path)
    qtbot.mouseClick(rules_manager._save_draft_button, Qt.MouseButton.LeftButton)
    saved = path.read_bytes()
    first = rules_manager.draft
    assert first is not None

    _extracted(rules_manager, monkeypatch, source_pdfs)

    assert rules_manager.draft is not None
    assert rules_manager.draft.manifest.package_id != first.manifest.package_id
    assert rules_manager.draft_path is None
    assert path.read_bytes() == saved


def test_resume_reports_a_source_document_that_no_longer_matches(
    qtbot,
    rules_manager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_pdfs: tuple[Path, ...],
) -> None:
    _extracted(rules_manager, monkeypatch, source_pdfs)
    path = tmp_path / "under-review.icdraft"
    _save_to(monkeypatch, path)
    qtbot.mouseClick(rules_manager._save_draft_button, Qt.MouseButton.LeftButton)
    source_pdfs[0].write_bytes(source_pdfs[0].read_bytes() + b"% appended\n")

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.rules_manager.QMessageBox.critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    fresh = RulesManagerWindow(rules_dir=tmp_path / "rules")
    qtbot.addWidget(fresh)
    _resume_from(monkeypatch, path)

    qtbot.mouseClick(fresh._resume_draft_button, Qt.MouseButton.LeftButton)

    assert fresh.draft is None
    assert [title for title, _ in messages] == ["Resume Draft"]
    assert "missing or changed" in messages[0][1]
