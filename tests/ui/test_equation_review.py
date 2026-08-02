from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.domain.rules import SourceReference
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


@pytest.fixture
def tables_accepted(tmp_path):
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


def test_dialog_shows_canonical_formula_source_and_dependent_mappings(
    qtbot,
    tables_accepted,
) -> None:
    dialog = EquationReviewDialog(tables_accepted, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert dialog._formula_selector.count() == 2
    assert "synthetic-part1-formula" in dialog._details.toPlainText()
    assert "linear_interpolate" in dialog._details.toPlainText()
    assert "SYNTHETIC" in dialog._details.toPlainText()
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
    assert len(unresolved_equation_items(dialog.reviewed_draft)) == 2

    dialog._notes_edit.setText("Verified formula and route")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert len(unresolved_equation_items(dialog.reviewed_draft)) == 1
    assert len(unresolved_mapping_items(dialog.reviewed_draft)) == 1
    assert dialog._formula_selector.currentData() == "synthetic-part4-formula"


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
            standard="IEC 60664-1",
            edition="2020",
            clause="SYNTHETIC",
            table="S1",
            note="PDF page 1",
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
    monkeypatch.setattr(recipe_registry, "RECIPES", (part1, recipes[1]))
    from tests.rules.test_importer import _compound_draft

    draft = _compound_draft(tmp_path)
    for grid in draft.raw_grids:
        draft = accept_raw_table(
            draft,
            grid_id=grid.id,
            corrections={},
            actor="Maintainer",
            notes="Verified table",
        )

    dialog = EquationReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert dialog._formula_selector.count() == 3
    mapping_index = dialog._formula_selector.findData(f"mapping:{part1.mappings[0].id}")
    assert mapping_index >= 0
    dialog._formula_selector.setCurrentIndex(mapping_index)
    assert "Mapping:" in dialog._details.toPlainText()
