"""Explicit review of canonical IEC formulas/equations and semantic mappings."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
)
from insulation_coordination.rules.importer.review import (
    accept_equation_mapping,
    unresolved_equation_items,
    unresolved_mapping_items,
)


class EquationReviewDialog(QDialog):
    """Review one canonical formula/equation and its dependent mappings at a time."""

    draft_changed = Signal(object)

    def __init__(self, draft: ImportedRuleDraft, *, actor: str) -> None:
        super().__init__()
        self.setWindowTitle("Review IEC equations and mappings")
        self.resize(760, 560)
        self._draft = draft
        self._actor = actor

        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Equation / formula:"))
        self._formula_selector = QComboBox()
        self._formula_selector.currentIndexChanged.connect(self._load_current)
        selector_row.addWidget(self._formula_selector, 1)
        layout.addLayout(selector_row)

        self._progress = QLabel()
        layout.addWidget(self._progress)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        layout.addWidget(self._details, 1)

        layout.addWidget(QLabel("Dependent semantic mappings:"))
        self._mappings = QListWidget()
        layout.addWidget(self._mappings)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("Resolution notes:"))
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Required only when accepting")
        notes_row.addWidget(self._notes_edit, 1)
        layout.addLayout(notes_row)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self._accept_button = QPushButton("Accept equation and mappings")
        self._accept_button.clicked.connect(self._accept_current)
        action_row.addWidget(self._accept_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        action_row.addWidget(close_button)
        layout.addLayout(action_row)

        self._reload_selector()

    @property
    def reviewed_draft(self) -> ImportedRuleDraft:
        return self._draft

    @staticmethod
    def _recipe_specs() -> tuple[
        dict[str, FormulaAuditSpec],
        dict[str, MappingAuditSpec],
    ]:
        from insulation_coordination.rules.importer.recipes import RECIPES

        return (
            {spec.semantic_id: spec for recipe in RECIPES for spec in recipe.formulas},
            {spec.id: spec for recipe in RECIPES for spec in recipe.mappings},
        )

    def _reload_selector(self) -> None:
        current = str(self._formula_selector.currentData() or "")
        self._formula_selector.blockSignals(True)
        self._formula_selector.clear()
        for item in unresolved_equation_items(self._draft):
            self._formula_selector.addItem(item.semantic_id, item.semantic_id)
        if current:
            index = self._formula_selector.findData(current)
            if index >= 0:
                self._formula_selector.setCurrentIndex(index)
        self._formula_selector.blockSignals(False)
        self._load_current(self._formula_selector.currentIndex())

    def _dependent_mapping_ids(self, formula_id: str) -> tuple[str, ...]:
        _, mapping_specs = self._recipe_specs()
        pending = {item.semantic_id for item in unresolved_mapping_items(self._draft)}
        return tuple(
            mapping_id
            for mapping_id, spec in mapping_specs.items()
            if spec.target_rule_id == formula_id and mapping_id in pending
        )

    def _load_current(self, _index: int) -> None:
        formula_id = str(self._formula_selector.currentData() or "")
        formula_specs, mapping_specs = self._recipe_specs()
        spec = formula_specs.get(formula_id)
        extracted = next(
            (equation for equation in self._draft.extracted_equations if equation.id == formula_id),
            None,
        )
        self._mappings.clear()
        for mapping_id in self._dependent_mapping_ids(formula_id):
            mapping = mapping_specs[mapping_id]
            self._mappings.addItem(f"{mapping.id} — {mapping.semantic_route}")
        pending_formulas = len(unresolved_equation_items(self._draft))
        pending_mappings = len(unresolved_mapping_items(self._draft))
        self._progress.setText(
            f"Equations/formulas: {pending_formulas} pending. Mappings: {pending_mappings} pending."
        )
        if spec is None:
            self._details.clear()
            self._accept_button.setEnabled(False)
            return
        source = (
            f"{spec.clause}; PDF page {spec.page_number}; "
            f"{spec.figure or ('table ' + spec.table if spec.table else 'clause source')}"
        )
        rendered = extracted.rendered if extracted is not None else spec.expression_shape
        raw = extracted.raw_text if extracted is not None else "recipe-defined table selection"
        applicability = extracted.applicability if extracted is not None else spec.applicability
        parse_status = extracted.parse_status if extracted is not None else "parsed"
        self._details.setPlainText(
            "\n".join(
                (
                    f"ID: {formula_id}",
                    f"Canonical expression: {rendered}",
                    f"Raw source: {raw}",
                    f"Variables: {', '.join(spec.variables) or 'none'}",
                    f"Unit: {spec.unit}",
                    f"Applicability: {applicability}",
                    f"Parse status: {parse_status}",
                    f"Source: {source}",
                )
            )
        )
        self._accept_button.setEnabled(parse_status == "parsed")

    def _accept_current(self) -> None:
        formula_id = str(self._formula_selector.currentData() or "")
        if not formula_id:
            return
        notes = self._notes_edit.text().strip()
        if not notes:
            QMessageBox.warning(
                self,
                "Review Equation and Mappings",
                "Resolution notes are required to accept this equation and mappings.",
            )
            return
        try:
            self._draft = accept_equation_mapping(
                self._draft,
                equation_ids=(formula_id,),
                mapping_ids=self._dependent_mapping_ids(formula_id),
                actor=self._actor,
                notes=notes,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Review Equation and Mappings", str(error))
            return
        self._notes_edit.clear()
        self.draft_changed.emit(self._draft)
        self._reload_selector()
