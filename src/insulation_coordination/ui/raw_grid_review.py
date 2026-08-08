"""Explicit review and correction of tables extracted from IEC PDFs."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
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
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    RawGrid,
    RawGridCell,
)
from insulation_coordination.rules.importer.identify import TableAuditSpec
from insulation_coordination.rules.importer.review import (
    accept_raw_table,
    correctable_coordinates,
    flagged_coordinates,
    unresolved_raw_review_items,
    unresolved_table_items,
)

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
_PAGE_RESOLUTION = 110


def source_pdf_paths(
    draft: ImportedRuleDraft,
    paths: tuple[Path, ...],
) -> dict[str, Path]:
    """Map each recognized standard to the PDF on disk it was extracted from.

    Matching is by content digest, not filename, so a renamed or swapped file
    cannot end up displayed beside another standard's grid.
    """
    digests: dict[str, Path] = {}
    for path in paths:
        try:
            digests[hashlib.sha256(Path(path).read_bytes()).hexdigest()] = Path(path)
        except OSError:
            continue
    return {
        identity.standard: digests[identity.sha256]
        for identity in getattr(draft, "source_identities", ())
        if identity.sha256 in digests
    }


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
        self._corrections: dict[
            str, dict[tuple[int, int] | tuple[int, int, str], Decimal]
        ] = {}
        self._selected_component_id: str | None = None
        # Passwords stay in memory for page rendering only; they are never stored.
        self._pdf_paths = dict(pdf_paths or {})
        self._pdf_passwords = dict(pdf_passwords or {})
        self._page_cache: dict[tuple[Path, int], QPixmap] = {}

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
        self._page_label = QLabel("Source page not available.")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._pages_widget = QWidget()
        self._pages_layout = QVBoxLayout(self._pages_widget)
        self._pages_layout.setContentsMargins(0, 0, 0, 0)
        self._pages_layout.addWidget(self._page_label)
        self._pages_layout.addStretch(1)
        self._extra_page_labels: list[QLabel] = []
        page_scroll = QScrollArea()
        page_scroll.setWidget(self._pages_widget)
        page_scroll.setWidgetResizable(True)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self._table.currentCellChanged.connect(self._selection_changed)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(page_scroll)
        splitter.addWidget(self._table)
        splitter.setSizes([460, 700])
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
    ) -> dict[tuple[int, int] | tuple[int, int, str], Decimal]:
        return dict(self._corrections.get(self._current_grid_id(), {}))

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

    def _page_pixmap(self, path: Path, page_number: int) -> QPixmap:
        """Render one page, raising nothing the caller cannot report."""
        cached = self._page_cache.get((path, page_number))
        if cached is not None:
            return cached
        with pdfplumber.open(path, password=self._pdf_passwords.get(path, "")) as pdf:
            image = pdf.pages[page_number - 1].to_image(resolution=_PAGE_RESOLUTION)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self._page_cache[(path, page_number)] = pixmap
        return pixmap

    def _page_target(self, index: int) -> QLabel:
        """The label showing the index-th page of the current grid."""
        if index == 0:
            return self._page_label
        while len(self._extra_page_labels) < index:
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            self._extra_page_labels.append(label)
            self._pages_layout.insertWidget(len(self._extra_page_labels), label)
        return self._extra_page_labels[index - 1]

    def _render_pages(self, grid: RawGrid) -> None:
        for label in self._extra_page_labels:
            label.clear()
            label.setVisible(False)
        path = self._pdf_paths.get(grid.source.standard)
        if path is None:
            self._page_label.setPixmap(QPixmap())
            self._page_label.setText(
                "Source page not available: re-extract from the PDFs to compare pages."
            )
            return
        for index, page_number in enumerate(self._page_numbers(grid)):
            label = self._page_target(index)
            label.setVisible(True)
            try:
                pixmap = self._page_pixmap(path, page_number)
            except (OSError, IndexError, TypeError, ValueError, PdfminerException) as error:
                label.setPixmap(QPixmap())
                label.setText(f"Source page {page_number} could not be rendered: {error}")
                continue
            label.setText("")
            label.setPixmap(pixmap)

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
            return
        self._details.setText(self._cell_details(cell, pending))
        self._components_table.setRowCount(len(cell.components))
        self._components_table.setVisible(bool(cell.components))
        formulas = {
            component_id: tuple(
                candidate.formula_id or "unresolved"
                for candidate in cell.formula_candidates
                if candidate.component_id == component_id
            )
            for component_id in {part.component_id for part in cell.components}
        }
        for index, component in enumerate(cell.components):
            component_value = self._corrections.get(grid.id, {}).get(
                (row, column, component.component_id), component.value
            )
            for item_column, text in enumerate(
                (
                    component.component_id,
                    component.raw_text,
                    "" if component_value is None else str(component_value),
                    ", ".join(formulas.get(component.component_id, ())) or "none",
                )
            ):
                self._components_table.setItem(index, item_column, QTableWidgetItem(text))
        if cell.components:
            self._components_table.setCurrentCell(0, 0)
        else:
            self._selected_component_id = None
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
            return
        component = cell.components[row]
        self._selected_component_id = component.component_id
        value = self._corrections.get(grid.id, {}).get(
            (cell_row, cell_column, component.component_id), component.value
        )
        self._value_edit.setEnabled(True)
        self._apply_button.setEnabled(True)
        self._value_edit.setText("" if value is None else str(value))

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
        correction_coordinate: tuple[int, int] | tuple[int, int, str] = coordinate
        if self._selected_component_id is not None:
            correction_coordinate = (*coordinate, self._selected_component_id)
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
