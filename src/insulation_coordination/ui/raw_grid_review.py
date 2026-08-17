"""Explicit review and correction of tables extracted from IEC PDFs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    RawGridCell,
)
from insulation_coordination.rules.importer.identify import TableAuditSpec
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    correctable_coordinates,
    fill_suggested_compound_associations,
    flagged_coordinates,
    suggested_compound_associations,
    unresolved_raw_review_items,
    unresolved_table_items,
)
from insulation_coordination.ui.axis_review import (
    AxisReviewModel,
    AxisReviewRow,
    AxisSelectorEditor,
)
from insulation_coordination.ui.page_preview import PagePreview, source_pdf_paths

__all__ = ["RawGridReviewDialog", "source_pdf_paths"]

_CELL_COLORS = {
    "numeric": QColor("#e5f4e3"),
    "ambiguous_numeric": QColor("#ffe3a3"),
    "compound": QColor("#e5f4e3"),
    "ambiguous_compound": QColor("#ffe3a3"),
    "text": QColor("#e8eef8"),
    "blank": QColor("#f0f0f0"),
    "non_scalar": QColor("#ffe3a3"),
    "range": QColor("#ffe3a3"),
}
_AXIS_PROMPT = "Select a row or column header to review the selector for that position."
_NO_SOURCE_PAGE = "Source page not available: re-extract from the PDFs to compare pages."


class RawGridReviewDialog(QDialog):
    """Show each extracted grid beside its source page and accept it explicitly."""

    draft_changed = Signal(object)

    def __init__(
        self,
        draft: ImportedRuleDraft,
        *,
        actor: str,
        pdf_paths: Mapping[str, Path] | None = None,
        pdf_passwords: Mapping[Path, str] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Review extracted IEC tables")
        self.resize(1180, 700)
        self._draft = draft
        self._actor = actor
        self._corrections: dict[str, dict[tuple[int, int] | tuple[int, int, int], Decimal]] = {}
        self._association_corrections: dict[str, dict[tuple[int, int, int], str]] = {}
        self._formula_corrections: dict[str, dict[tuple[int, int, int], str]] = {}
        self._selected_component_id: str | None = None
        self._selected_source_index: int | None = None
        # Passwords stay in memory for page rendering only; they are never stored.
        self._pdf_paths = dict(pdf_paths or {})
        self._pdf_passwords = dict(pdf_passwords or {})

        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Extracted table:"))
        self._grid_selector = QComboBox()
        for grid in draft.raw_grids:
            source = grid.source.table or "untitled"
            self._grid_selector.addItem(f"{grid.id} (table {source})", grid.id)
        self._grid_selector.currentIndexChanged.connect(self._load_grid)
        selector_row.addWidget(self._grid_selector, 1)
        layout.addLayout(selector_row)

        self._progress = QLabel()
        layout.addWidget(self._progress)

        # A table that spans pages needs every one of its pages, stacked in
        # reading order, or half the grid has no source to compare against.
        self._page_view = PagePreview(self)
        self._page_view.set_passwords(self._pdf_passwords)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self._table.currentCellChanged.connect(self._selection_changed)
        # A selector describes a row or a column, so the header is where it is edited. Both
        # this dialog's header labels and ``proposal.index`` stay exactly as they were: the
        # 1-based citation strings are printed-table text, the index is the physical position.
        self._table.verticalHeader().sectionClicked.connect(
            lambda index: self.show_axis_position("row", index)
        )
        self._table.horizontalHeader().sectionClicked.connect(
            lambda index: self.show_axis_position("column", index)
        )
        self._row_header_labels: tuple[str, ...] = ()
        self._column_header_labels: tuple[str, ...] = ()
        self._axis_position: tuple[str, int] | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._page_view)
        splitter.addWidget(self._table)
        splitter.addWidget(self._axis_pane())
        splitter.setSizes([420, 520, 280])
        layout.addWidget(splitter, 1)

        self._details = QLabel("Select a cell to compare it with the source page.")
        self._details.setWordWrap(True)
        layout.addWidget(self._details)

        self._components_table = QTableWidget()
        self._components_table.setColumnCount(4)
        self._components_table.setHorizontalHeaderLabels(
            ("Component", "Extracted text", "Value", "Formula candidate")
        )
        self._components_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._components_table.currentCellChanged.connect(self._component_selection_changed)
        self._components_table.setVisible(False)
        layout.addWidget(self._components_table)

        association_row = QHBoxLayout()
        association_row.addWidget(QLabel("Reviewed component association:"))
        self._association_selector = QComboBox()
        self._association_selector.setEnabled(False)
        self._association_selector.currentIndexChanged.connect(self._association_changed)
        association_row.addWidget(self._association_selector, 1)
        self._apply_association_button = QPushButton("Apply association")
        self._apply_association_button.setEnabled(False)
        self._apply_association_button.clicked.connect(self._apply_association)
        association_row.addWidget(self._apply_association_button)
        layout.addLayout(association_row)

        formula_row = QHBoxLayout()
        formula_row.addWidget(QLabel("Reviewed formula candidate:"))
        self._formula_selector = QComboBox()
        self._formula_selector.setEnabled(False)
        formula_row.addWidget(self._formula_selector, 1)
        self._apply_formula_button = QPushButton("Apply formula")
        self._apply_formula_button.setEnabled(False)
        self._apply_formula_button.clicked.connect(self._apply_formula)
        formula_row.addWidget(self._apply_formula_button)
        layout.addLayout(formula_row)

        editor_row = QHBoxLayout()
        editor_row.addWidget(QLabel("Reviewed decimal value:"))
        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("Select a data cell to retype its value")
        self._value_edit.setEnabled(False)
        editor_row.addWidget(self._value_edit, 1)
        self._apply_button = QPushButton("Apply value")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_value)
        editor_row.addWidget(self._apply_button)
        layout.addLayout(editor_row)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("Resolution notes:"))
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Required only when accepting this table")
        notes_row.addWidget(self._notes_edit, 1)
        layout.addLayout(notes_row)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self._fill_button = QPushButton()
        self._fill_button.clicked.connect(self._fill_suggested)
        action_row.addWidget(self._fill_button)
        self._accept_button = QPushButton("Accept table")
        self._accept_button.clicked.connect(self._accept_table)
        action_row.addWidget(self._accept_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        action_row.addWidget(close_button)
        layout.addLayout(action_row)

        self._load_grid(0)

    @property
    def reviewed_draft(self) -> ImportedRuleDraft:
        return self._draft

    @property
    def pending_cell_count(self) -> int:
        return len(unresolved_raw_review_items(self._draft))

    @property
    def pending_table_count(self) -> int:
        return len(unresolved_table_items(self._draft))

    @property
    def pending_corrections(
        self,
    ) -> dict[tuple[int, int] | tuple[int, int, int], Decimal]:
        return dict(self._corrections.get(self._current_grid_id(), {}))

    @property
    def pending_association_corrections(self) -> dict[tuple[int, int, int], str]:
        return dict(self._association_corrections.get(self._current_grid_id(), {}))

    @property
    def pending_formula_corrections(self) -> dict[tuple[int, int, int], str]:
        return dict(self._formula_corrections.get(self._current_grid_id(), {}))

    def _current_grid_id(self) -> str:
        return str(self._grid_selector.currentData() or "")

    def _current_grid(self) -> RawGrid | None:
        grid_id = self._current_grid_id()
        return next((grid for grid in self._draft.raw_grids if grid.id == grid_id), None)

    def _pending_coordinates(self, grid_id: str) -> set[tuple[int, int]]:
        return flagged_coordinates(
            item
            for item in unresolved_raw_review_items(self._draft)
            if item.semantic_id.startswith(f"{grid_id}:")
        )

    def _editable_coordinates(self, grid: RawGrid) -> set[tuple[int, int]]:
        return correctable_coordinates(grid, self._pending_coordinates(grid.id))

    def _current_spec(self) -> TableAuditSpec | None:
        from insulation_coordination.rules.importer.recipes import RECIPES

        semantic_id = self._current_grid_id().removeprefix("raw-")
        return next(
            (
                spec
                for recipe in RECIPES
                for spec in recipe.tables
                if spec.semantic_id == semantic_id
            ),
            None,
        )

    def _table_pending(self, grid_id: str) -> bool:
        semantic_id = grid_id.removeprefix("raw-")
        return any(item.semantic_id == semantic_id for item in unresolved_table_items(self._draft))

    @staticmethod
    def _row_labels(grid: RawGrid) -> tuple[str, ...]:
        labels: list[str] = []
        for segment in grid.segments:
            labels.extend(f"p{segment.page_number} r{row + 1}" for row in range(segment.row_count))
        return tuple(labels)

    @staticmethod
    def _page_numbers(grid: RawGrid) -> tuple[int, ...]:
        """Every PDF page the grid was read from, in reading order, without repeats."""
        pages: list[int] = []
        for segment in grid.segments:
            if segment.page_number not in pages:
                pages.append(segment.page_number)
        return tuple(pages)

    @property
    def page_pixmaps(self) -> tuple[QPixmap, ...]:
        """The rendered pages currently in the source pane, in reading order."""
        return self._page_view.pixmaps

    @property
    def page_messages(self) -> tuple[str, ...]:
        """Whatever the pane says in place of a page it could not show."""
        return self._page_view.messages

    def _render_pages(self, grid: RawGrid) -> None:
        """Stack this grid's pages in one zoomable scene, in reading order.

        Whole pages rather than the grid's own rectangle: judging a cell means reading the
        printed table around it, including the header rows and notes outside the data region.
        """
        self._page_view.render_regions(
            self._pdf_paths.get(grid.source.standard),
            tuple((page_number, None) for page_number in self._page_numbers(grid)),
            unavailable=_NO_SOURCE_PAGE,
        )

    # -- Axis selectors ----------------------------------------------------
    #
    # The selector for a row or a column is edited here, beside the position it describes,
    # rather than in a screen of its own where the same position carried a second number.
    # Every mutation still goes through ``review_axis_selector`` by way of AxisReviewModel,
    # which also owns the staleness test this dialog only reads.

    def _axis_pane(self) -> QWidget:
        pane = QWidget()
        pane_layout = QVBoxLayout(pane)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        self._axis_position_label = QLabel(_AXIS_PROMPT)
        self._axis_position_label.setWordWrap(True)
        pane_layout.addWidget(self._axis_position_label)
        self._axis_editor = AxisSelectorEditor("Axis selector")
        self._axis_editor.changed.connect(self._refresh_axis_confirm)
        pane_layout.addWidget(self._axis_editor)
        self._confirm_axis_button = QPushButton("Confirm selector")
        self._confirm_axis_button.setEnabled(False)
        self._confirm_axis_button.clicked.connect(self._confirm_axis_selector)
        pane_layout.addWidget(self._confirm_axis_button)
        self._axis_status = QLabel()
        self._axis_status.setWordWrap(True)
        pane_layout.addWidget(self._axis_status)
        pane_layout.addStretch(1)
        return pane

    @property
    def axis_status_text(self) -> str:
        return self._axis_status.text()

    def _axis_rows(self) -> tuple[AxisReviewRow, ...]:
        """This grid's axis positions with their live status, straight from the axis model."""
        grid_id = self._current_grid_id()
        return tuple(row for row in AxisReviewModel(self._draft).rows() if row.grid_id == grid_id)

    @staticmethod
    def _with_status(label: str, status: str | None) -> str:
        return label if status is None else f"{label} · {status}"

    def _apply_axis_statuses(self) -> None:
        """Show each position's review status against the row or column it describes."""
        statuses = {(row.axis, row.index): row.status for row in self._axis_rows()}
        self._table.setVerticalHeaderLabels(
            [
                self._with_status(label, statuses.get(("row", index)))
                for index, label in enumerate(self._row_header_labels)
            ]
        )
        self._table.setHorizontalHeaderLabels(
            [
                self._with_status(label, statuses.get(("column", index)))
                for index, label in enumerate(self._column_header_labels)
            ]
        )

    def _clear_axis_panel(self) -> None:
        self._axis_position = None
        self._axis_position_label.setText(_AXIS_PROMPT)
        self._axis_status.clear()
        self._axis_editor.clear()

    def show_axis_position(self, axis: str, index: int) -> None:
        """Offer the selected header's own selector editor, pre-filled with what it reads."""
        row = next(
            (item for item in self._axis_rows() if (item.axis, item.index) == (axis, index)),
            None,
        )
        labels = self._row_header_labels if axis == "row" else self._column_header_labels
        visible = labels[index] if index < len(labels) else str(index)
        if row is None:
            self._clear_axis_panel()
            self._axis_position_label.setText(f"{visible} carries no axis selector position.")
            return
        self._axis_position = (axis, index)
        self._axis_status.clear()
        self._axis_position_label.setText(f"Selector for {axis} {visible}: {row.status}")
        self._axis_editor.show_selector(
            row.selector_kind, row.confirmed if row.confirmed is not None else row.proposed
        )

    def _refresh_axis_confirm(self) -> None:
        self._confirm_axis_button.setEnabled(
            self._axis_position is not None and self._axis_editor.complete
        )

    def _confirm_axis_selector(self) -> None:
        """Record the visible reading for the selected position. The importer owns the mutation."""
        if self._axis_position is None:
            return
        axis, index = self._axis_position
        model = AxisReviewModel(self._draft)
        try:
            self._draft = model.confirm(
                self._current_grid_id(),
                axis,
                index,
                self._axis_editor.selector(),
                actor=self._actor,
                notes="confirmed beside the reviewed row or column",
            )
        except (RulePackageError, ValidationError) as error:
            self._axis_status.setText(f"Selector refused: {error}")
            return
        self.draft_changed.emit(self._draft)
        self._apply_axis_statuses()
        self.show_axis_position(axis, index)
        self._axis_status.setText("Selector confirmed for this position.")

    def _load_grid(self, _index: int) -> None:
        grid = self._current_grid()
        if grid is None:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._row_header_labels = ()
            self._column_header_labels = ()
            self._clear_axis_panel()
            self._accept_button.setEnabled(False)
            self._refresh_fill_button(None)
            return
        pending = self._pending_coordinates(grid.id)
        self._table.clear()
        self._table.setRowCount(grid.rows)
        self._table.setColumnCount(grid.columns)
        spec = self._current_spec()
        headings = (
            tuple(column.heading for column in spec.columns)
            if spec is not None and len(spec.columns) == grid.columns
            else tuple(f"Column {column + 1}" for column in range(grid.columns))
        )
        self._column_header_labels = headings
        self._row_header_labels = self._row_labels(grid)
        self._clear_axis_panel()
        self._apply_axis_statuses()
        corrections = self._corrections.get(grid.id, {})
        for cell in grid.cells:
            coordinate = (cell.row, cell.column)
            item = QTableWidgetItem(cell.raw_text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(_CELL_COLORS[cell.parse_status])
            if coordinate in corrections:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                item.setText(f"{cell.raw_text} → {corrections[coordinate]}")
            item.setToolTip(self._cell_details(cell, coordinate in pending))
            self._table.setItem(cell.row, cell.column, item)
        self._table.resizeColumnsToContents()
        table_pending = self._table_pending(grid.id)
        self._accept_button.setEnabled(table_pending)
        self._refresh_fill_button(grid)
        state = "pending" if table_pending else "accepted"
        self._progress.setText(
            f"This table is {state}. All tables: {self.pending_table_count} pending. "
            f"Any cell can be retyped; {len(pending)} cell(s) here need an explicit decision."
        )
        self._render_pages(grid)
        self._selection_changed(-1, -1, -1, -1)

    def _cell_details(self, cell: RawGridCell, pending: bool) -> str:
        source = cell.source
        location = " ".join(
            part
            for part in (
                source.standard,
                source.edition,
                f"clause {source.clause}",
                f"table {source.table}" if source.table else None,
                source.note,
                source.row,
                source.column,
            )
            if part
        )
        corrected = self._corrections.get(self._current_grid_id(), {}).get((cell.row, cell.column))
        return (
            f"role: {cell.role}; status: {cell.parse_status}; raw: {cell.raw_text!r}; "
            f"normalized: {cell.value}; qualifier: {cell.qualifier}; "
            f"footnotes: {', '.join(cell.footnotes) or 'none'}; "
            f"pending review: {'yes' if pending else 'no'}; "
            f"pending correction: {corrected}; source: {location}"
        )

    def _selection_changed(
        self,
        row: int,
        column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        grid = self._current_grid()
        if grid is None:
            return
        cell = next(
            (
                candidate
                for candidate in grid.cells
                if (candidate.row, candidate.column) == (row, column)
            ),
            None,
        )
        pending = (row, column) in self._pending_coordinates(grid.id)
        editable = (row, column) in self._editable_coordinates(grid)
        self._value_edit.setEnabled(editable)
        self._apply_button.setEnabled(editable)
        if cell is None:
            self._details.setText("Select a cell to compare it with the source page.")
            self._value_edit.clear()
            self._components_table.setRowCount(0)
            self._components_table.setVisible(False)
            self._selected_component_id = None
            self._selected_source_index = None
            return
        self._details.setText(self._cell_details(cell, pending))
        self._components_table.setRowCount(len(cell.components))
        self._components_table.setVisible(bool(cell.components))
        formulas = {
            source_index: tuple(
                candidate.formula_id or "unresolved"
                for candidate in cell.formula_candidates
                if candidate.source_index == source_index
            )
            for source_index in {part.source_index for part in cell.components}
        }
        for index, component in enumerate(cell.components):
            component_value = self._corrections.get(grid.id, {}).get(
                (row, column, component.source_index), component.value
            )
            effective_component_id = self._association_corrections.get(grid.id, {}).get(
                (row, column, component.source_index), component.component_id
            )
            for item_column, text in enumerate(
                (
                    effective_component_id or "unresolved",
                    component.raw_text,
                    "" if component_value is None else str(component_value),
                    self._formula_corrections.get(grid.id, {}).get(
                        (row, column, component.source_index),
                        ", ".join(formulas.get(component.source_index, ())) or "none",
                    ),
                )
            ):
                self._components_table.setItem(index, item_column, QTableWidgetItem(text))
        if cell.components:
            self._components_table.setCurrentCell(0, 0)
        else:
            self._selected_component_id = None
            self._selected_source_index = None
            value = self._corrections.get(grid.id, {}).get((row, column), cell.value)
            self._value_edit.setText("" if not editable or value is None else str(value))

    def _component_selection_changed(
        self,
        row: int,
        _column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        grid = self._current_grid()
        cell_row, cell_column = self._table.currentRow(), self._table.currentColumn()
        if grid is None or row < 0:
            self._selected_component_id = None
            self._selected_source_index = None
            return
        cell = next(
            (
                candidate
                for candidate in grid.cells
                if (candidate.row, candidate.column) == (cell_row, cell_column)
            ),
            None,
        )
        if cell is None or row >= len(cell.components):
            self._selected_component_id = None
            self._selected_source_index = None
            return
        component = cell.components[row]
        key = (cell_row, cell_column, component.source_index)
        self._selected_component_id = self._association_corrections.get(grid.id, {}).get(
            key, component.component_id
        )
        self._selected_source_index = component.source_index
        value = self._corrections.get(grid.id, {}).get(key, component.value)
        self._value_edit.setEnabled(True)
        self._apply_button.setEnabled(True)
        self._value_edit.setText("" if value is None else str(value))
        self._association_selector.blockSignals(True)
        self._association_selector.clear()
        for component_id in cell.compound_component_ids:
            self._association_selector.addItem(component_id, component_id)
        selected_association = self._association_selector.findData(self._selected_component_id)
        self._association_selector.setCurrentIndex(max(0, selected_association))
        self._association_selector.blockSignals(False)
        self._association_selector.setEnabled(True)
        self._apply_association_button.setEnabled(True)
        self._load_formula_candidates(cell, key)

    def _association_changed(self, _index: int) -> None:
        grid = self._current_grid()
        if grid is None or self._selected_source_index is None:
            return
        coordinate = (self._table.currentRow(), self._table.currentColumn())
        cell = next(
            (
                candidate
                for candidate in grid.cells
                if (candidate.row, candidate.column) == coordinate
            ),
            None,
        )
        if cell is None:
            return
        self._load_formula_candidates(
            cell,
            (*coordinate, self._selected_source_index),
            component_id=str(self._association_selector.currentData() or ""),
            preserve_existing=False,
        )

    def _load_formula_candidates(
        self,
        cell: RawGridCell,
        key: tuple[int, int, int],
        *,
        component_id: str | None = None,
        preserve_existing: bool = True,
    ) -> None:
        if component_id is None:
            component_id = self._association_corrections.get(self._current_grid_id(), {}).get(
                key, self._selected_component_id
            )
        allowed = tuple(
            formula_id
            for route_component_id, formula_id in cell.allowed_component_formula_ids
            if route_component_id == component_id
        )
        self._formula_selector.clear()
        if allowed:
            self._formula_selector.addItem("Select formula…", None)
        for formula_id in allowed:
            self._formula_selector.addItem(formula_id, formula_id)
        pending_component = self._association_corrections.get(self._current_grid_id(), {}).get(key)
        selected_formula = (
            self._formula_corrections.get(self._current_grid_id(), {}).get(key)
            if pending_component == component_id or pending_component is None and preserve_existing
            else None
        )
        if selected_formula is None and preserve_existing:
            existing = tuple(
                candidate.formula_id
                for candidate in cell.formula_candidates
                if candidate.source_index == key[2]
                and candidate.component_id == component_id
                and candidate.formula_id in allowed
            )
            selected_formula = existing[0] if len(existing) == 1 else None
        if selected_formula is not None:
            self._formula_selector.setCurrentIndex(
                self._formula_selector.findData(selected_formula)
            )
        self._formula_selector.setEnabled(bool(allowed))
        self._apply_formula_button.setEnabled(bool(allowed))

    def _apply_association(self) -> None:
        grid = self._current_grid()
        if grid is None or self._selected_source_index is None:
            return
        row, column = self._table.currentRow(), self._table.currentColumn()
        component_id = str(self._association_selector.currentData() or "")
        if not component_id:
            return
        key = (row, column, self._selected_source_index)
        cell = next(cell for cell in grid.cells if (cell.row, cell.column) == (row, column))
        allowed = {
            formula_id
            for route_component_id, formula_id in cell.allowed_component_formula_ids
            if route_component_id == component_id
        }
        formula_id = str(self._formula_selector.currentData() or "")
        if allowed and formula_id not in allowed:
            QMessageBox.warning(
                self,
                "Review Component Association",
                "Select an exact formula for the reviewed component route.",
            )
            return
        self._association_corrections.setdefault(grid.id, {})[key] = component_id
        if formula_id:
            self._formula_corrections.setdefault(grid.id, {})[key] = formula_id
        else:
            self._formula_corrections.get(grid.id, {}).pop(key, None)
        self._selected_component_id = component_id
        item = self._components_table.item(self._components_table.currentRow(), 0)
        if item is not None:
            item.setText(component_id)
        formula_item = self._components_table.item(self._components_table.currentRow(), 3)
        if formula_item is not None:
            formula_item.setText(formula_id or "none")
        self._load_formula_candidates(cell, key)

    def _apply_formula(self) -> None:
        grid = self._current_grid()
        if grid is None or self._selected_source_index is None:
            return
        formula_id = str(self._formula_selector.currentData() or "")
        if not formula_id:
            return
        key = (
            self._table.currentRow(),
            self._table.currentColumn(),
            self._selected_source_index,
        )
        self._formula_corrections.setdefault(grid.id, {})[key] = formula_id
        item = self._components_table.item(self._components_table.currentRow(), 3)
        if item is not None:
            item.setText(formula_id)

    def _apply_value(self) -> None:
        grid = self._current_grid()
        coordinate = (self._table.currentRow(), self._table.currentColumn())
        if grid is None or coordinate not in self._editable_coordinates(grid):
            return
        try:
            value = Decimal(self._value_edit.text().strip())
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Review Extracted Cell", "Enter a decimal value.")
            return
        if not value.is_finite():
            QMessageBox.warning(self, "Review Extracted Cell", "Value must be finite.")
            return
        correction_coordinate: tuple[int, int] | tuple[int, int, int] = coordinate
        if self._selected_source_index is not None:
            correction_coordinate = (*coordinate, self._selected_source_index)
        self._corrections.setdefault(grid.id, {})[correction_coordinate] = value
        cell = next(cell for cell in grid.cells if (cell.row, cell.column) == coordinate)
        item = self._table.item(*coordinate)
        if item is not None:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            suffix = (
                f" ({self._selected_component_id})"
                if self._selected_component_id is not None
                else ""
            )
            item.setText(f"{cell.raw_text} → {value}{suffix}")
            item.setToolTip(
                self._cell_details(cell, coordinate in self._pending_coordinates(grid.id))
            )
        self._details.setText(
            self._cell_details(cell, coordinate in self._pending_coordinates(grid.id))
        )

    def _refresh_fill_button(self, grid: RawGrid | None) -> None:
        suggested = suggested_compound_associations(grid) if grid is not None else {}
        cells = {(row, column) for row, column, _source_index in suggested}
        self._fill_button.setText(f"Fill suggested associations and values ({len(cells)})")
        self._fill_button.setEnabled(bool(cells))

    def _fill_suggested(self) -> None:
        """Record the suggested association and extracted value for every suggested cell.

        The filled cells stay visible and coloured for scan review, and the table itself
        stays pending: accepting it remains the reviewer's explicit decision.
        """
        try:
            self._draft, _filled, _skipped = fill_suggested_compound_associations(
                self._draft,
                grid_id=self._current_grid_id(),
                actor=self._actor,
                notes="filled the suggested component associations; extracted values kept",
            )
        except ValueError as error:
            QMessageBox.warning(self, "Review Extracted Table", str(error))
            return
        self.draft_changed.emit(self._draft)
        self._load_grid(self._grid_selector.currentIndex())

    def _accept_table(self) -> None:
        grid_id = self._current_grid_id()
        notes = self._notes_edit.text().strip()
        if not notes:
            QMessageBox.warning(
                self,
                "Review Extracted Table",
                "Resolution notes are required to accept this table.",
            )
            return
        try:
            self._draft = accept_raw_table(
                self._draft,
                grid_id=grid_id,
                corrections=self._corrections.get(grid_id, {}),
                actor=self._actor,
                notes=notes,
                component_associations=self._association_corrections.get(grid_id, {}),
                formula_selections=self._formula_corrections.get(grid_id, {}),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Review Extracted Table", str(error))
            return
        self._corrections.pop(grid_id, None)
        self._association_corrections.pop(grid_id, None)
        self._formula_corrections.pop(grid_id, None)
        self._notes_edit.clear()
        self.draft_changed.emit(self._draft)
        if not self.pending_table_count:
            self.accept()
            return
        next_index = next(
            (
                index
                for index in range(self._grid_selector.count())
                if self._table_pending(str(self._grid_selector.itemData(index)))
            ),
            self._grid_selector.currentIndex(),
        )
        self._grid_selector.setCurrentIndex(next_index)
        self._load_grid(next_index)
