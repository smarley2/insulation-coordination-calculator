"""Axis selector review: confirm, correct or supply one selector per axis position.

Qt holds no review logic. Every decision goes through review_axis_selector, which records an
audited correction and binds the review to the exact proposal and its per-position evidence.

The editor a reviewer types a selector into lives here as a widget, and the screen that shows
it is the raw grid review dialog, beside the row or column the selector describes. This module
holds no screen of its own.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, get_args

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelector,
    DvcDesignationSelector,
    FrequencyBandSelector,
    ProtectionTargetSelector,
    Table2QuantitySelector,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    axis_review_is_current,
    review_axis_selector,
)

_SELECTOR_MODELS: dict[
    str,
    type[
        DvcDesignationSelector
        | Table2QuantitySelector
        | ProtectionTargetSelector
        | FrequencyBandSelector
    ],
] = {
    "dvc_designation": DvcDesignationSelector,
    "table2_quantity": Table2QuantitySelector,
    "protection_target": ProtectionTargetSelector,
    "frequency_band": FrequencyBandSelector,
}
#: Shown where extraction read no quantity for a position, so the reviewer sees an unread
#: position rather than a blank that could pass for a value.
_NOTHING_READ = "not read from the source"


def _extracted_fields(selector_kind: str) -> tuple[str, ...]:
    """Dimensions the reviewer reads rather than chooses: the quantities the source states.

    A band's bounds belong to the document, so the editor shows them and offers no way to
    type another number -- a reviewer who could would be declaring a boundary instead of
    confirming one. They ride through from the proposal, and a position nothing was read from
    carries none and so can never be confirmed.
    """

    return tuple(
        name
        for name, field in _SELECTOR_MODELS[selector_kind].model_fields.items()
        if field.annotation is Decimal
    )


def _dimensions(selector_kind: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each chosen dimension of one selector kind with its own vocabulary.

    Read from the model's own total ``Literal`` annotations, so the UI never carries a
    hand-written copy of a vocabulary that could drift from the model it has to build.
    A field that stops being a total ``Literal`` of strings is refused here rather than
    degrading silently: ``get_args`` would yield nothing or types, leaving that dimension's
    combo holding only its blank placeholder, so Confirm never enables, the position can
    never be confirmed, and approval blocks on it with nothing to explain why. An extracted
    quantity is not a vocabulary and is not offered as one; it is excluded before the check.
    """

    extracted = _extracted_fields(selector_kind)
    dimensions = tuple(
        (name, get_args(field.annotation))
        for name, field in _SELECTOR_MODELS[selector_kind].model_fields.items()
        if name != "selector_kind" and name not in extracted
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
        self._extracted: dict[str, str] = {}
        self._extracted_labels: dict[str, QLabel] = {}
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
    def extracted_values(self) -> dict[str, str]:
        """The quantities this position was read as, shown for confirmation, never editable."""

        return dict(self._extracted)

    @property
    def complete(self) -> bool:
        """Whether the position is ready to confirm.

        Every chosen dimension must be chosen, and every extracted quantity the kind declares
        must have arrived from the proposal. No dimensions at all is never complete.
        """

        if self._kind is None:
            return False
        extracted = _extracted_fields(self._kind)
        if set(extracted) != set(self._extracted):
            return False
        return bool(self._combos or extracted) and all(
            combo.currentText() for combo in self._combos.values()
        )

    def dimension_combo(self, field: str) -> QComboBox:
        return self._combos[field]

    def clear(self) -> None:
        """Offer nothing, for a position that is not selected or carries no axis selector."""

        self._reset()
        self._kind = None
        self.changed.emit()

    def show_selector(self, selector_kind: str, selector: AxisSelector | None) -> None:
        """Offer one kind's dimensions, pre-filled with what the position already reads."""

        self._build(selector_kind)
        for field, combo in self._combos.items():
            combo.setCurrentText("" if selector is None else getattr(selector, field))
        for field in _extracted_fields(selector_kind):
            if selector is None:
                continue
            self._extracted[field] = str(getattr(selector, field))
            self._extracted_labels[field].setText(self._extracted[field])
        self.changed.emit()

    def selector(self) -> AxisSelector:
        """The visible reading, as the kind this editor was built for."""

        if self._kind is None:
            raise RulePackageError("no axis selector kind is on offer")
        return _SELECTOR_MODELS[self._kind].model_validate(
            {
                **self._extracted,
                **{field: combo.currentText() for field, combo in self._combos.items()},
            }
        )

    def _reset(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._combos = {}
        self._extracted = {}
        self._extracted_labels = {}

    def _build(self, selector_kind: str) -> None:
        # Rebuilt for every position, not only for a new kind: an extracted quantity differs
        # per position, so a cached editor would show the previous position's bounds beside
        # this one's combos and confirm them.
        self._reset()
        for field in _extracted_fields(selector_kind):
            label = QLabel(_NOTHING_READ)
            self._form.addRow(field.replace("_", " "), label)
            self._extracted_labels[field] = label
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


__all__ = ["AxisReviewModel", "AxisReviewRow", "AxisSelectorEditor"]
