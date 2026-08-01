from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtCore import Qt

from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.review import unresolved_raw_review_items
from insulation_coordination.ui.raw_grid_review import RawGridReviewDialog
from tests.rules.test_importer import _compound_draft, _test_recipes


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


@pytest.fixture
def draft(tmp_path):
    return _compound_draft(tmp_path)


def test_dialog_shows_complete_grid_and_flags_review_cells(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(
        draft,
        actor="Maintainer",
        notes="Compared against PDF",
    )
    qtbot.addWidget(dialog)
    grid = draft.raw_grids[0]

    assert dialog._grid_selector.count() == len(draft.raw_grids)
    assert dialog._table.rowCount() == grid.rows
    assert dialog._table.columnCount() == grid.columns
    assert dialog.pending_cell_count == 1
    flagged = dialog._table.item(1, 1)
    assert flagged is not None
    assert flagged.text() == "<= 1.2zz"
    assert "ambiguous_numeric" in flagged.toolTip()
    assert dialog._accept_button.isEnabled()


def test_dialog_applies_value_then_accepts_only_current_table(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(
        draft,
        actor="Maintainer",
        notes="Compared against PDF",
    )
    qtbot.addWidget(dialog)
    changed = []
    dialog.draft_changed.connect(changed.append)

    dialog._table.setCurrentCell(1, 1)
    dialog._value_edit.setText("1.25")
    qtbot.mouseClick(dialog._apply_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert changed
    assert unresolved_raw_review_items(dialog.reviewed_draft) == ()
    reviewed = next(
        cell
        for grid in dialog.reviewed_draft.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert reviewed.value == Decimal("1.25")
    assert reviewed.raw_text == "<= 1.2zz"
    assert dialog._accept_button.isEnabled() is False


@pytest.mark.parametrize("value", ("", "not-a-number", "NaN"))
def test_dialog_rejects_invalid_cell_value(
    qtbot,
    draft,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.raw_grid_review.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    dialog = RawGridReviewDialog(
        draft,
        actor="Maintainer",
        notes="Compared against PDF",
    )
    qtbot.addWidget(dialog)
    dialog._table.setCurrentCell(1, 1)
    dialog._value_edit.setText(value)

    qtbot.mouseClick(dialog._apply_button, Qt.MouseButton.LeftButton)

    assert warnings
    assert dialog.pending_corrections == {}
