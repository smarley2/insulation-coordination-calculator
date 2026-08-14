"""Axis selector review: confirm, correct or supply one selector per axis position.

Qt holds no review logic. Every decision goes through review_axis_selector, which records an
audited correction and binds the review to the exact proposal and its per-position evidence.

The editor a reviewer types a selector into lives here as a widget, but the screen that shows
it is the raw grid review dialog, beside the row or column the selector describes. This module
keeps the read-only overview of every position across every grid.
"""

from __future__ import annotations

from typing import Literal, get_args

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
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


class AxisSelectorEditor(QGroupBox):
    """One combo per dimension of a single selector kind, built from the selector models.

    The vocabularies stay read from the models here rather than in the screen that shows the
    editor, so a position can only ever be edited as the kind its axis declares.
    """

    changed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._form = QFormLayout(self)
        self._combos: dict[str, QComboBox] = {}
        self._kind: str | None = None

    @property
    def dimension_options(self) -> dict[str, tuple[str, ...]]:
        """The visible editor's vocabulary per dimension, without the blank placeholder."""

        return {
            field: tuple(
                combo.itemText(item) for item in range(combo.count()) if combo.itemText(item)
            )
            for field, combo in self._combos.items()
        }

    @property
    def complete(self) -> bool:
        """Whether every dimension has been chosen. No combos is never complete."""

        return bool(self._combos) and all(combo.currentText() for combo in self._combos.values())

    def dimension_combo(self, field: str) -> QComboBox:
        return self._combos[field]

    def clear(self) -> None:
        """Offer nothing, for a position that is not selected or carries no axis selector."""

        while self._form.rowCount():
            self._form.removeRow(0)
        self._combos = {}
        self._kind = None
        self.changed.emit()

    def show_selector(self, selector_kind: str, selector: AxisSelector | None) -> None:
        """Offer one kind's dimensions, pre-filled with what the position already reads."""

        if self._kind != selector_kind:
            self._build(selector_kind)
        for field, combo in self._combos.items():
            combo.setCurrentText("" if selector is None else getattr(selector, field))
        self.changed.emit()

    def selector(self) -> AxisSelector:
        """The visible reading, as the kind this editor was built for."""

        if self._kind is None:
            raise RulePackageError("no axis selector kind is on offer")
        return _SELECTOR_MODELS[self._kind].model_validate(
            {field: combo.currentText() for field, combo in self._combos.items()}
        )

    def _build(self, selector_kind: str) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._combos = {}
        for field, options in _dimensions(selector_kind):
            combo = QComboBox()
            # A blank first entry, so a position nothing was proposed for starts unchosen: a
            # reviewer must never be able to record a selector they did not pick.
            combo.addItem("")
            combo.addItems(options)
            combo.currentIndexChanged.connect(self.changed)
            self._form.addRow(field.replace("_", " "), combo)
            self._combos[field] = combo
        self._kind = selector_kind


class AxisReviewDialog(QDialog):
    """Read-only overview of every axis position of every grid, with its status.

    Confirming a selector happens in the raw grid review dialog, beside the row or column it
    describes; this screen answers what is still pending for the whole draft in one place.
    """

    def __init__(self, model: AxisReviewModel, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Axis selector review status")
        self._model = model
        self.table = QTableWidget(0, len(_HEADINGS), self)
        self.table.setHorizontalHeaderLabels([heading for heading in _HEADINGS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        rows = self._model.rows()
        self.table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            proposed = "" if row.proposed is None else row.proposed.selector_kind
            for column, text in enumerate(
                (row.grid_id, row.axis, str(row.index), proposed, row.status)
            ):
                self.table.setItem(position, column, QTableWidgetItem(text))


__all__ = ["AxisReviewDialog", "AxisReviewModel", "AxisReviewRow", "AxisSelectorEditor"]
