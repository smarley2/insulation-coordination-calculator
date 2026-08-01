"""Explicit review and correction of tables extracted from IEC PDFs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    RawGridCell,
)
from insulation_coordination.rules.importer.identify import TableAuditSpec
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    unresolved_raw_review_items,
    unresolved_table_items,
)

_CELL_COLORS = {
    "numeric": QColor("#e5f4e3"),
    "ambiguous_numeric": QColor("#ffe3a3"),
    "text": QColor("#e8eef8"),
    "blank": QColor("#f0f0f0"),
    "non_scalar": QColor("#ffe3a3"),
    "range": QColor("#ffe3a3"),
}


class RawGridReviewDialog(QDialog):
    """Show complete extracted grids and explicitly accept flagged cells."""

    draft_changed = Signal(object)

    def __init__(
        self,
        draft: ImportedRuleDraft,
        *,
        actor: str,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Review extracted IEC tables")
        self.resize(900, 620)
        self._draft = draft
        self._actor = actor
        self._corrections: dict[str, dict[tuple[int, int], Decimal]] = {}

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

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self._table.currentCellChanged.connect(self._selection_changed)
        layout.addWidget(self._table, 1)

        self._details = QLabel("Select a flagged cell to inspect it.")
        self._details.setWordWrap(True)
        layout.addWidget(self._details)

        editor_row = QHBoxLayout()
        editor_row.addWidget(QLabel("Reviewed decimal value:"))
        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("Select a highlighted review cell")
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
    def pending_corrections(self) -> dict[tuple[int, int], Decimal]:
        return dict(self._corrections.get(self._current_grid_id(), {}))

    def _current_grid_id(self) -> str:
        return str(self._grid_selector.currentData() or "")

    def _current_grid(self) -> RawGrid | None:
        grid_id = self._current_grid_id()
        return next((grid for grid in self._draft.raw_grids if grid.id == grid_id), None)

    def _pending_coordinates(self, grid_id: str) -> set[tuple[int, int]]:
        return {
            (
                int(item.semantic_id.rsplit(":", 2)[-2]),
                int(item.semantic_id.rsplit(":", 2)[-1]),
            )
            for item in unresolved_raw_review_items(self._draft)
            if item.semantic_id.startswith(f"{grid_id}:")
        }

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
            labels.extend(
                f"p{segment.page_number} r{row + 1}" for row in range(segment.row_count)
            )
        return tuple(labels)

    def _load_grid(self, _index: int) -> None:
        grid = self._current_grid()
        if grid is None:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._accept_button.setEnabled(False)
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
        self._table.setHorizontalHeaderLabels(headings)
        self._table.setVerticalHeaderLabels(self._row_labels(grid))
        for cell in grid.cells:
            item = QTableWidgetItem(cell.raw_text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(_CELL_COLORS[cell.parse_status])
            item.setToolTip(self._cell_details(cell, (cell.row, cell.column) in pending))
            self._table.setItem(cell.row, cell.column, item)
        self._table.resizeColumnsToContents()
        table_pending = self._table_pending(grid.id)
        self._accept_button.setEnabled(table_pending)
        state = "pending" if table_pending else "accepted"
        self._progress.setText(
            f"This table is {state}. All tables: {self.pending_table_count} pending."
        )
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
        self._value_edit.setEnabled(pending)
        self._apply_button.setEnabled(pending)
        if cell is None:
            self._details.setText("Select a flagged cell to inspect it.")
            self._value_edit.clear()
            return
        self._details.setText(self._cell_details(cell, pending))
        value = self._corrections.get(grid.id, {}).get((row, column), cell.value)
        self._value_edit.setText("" if not pending or value is None else str(value))

    def _apply_value(self) -> None:
        grid = self._current_grid()
        coordinate = (self._table.currentRow(), self._table.currentColumn())
        if grid is None or coordinate not in self._pending_coordinates(grid.id):
            return
        try:
            value = Decimal(self._value_edit.text().strip())
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Review Extracted Cell", "Enter a decimal value.")
            return
        if not value.is_finite():
            QMessageBox.warning(self, "Review Extracted Cell", "Value must be finite.")
            return
        self._corrections.setdefault(grid.id, {})[coordinate] = value
        cell = next(cell for cell in grid.cells if (cell.row, cell.column) == coordinate)
        item = self._table.item(*coordinate)
        if item is not None:
            item.setToolTip(self._cell_details(cell, True))
        self._details.setText(self._cell_details(cell, True))

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
            )
        except ValueError as error:
            QMessageBox.warning(self, "Review Extracted Table", str(error))
            return
        self._corrections.pop(grid_id, None)
        self._notes_edit.clear()
        self.draft_changed.emit(self._draft)
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
