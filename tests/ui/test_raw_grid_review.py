from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    RawGridSegment,
    parse_compound_data_cell,
)
from insulation_coordination.rules.importer.identify import CompoundQuantitySpec, TableColumnSpec
from insulation_coordination.rules.importer.review import (
    unresolved_raw_review_items,
    unresolved_table_items,
)
from insulation_coordination.ui.raw_grid_review import RawGridReviewDialog, source_pdf_paths
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
    )
    qtbot.addWidget(dialog)
    changed = []
    dialog.draft_changed.connect(changed.append)

    dialog._table.setCurrentCell(1, 1)
    dialog._value_edit.setText("1.25")
    qtbot.mouseClick(dialog._apply_button, Qt.MouseButton.LeftButton)
    dialog._notes_edit.setText("Compared against PDF")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert changed
    assert unresolved_raw_review_items(dialog.reviewed_draft) == ()
    assert len(unresolved_table_items(dialog.reviewed_draft)) == 2
    reviewed = next(
        cell
        for grid in dialog.reviewed_draft.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert reviewed.value == Decimal("1.25")
    assert reviewed.raw_text == "<= 1.2zz"
    assert dialog._current_grid_id() == "raw-synthetic-part4-table"
    assert dialog._accept_button.isEnabled() is True


def test_dialog_shows_the_source_page_next_to_the_grid(qtbot, tmp_path, draft) -> None:
    """Reviewing a parse means comparing it with the page it came from."""
    paths = (tmp_path / "part1.pdf", tmp_path / "part4.pdf")
    pdf_paths = source_pdf_paths(draft, paths)
    assert set(pdf_paths) == {"IEC 60664-1", "IEC 60664-4"}

    dialog = RawGridReviewDialog(draft, actor="Maintainer", pdf_paths=pdf_paths)
    qtbot.addWidget(dialog)

    assert dialog._page_label.text() == ""
    assert not dialog._page_label.pixmap().isNull()


def test_page_numbers_list_each_source_page_once_in_reading_order() -> None:
    grid = SimpleNamespace(
        segments=(
            SimpleNamespace(page_number=73),
            SimpleNamespace(page_number=73),
            SimpleNamespace(page_number=74),
        )
    )

    assert RawGridReviewDialog._page_numbers(grid) == (73, 74)


def test_multi_page_grid_shows_a_panel_for_every_page(qtbot, tmp_path, draft) -> None:
    """A table split across pages must offer both pages, not only the first."""
    original = draft.raw_grids[0]
    source = original.source
    split = RawGrid(
        id=original.id,
        rows=2,
        columns=1,
        target_unit=original.target_unit,
        segments=(
            RawGridSegment(page_number=1, row_start=0, row_count=1, source=source),
            RawGridSegment(page_number=2, row_start=1, row_count=1, source=source),
        ),
        cells=(
            RawGridCell(
                row=0,
                column=0,
                raw_text="page one",
                role="header",
                parse_status="text",
                source=source,
            ),
            RawGridCell(
                row=1,
                column=0,
                raw_text="page two",
                role="header",
                parse_status="text",
                source=source,
            ),
        ),
        source=source,
    )
    spanning = draft.model_copy(update={"raw_grids": (split,)})
    pdf_paths = source_pdf_paths(draft, (tmp_path / "part1.pdf", tmp_path / "part4.pdf"))

    dialog = RawGridReviewDialog(spanning, actor="Maintainer", pdf_paths=pdf_paths)
    qtbot.addWidget(dialog)

    assert not dialog._page_label.pixmap().isNull()
    assert len(dialog._extra_page_labels) == 1
    assert dialog._extra_page_labels[0].isVisibleTo(dialog._pages_widget)
    # The synthetic source has a single page, so page 2 reports itself as missing
    # rather than silently leaving half the grid unverifiable.
    assert "Source page 2 could not be rendered" in dialog._extra_page_labels[0].text()


def test_accepting_the_last_table_closes_the_dialog(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    dialog._notes_edit.setText("Compared against the source page")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.pending_table_count == 2

    dialog._notes_edit.setText("Compared against the source page")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.pending_table_count == 1

    dialog._notes_edit.setText("Compared against the source page")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert dialog.pending_table_count == 0
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_dialog_says_when_no_source_page_is_available(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert "Source page not available" in dialog._page_label.text()


def test_dialog_reports_an_unreadable_source_pdf(qtbot, tmp_path, draft) -> None:
    unreadable = tmp_path / "unreadable.pdf"
    unreadable.write_bytes(b"not a pdf at all")

    dialog = RawGridReviewDialog(
        draft,
        actor="Maintainer",
        pdf_paths={"IEC 60664-1": unreadable},
    )
    qtbot.addWidget(dialog)

    assert "could not be rendered" in dialog._page_label.text()


def test_source_pdf_paths_ignores_files_that_do_not_match_a_source(tmp_path, draft) -> None:
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-1.7 unrelated")

    assert source_pdf_paths(draft, (other, tmp_path / "absent.pdf")) == {}


def test_confidently_parsed_cell_can_still_be_corrected(qtbot, draft) -> None:
    """A cleanly parsed cell can still hold the wrong number."""
    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    clean = dialog._table.item(2, 1)
    assert clean is not None
    assert clean.text() == "2.1"
    dialog._table.setCurrentCell(2, 1)
    assert dialog._value_edit.isEnabled()

    dialog._value_edit.setText("2.15")
    qtbot.mouseClick(dialog._apply_button, Qt.MouseButton.LeftButton)
    dialog._notes_edit.setText("Retyped against PDF page 1")
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    corrected = next(
        cell
        for grid in dialog.reviewed_draft.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (2, 1)
    )
    assert corrected.value == Decimal("2.15")
    assert corrected.raw_text == "2.1"


def test_cell_outside_the_data_area_stays_read_only(qtbot, draft) -> None:
    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    dialog._table.setCurrentCell(0, 0)

    assert dialog._value_edit.isEnabled() is False
    assert dialog._apply_button.isEnabled() is False


def test_dialog_applies_association_and_formula_atomically(
    qtbot,
    draft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.raw_grid_review.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    grid = draft.raw_grids[0]
    original = next(cell for cell in grid.cells if (cell.row, cell.column) == (2, 1))
    parsed = parse_compound_data_cell(
        text="11 ac / 17 ac",
        spec=CompoundQuantitySpec(
            component_ids=("ac", "dc"),
            formula_candidates=(("ac", "synthetic-ac-formula"),),
            allowed_formula_ids=(
                ("ac", "synthetic-ac-formula"),
                ("dc", "synthetic-dc-formula"),
            ),
        ),
        source=original.source,
    )
    compound = original.model_copy(
        update={
            "raw_text": "11 ac / 17 ac",
            "value": None,
            "components": parsed.components,
            "compound_component_ids": parsed.compound_component_ids,
            "formula_candidates": parsed.formula_candidates,
            "allowed_component_formula_ids": parsed.allowed_component_formula_ids,
            "parse_status": parsed.parse_status,
        }
    )
    changed_grid = grid.model_copy(
        update={"cells": tuple(compound if cell is original else cell for cell in grid.cells)}
    )
    changed = draft.model_copy(
        update={
            "raw_grids": tuple(changed_grid if item is grid else item for item in draft.raw_grids)
        }
    )
    dialog = RawGridReviewDialog(changed, actor="Maintainer")
    qtbot.addWidget(dialog)

    dialog._table.setCurrentCell(2, 1)

    assert dialog._components_table.rowCount() == 2
    assert dialog._components_table.item(0, 0).text() == "ac"
    assert dialog._components_table.item(1, 0).text() == "ac"
    assert dialog._components_table.item(0, 2).text() == "11"
    assert dialog._components_table.item(1, 2).text() == "17"

    dialog._components_table.setCurrentCell(1, 0)
    dialog._association_selector.setCurrentIndex(dialog._association_selector.findData("dc"))
    qtbot.mouseClick(dialog._apply_association_button, Qt.MouseButton.LeftButton)

    assert warnings == ["Select an exact formula for the reviewed component route."]
    assert dialog.pending_association_corrections == {}
    assert dialog.pending_formula_corrections == {}

    dialog._formula_selector.setCurrentIndex(
        dialog._formula_selector.findData("synthetic-dc-formula")
    )
    qtbot.mouseClick(dialog._apply_association_button, Qt.MouseButton.LeftButton)

    assert dialog.pending_association_corrections == {(2, 1, 1): "dc"}
    assert dialog.pending_formula_corrections == {(2, 1, 1): "synthetic-dc-formula"}


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
    )
    qtbot.addWidget(dialog)
    dialog._table.setCurrentCell(1, 1)
    dialog._value_edit.setText(value)

    qtbot.mouseClick(dialog._apply_button, Qt.MouseButton.LeftButton)

    assert warnings
    assert dialog.pending_corrections == {}


def test_dialog_opens_without_notes_and_requires_them_only_on_accept(
    qtbot,
    draft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "insulation_coordination.ui.raw_grid_review.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert dialog._notes_edit.text() == ""
    assert dialog.reviewed_draft == draft
    qtbot.mouseClick(dialog._accept_button, Qt.MouseButton.LeftButton)

    assert warnings == ["Resolution notes are required to accept this table."]
    assert dialog.reviewed_draft == draft


def test_dialog_uses_recipe_headings_and_table_progress(
    qtbot,
    draft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe1, recipe4, recipe62477 = _test_recipes()
    columns = (
        TableColumnSpec(
            semantic_id="stress",
            heading="Stress voltage",
            source_column=0,
            role="axis",
            unit="V",
        ),
        TableColumnSpec(
            semantic_id="branch-low",
            heading="Low branch",
            source_column=1,
            role="data",
            unit="mm",
        ),
        TableColumnSpec(
            semantic_id="branch-high",
            heading="High branch",
            source_column=2,
            role="data",
            unit="mm",
        ),
    )
    table = recipe1.tables[0].model_copy(update={"columns": columns})
    monkeypatch.setattr(
        recipe_registry,
        "RECIPES",
        (recipe1.model_copy(update={"tables": (table,)}), recipe4, recipe62477),
    )

    dialog = RawGridReviewDialog(draft, actor="Maintainer")
    qtbot.addWidget(dialog)

    assert tuple(dialog._table.horizontalHeaderItem(index).text() for index in range(3)) == (
        "Stress voltage",
        "Low branch",
        "High branch",
    )
    assert dialog._progress.text() == (
        "This table is pending. All tables: 3 pending. "
        "Any cell can be retyped; 1 cell(s) here need an explicit decision."
    )
