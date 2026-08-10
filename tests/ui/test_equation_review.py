from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer import extract
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.extract import ExtractedEquation
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    unresolved_equation_items,
    unresolved_mapping_items,
)
from insulation_coordination.ui.equation_review import EquationReviewDialog
from tests.rules.test_importer import _compound_draft, _test_recipes


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


@pytest.fixture(autouse=True)
def maintainer_reviews_every_equation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extract drafts whose equations and mappings all await a human.

    The synthetic recipes declare no PDF-extracted equation, so a real draft
    leaves this dialog nothing to show; treating every item as PDF-derived puts
    the dialog in the state a maintainer sees for IEC 60664-4.
    """
    monkeypatch.setattr(extract, "is_recipe_derived", lambda _item: False)


def _tables_accepted(tmp_path):
    draft = _compound_draft(tmp_path)
    for grid in draft.raw_grids:
        draft = accept_raw_table(
            draft,
            grid_id=grid.id,
            corrections={},
            actor="Maintainer",
            notes="Verified table",
        )
    return draft


@pytest.fixture
def tables_accepted(tmp_path):
    return _tables_accepted(tmp_path)


def test_dialog_shows_canonical_formula_source_and_dependent_mappings(
    qtbot,
    tables_accepted,
) -> None:
    dialog = EquationReviewDialog(tables_accepted, actor="Maintainer")
    qtbot.addWidget(dialog)

    details = dialog._details.toPlainText()
    assert dialog._formula_selector.count() == 3
    assert "synthetic-part1-formula" in details
    assert "Calculation: table synthetic-part1-table[row stress (interpolated)" in details
    assert "Canonical shape (audit contract): table_select:" in details
    assert "Numbers read from the PDF (check these): none" in details
    assert "SYNTHETIC" in details
    assert dialog._mappings.count() == 1
    assert dialog._notes_edit.text() == ""
    assert not hasattr(dialog, "_edits")


def test_accept_requires_notes_and_resolves_only_current_formula_and_mappings(
    qtbot,
    tables_accepted,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.equation_review.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    dialog = EquationReviewDialog(tables_accepted, actor="Maintainer")
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)
    assert warnings == ["Resolution notes are required to accept this equation and mappings."]
    assert len(unresolved_equation_items(dialog.reviewed_draft)) == 3

    dialog._notes_edit.setText("Verified formula and route")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert len(unresolved_equation_items(dialog.reviewed_draft)) == 2
    assert len(unresolved_mapping_items(dialog.reviewed_draft)) == 2
    assert dialog._formula_selector.currentData() == "synthetic-part4-formula"


def test_accepting_the_last_equation_closes_the_dialog(qtbot, tables_accepted) -> None:
    dialog = EquationReviewDialog(tables_accepted, actor="Maintainer")
    qtbot.addWidget(dialog)

    dialog._notes_edit.setText("Verified against the source clause")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._notes_edit.setText("Verified against the source clause")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._notes_edit.setText("Verified against the source clause")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert unresolved_equation_items(dialog.reviewed_draft) == ()
    assert unresolved_mapping_items(dialog.reviewed_draft) == ()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_unresolved_extracted_equation_cannot_be_accepted(qtbot, tables_accepted) -> None:
    equation = ExtractedEquation(
        id="synthetic-part1-formula",
        raw_text="unresolved source expression",
        rendered="review required",
        variables=("stress",),
        literals=(),
        unit="mm",
        applicability="synthetic",
        parse_status="review_required",
        source=SourceReference(
            document_id="iec60664-1-2020",
            standard="IEC 60664-1",
            edition="2020",
            clause="SYNTHETIC",
            table="S1",
            page=1,
        ),
    )
    draft = tables_accepted.model_copy(update={"extracted_equations": (equation,)})

    dialog = EquationReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert "Parse status: review_required" in dialog._details.toPlainText()
    assert dialog._accept_button.isEnabled() is False


def test_dialog_exposes_mapping_without_formula_dependency(
    qtbot, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipes = _test_recipes()
    part1 = recipes[0].model_copy(
        update={
            "mappings": (
                recipes[0]
                .mappings[0]
                .model_copy(update={"target_rule_id": recipes[0].tables[0].semantic_id}),
            )
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (part1, recipes[1], recipes[2]))

    draft = _tables_accepted(tmp_path)

    dialog = EquationReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert dialog._formula_selector.count() == 4
    mapping_index = dialog._formula_selector.findData(f"mapping:{part1.mappings[0].id}")
    assert mapping_index >= 0
    dialog._formula_selector.setCurrentIndex(mapping_index)
    assert "Mapping:" in dialog._details.toPlainText()
