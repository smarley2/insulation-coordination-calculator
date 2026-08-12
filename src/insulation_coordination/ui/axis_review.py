"""Axis selector review: confirm, correct or supply one selector per axis position.

Qt holds no review logic. Every decision goes through review_axis_selector, which records an
audited correction and binds the review to the exact proposal and its per-position evidence.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelector,
    DvcDesignationSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    axis_review_is_current,
    review_axis_selector,
)

_HEADINGS = ("table", "axis", "position", "proposed", "status")

_SELECTOR_MODELS: dict[
    str, type[DvcDesignationSelector | Table2QuantitySelector | ProtectionTargetSelector]
] = {
    "dvc_designation": DvcDesignationSelector,
    "table2_quantity": Table2QuantitySelector,
    "protection_target": ProtectionTargetSelector,
}


def _dimensions(selector_kind: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each dimension of one selector kind with its own vocabulary.

    Read from the model's own total ``Literal`` annotations, so the UI never carries a
    hand-written copy of a vocabulary that could drift from the model it has to build.
    A field that stops being a total ``Literal`` of strings is refused here rather than
    degrading silently: ``get_args`` would yield nothing or types, leaving that dimension's
    combo holding only its blank placeholder, so Confirm never enables, the position can
    never be confirmed, and approval blocks on it with nothing to explain why.
    """

    dimensions = tuple(
        (name, get_args(field.annotation))
        for name, field in _SELECTOR_MODELS[selector_kind].model_fields.items()
        if name != "selector_kind"
    )
    for name, options in dimensions:
        if not options or not all(isinstance(option, str) for option in options):
            raise RulePackageError(
                f"{selector_kind}.{name} declares no vocabulary of strings the review "
                "dialog could offer"
            )
    return dimensions


class AxisReviewRow(FrozenModel):
    """One axis position as the reviewer sees it."""

    grid_id: str
    axis: Literal["row", "column"]
    index: int
    proposed: AxisSelector | None
    confirmed: AxisSelector | None
    selector_kind: str
    status: Literal["needs_review", "reviewed"]


class AxisReviewModel:
    """Review actions over one draft's axis selector proposals."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    def rows(self) -> tuple[AxisReviewRow, ...]:
        rows: list[AxisReviewRow] = []
        for proposal in self._draft.axis_selector_proposals:
            # The same currency test ``approval_blockers`` applies, against the same live
            # grid: reading the proposal's own stored evidence hash instead would report
            # every position reviewed while approval stayed blocked on one of them, with
            # nothing on this surface telling the reviewer which.
            exact = next(
                (
                    review
                    for review in self._draft.axis_selector_reviews
                    if axis_review_is_current(review, proposal, self._draft)
                ),
                None,
            )
            rows.append(
                AxisReviewRow(
                    grid_id=proposal.grid_id,
                    axis=proposal.axis,
                    index=proposal.index,
                    proposed=proposal.selector,
                    confirmed=exact.confirmed_selector if exact else None,
                    selector_kind=proposal.selector_kind,
                    status="reviewed" if exact else "needs_review",
                )
            )
        return tuple(rows)

    def confirm(
        self,
        grid_id: str,
        axis: str,
        index: int,
        selector: AxisSelector,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = review_axis_selector(
            self._draft,
            grid_id=grid_id,
            axis=axis,
            index=index,
            selector=selector,
            actor=actor,
            notes=notes,
        )
        return self._draft


class AxisReviewDialog(QDialog):
    """One table of axis positions, with an editor for the selected position's selector.

    No wizard: a reviewer sees every position at once, and confirms, corrects or supplies the
    selected one. The editor's combos come from the selector models themselves, so a position
    can only be confirmed as the kind its axis declares.
    """

    def __init__(self, model: AxisReviewModel, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Review axis selectors")
        self._model = model
        self._combos: dict[str, QComboBox] = {}
        self._editor_kind: str | None = None
        self.table = QTableWidget(0, len(_HEADINGS), self)
        self.table.setHorizontalHeaderLabels([heading for heading in _HEADINGS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._load_editor)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._editor_box = QGroupBox("Selector for the selected position", self)
        self._editor_form = QFormLayout(self._editor_box)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self.confirm_button = QPushButton("Confirm selector", self)
        # Nothing is selected yet, and a draft with no axis positions never selects a row, so
        # ``_load_editor`` would never run to disable this.
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.confirm_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.confirm_button)
        actions.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self._editor_box)
        layout.addWidget(self._status)
        layout.addLayout(actions)
        self.refresh()
        if self.table.rowCount():
            self.table.selectRow(0)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def dimension_options(self) -> dict[str, tuple[str, ...]]:
        """The visible editor's vocabulary per dimension, without the blank placeholder."""

        return {
            field: tuple(
                combo.itemText(item) for item in range(combo.count()) if combo.itemText(item)
            )
            for field, combo in self._combos.items()
        }

    def dimension_combo(self, field: str) -> QComboBox:
        return self._combos[field]

    def refresh(self) -> None:
        rows = self._model.rows()
        self.table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            proposed = "" if row.proposed is None else row.proposed.selector_kind
            for column, text in enumerate(
                (row.grid_id, row.axis, str(row.index), proposed, row.status)
            ):
                self.table.setItem(position, column, QTableWidgetItem(text))

    def confirm_selected(self) -> None:
        """Record the visible reading for the selected position. The model owns the mutation."""

        position = self.table.currentRow()
        row = self._current_row()
        if row is None:
            self._status.setText("Select an axis position first.")
            return
        values = {field: combo.currentText() for field, combo in self._combos.items()}
        if not all(values.values()):
            self._status.setText("Choose every dimension before confirming this selector.")
            return
        try:
            self._model.confirm(
                row.grid_id,
                row.axis,
                row.index,
                _SELECTOR_MODELS[row.selector_kind].model_validate(values),
                actor="maintainer",
                notes="confirmed in the axis selector review dialog",
            )
        except (RulePackageError, ValidationError) as error:
            self._status.setText(f"Selector refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._status.setText("Selector confirmed for this position.")

    def _current_row(self) -> AxisReviewRow | None:
        rows = self._model.rows()
        position = self.table.currentRow()
        return rows[position] if 0 <= position < len(rows) else None

    def _load_editor(self) -> None:
        """Offer the selected position's kind, pre-filled with what it already reads."""

        row = self._current_row()
        if row is None:
            self.confirm_button.setEnabled(False)
            return
        if self._editor_kind != row.selector_kind:
            self._build_editor(row.selector_kind)
        selector = row.confirmed if row.confirmed is not None else row.proposed
        for field, combo in self._combos.items():
            combo.setCurrentText("" if selector is None else getattr(selector, field))
        self._refresh_confirm_enabled()

    def _build_editor(self, selector_kind: str) -> None:
        while self._editor_form.rowCount():
            self._editor_form.removeRow(0)
        self._combos = {}
        for field, options in _dimensions(selector_kind):
            combo = QComboBox()
            # A blank first entry, so a position nothing was proposed for starts unchosen: a
            # reviewer must never be able to record a selector they did not pick.
            combo.addItem("")
            combo.addItems(options)
            combo.currentIndexChanged.connect(self._refresh_confirm_enabled)
            self._editor_form.addRow(field.replace("_", " "), combo)
            self._combos[field] = combo
        self._editor_kind = selector_kind

    def _refresh_confirm_enabled(self) -> None:
        self.confirm_button.setEnabled(
            bool(self._combos) and all(combo.currentText() for combo in self._combos.values())
        )


__all__ = ["AxisReviewDialog", "AxisReviewModel", "AxisReviewRow"]
