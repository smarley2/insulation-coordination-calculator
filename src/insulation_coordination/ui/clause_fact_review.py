"""Clause fact review: the reviewer reads the licensed fragment and authors typed statements.

Qt holds no review logic. Every mutation goes through ``author_clause_fact``,
``retract_clause_fact`` and ``record_fact_completion``, which record audited corrections, and
every status is read through the importer's own digest functions, so this surface agrees with
the approval gate it exists to clear. Fragment text is displayed from the private draft because
a reviewer must read the licensed clause to author a statement; it is never written anywhere.
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
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    CitedNode,
    HfAttenuationFact,
    PropagationStepFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SupplyFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    fact_set_sha256,
    live_evidence_sha256,
    record_fact_completion,
    retract_clause_fact,
)

_HEADINGS = ("route", "authored", "status", "fragment")

_FACT_MODELS: dict[
    str,
    type[
        SystemVoltageFact
        | PropagationStepFact
        | BarrierTransferFact
        | SpdReductionFact
        | SpdMonitoringFact
        | HfAttenuationFact
    ],
] = {
    "system_voltage": SystemVoltageFact,
    "propagation_step": PropagationStepFact,
    "barrier_transfer": BarrierTransferFact,
    "spd_reduction": SpdReductionFact,
    "spd_monitoring": SpdMonitoringFact,
    "hf_attenuation": HfAttenuationFact,
}

#: ``fact_kind`` is the family itself, fixed per route; ``statement_index`` has its own spinner;
#: ``node_references`` come from the node reader, never typed by hand.
_UNDIMENSIONED_FIELDS = frozenset({"fact_kind", "statement_index", "node_references"})

DimensionKind = Literal["choice", "boolean", "identifier"]


def _dimensions(fact_kind: str) -> tuple[tuple[str, DimensionKind, tuple[str, ...]], ...]:
    """Each authored dimension of one fact family with its widget kind and vocabulary.

    Read from the model's own annotations, so the UI never carries a hand-written copy of a
    vocabulary that could drift from the model it has to build. A boolean is a two-value
    choice starting unchosen -- a reviewer must never record a reading they did not pick, and
    a checkbox has no unchosen state. An ``Identifier`` field has no vocabulary and gets a
    line edit. Anything else is refused here rather than degrading silently: a dimension the
    editor cannot offer is a fact no reviewer can author, and approval would block on the
    route with nothing to explain why.
    """

    dimensions: list[tuple[str, DimensionKind, tuple[str, ...]]] = []
    for name, field in _FACT_MODELS[fact_kind].model_fields.items():
        if name in _UNDIMENSIONED_FIELDS:
            continue
        if field.annotation is bool:
            dimensions.append((name, "boolean", ("true", "false")))
            continue
        options = get_args(field.annotation)
        if options:
            if not all(isinstance(option, str) for option in options):
                raise RulePackageError(
                    f"{fact_kind}.{name} declares no vocabulary of strings the review "
                    "dialog could offer"
                )
            dimensions.append((name, "choice", options))
            continue
        if field.annotation is str:
            dimensions.append((name, "identifier", ()))
            continue
        raise RulePackageError(
            f"{fact_kind}.{name} declares no vocabulary of strings the review dialog could offer"
        )
    return tuple(dimensions)


class ClauseFactRouteRow(FrozenModel):
    """One rule route as the reviewer sees it."""

    rule_route: str
    fragment_id: str
    authored: int
    status: Literal["needs_facts", "needs_completion", "complete", "stale"]


class ClauseFactNodeRow(FrozenModel):
    """One fragment node the reviewer reads in order to author a statement.

    ``raw_text`` is licensed clause text shown from the private draft; it exists to be read
    here and must never be written to a committed file.
    """

    fragment_id: str
    node_order: int
    node_kind: str
    node_sha256: str
    raw_text: str


class ClauseFactStatementRow(FrozenModel):
    """One authored statement as the reviewer sees it."""

    rule_route: str
    statement_index: int
    fact: SupplyFact
    evidence: Literal["current", "stale"]


class ClauseFactReviewModel:
    """Review actions over one draft's clause fact routes."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    def routes(self) -> tuple[ClauseFactRouteRow, ...]:
        """Every declared non-legacy route whose fragment this draft carries.

        The same scope ``_clause_fact_blockers`` gates: a route in
        ``LEGACY_BRANCH_AUTHORITY_RULE_IDS`` keeps its branch authority in the recipe, and a
        route whose clause was never extracted gives the reviewer nothing to author from --
        the missing fragment is ``missing_required_content``'s finding, not this surface's.
        Status is derived through the importer's own digests, so a route this table calls
        complete is one the gate does not block.
        """

        fragments = {item.id: item for item in self._draft.raw_clause_fragments}
        rows: list[ClauseFactRouteRow] = []
        for route in SUPPLY_FACT_FAMILY_BY_ROUTE:
            fragment = fragments.get(f"raw-{route}")
            if route in LEGACY_BRANCH_AUTHORITY_RULE_IDS or fragment is None:
                continue
            reviews = tuple(
                item for item in self._draft.clause_fact_reviews if item.rule_route == route
            )
            completion = next(
                (item for item in self._draft.clause_fact_completions if item.rule_route == route),
                None,
            )
            status: Literal["needs_facts", "needs_completion", "complete", "stale"]
            if not reviews:
                status = "needs_facts"
            elif completion is None:
                status = "needs_completion"
            elif completion.fragment_sha256 != fragment.raw_sha256 or (
                completion.fact_set_sha256 != fact_set_sha256(tuple(item.fact for item in reviews))
            ):
                status = "stale"
            else:
                status = "complete"
            rows.append(
                ClauseFactRouteRow(
                    rule_route=route,
                    fragment_id=fragment.id,
                    authored=len(reviews),
                    status=status,
                )
            )
        return tuple(rows)

    def nodes(self, fragment_id: str) -> tuple[ClauseFactNodeRow, ...]:
        """The fragment's nodes with their live content hashes, so a citation is exact."""

        fragment = next(
            (item for item in self._draft.raw_clause_fragments if item.id == fragment_id), None
        )
        if fragment is None:
            return ()
        return tuple(
            ClauseFactNodeRow(
                fragment_id=fragment.id,
                node_order=node.order,
                node_kind=node.kind,
                node_sha256=canonical_model_sha256(node),
                raw_text=node.raw_text,
            )
            for node in fragment.nodes
        )

    def facts(self, rule_route: str) -> tuple[ClauseFactStatementRow, ...]:
        """The route's authored statements, each checked against the draft's live nodes."""

        reviews = sorted(
            (item for item in self._draft.clause_fact_reviews if item.rule_route == rule_route),
            key=lambda item: item.statement_index,
        )
        return tuple(
            ClauseFactStatementRow(
                rule_route=rule_route,
                statement_index=review.statement_index,
                fact=review.fact,
                evidence=(
                    "current"
                    if review.evidence_sha256
                    == live_evidence_sha256(self._draft, review.fact.node_references)
                    else "stale"
                ),
            )
            for review in reviews
        )

    def author(
        self,
        rule_route: str,
        fact: SupplyFact,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = author_clause_fact(
            self._draft, rule_route=rule_route, fact=fact, actor=actor, notes=notes
        )
        return self._draft

    def retract(
        self,
        rule_route: str,
        statement_index: int,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = retract_clause_fact(
            self._draft,
            rule_route=rule_route,
            statement_index=statement_index,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def complete(
        self,
        rule_route: str,
        fragment_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = record_fact_completion(
            self._draft,
            rule_route=rule_route,
            fragment_id=fragment_id,
            actor=actor,
            notes=notes,
        )
        return self._draft


class ClauseFactReviewDialog(QDialog):
    """One table of routes, a node reader, the route's authored facts, and a typed editor.

    No wizard: the reviewer sees every route at once, reads the selected route's fragment
    nodes, and authors, replaces, retracts or completes. The editor's fields come from the
    fact models themselves and its family is fixed by the route's declaration, so a statement
    can only be authored as the kind its clause states.
    """

    def __init__(self, model: ClauseFactReviewModel, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Review clause facts")
        self._model = model
        self._combos: dict[str, QComboBox] = {}
        self._edits: dict[str, QLineEdit] = {}
        self._booleans: set[str] = set()
        self._editor_kind: str | None = None
        self._node_rows: tuple[ClauseFactNodeRow, ...] = ()
        self._fact_rows: tuple[ClauseFactStatementRow, ...] = ()

        self.table = QTableWidget(0, len(_HEADINGS), self)
        self.table.setHorizontalHeaderLabels([heading for heading in _HEADINGS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._load_route)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        nodes_box = QGroupBox("Clause nodes the statement rests on (select the cited ones)", self)
        nodes_layout = QVBoxLayout(nodes_box)
        self.nodes_list = QListWidget(nodes_box)
        self.nodes_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.nodes_list.itemSelectionChanged.connect(self._refresh_author_enabled)
        nodes_layout.addWidget(self.nodes_list)

        facts_box = QGroupBox("Authored statements for the selected route", self)
        facts_layout = QVBoxLayout(facts_box)
        self.facts_list = QListWidget(facts_box)
        self.facts_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.facts_list.itemSelectionChanged.connect(self._load_fact)
        facts_layout.addWidget(self.facts_list)
        self.retract_button = QPushButton("Retract fact", facts_box)
        self.retract_button.setEnabled(False)
        self.retract_button.clicked.connect(self.retract_selected)
        facts_layout.addWidget(self.retract_button)

        panes = QHBoxLayout()
        panes.addWidget(nodes_box, 1)
        panes.addWidget(facts_box, 1)

        self._editor_box = QGroupBox("Statement for the selected route", self)
        self._editor_form = QFormLayout(self._editor_box)
        # Unparented placeholders, replaced by ``_build_editor`` when a route is selected:
        # parenting them to the editor box before then would paint them outside the form.
        self._family_label = QLabel("")
        self.statement_index = QSpinBox()
        self.statement_index.setRange(0, 9999)

        self._status = QLabel(self)
        self._status.setWordWrap(True)

        self.author_button = QPushButton("Author fact", self)
        # Nothing is selected yet, and a draft with no supply routes never selects a row, so
        # ``_load_route`` would never run to disable these.
        self.author_button.setEnabled(False)
        self.author_button.clicked.connect(self.author_selected)
        self.complete_button = QPushButton("Record completion", self)
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self.complete_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.author_button)
        actions.addWidget(self.complete_button)
        actions.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(panes)
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
    def family_text(self) -> str:
        """The fixed fact family displayed for the selected route -- display, not choice."""

        return self._family_label.text()

    @property
    def dimension_options(self) -> dict[str, tuple[str, ...]]:
        """The visible editor's vocabulary per combo dimension, without the blank placeholder."""

        return {
            field: tuple(
                combo.itemText(item) for item in range(combo.count()) if combo.itemText(item)
            )
            for field, combo in self._combos.items()
        }

    def dimension_combo(self, field: str) -> QComboBox:
        return self._combos[field]

    def dimension_edit(self, field: str) -> QLineEdit:
        return self._edits[field]

    def refresh(self) -> None:
        rows = self._model.routes()
        self.table.setRowCount(len(rows))
        for position, row in enumerate(rows):
            for column, text in enumerate(
                (row.rule_route, str(row.authored), row.status, row.fragment_id)
            ):
                self.table.setItem(position, column, QTableWidgetItem(text))

    def author_selected(self) -> None:
        """Record the visible statement for the selected route. The model owns the mutation."""

        position = self.table.currentRow()
        row = self._current_route_row()
        if row is None:
            self._status.setText("Select a rule route first.")
            return
        citations = tuple(
            CitedNode(
                fragment_id=node.fragment_id,
                node_order=node.node_order,
                node_sha256=node.node_sha256,
            )
            for node in self._selected_nodes()
        )
        if not citations:
            self._status.setText("Select the node(s) the statement rests on first.")
            return
        chosen = {field: combo.currentText() for field, combo in self._combos.items()}
        chosen.update({field: edit.text().strip() for field, edit in self._edits.items()})
        # Blankness is checked before any conversion: a blank boolean combo converted first
        # would read as a chosen ``false``.
        if not all(chosen.values()):
            self._status.setText("Choose every dimension before authoring this statement.")
            return
        values: dict[str, object] = {
            "statement_index": self.statement_index.value(),
            "node_references": citations,
            **{
                field: (text == "true") if field in self._booleans else text
                for field, text in chosen.items()
            },
        }
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        try:
            self._model.author(
                row.rule_route,
                _FACT_MODELS[family].model_validate(values),
                actor="maintainer",
                notes="authored in the clause fact review dialog",
            )
        except (ValidationError, ValueError) as error:
            self._status.setText(f"Fact refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._load_route()
        self._status.setText("Statement recorded for this route.")

    def retract_selected(self) -> None:
        """Remove the selected authored statement. The model owns the mutation."""

        position = self.table.currentRow()
        row = self._current_route_row()
        fact_row = self._current_fact_row()
        if row is None or fact_row is None:
            self._status.setText("Select an authored statement first.")
            return
        try:
            self._model.retract(
                row.rule_route,
                fact_row.statement_index,
                actor="maintainer",
                notes="retracted in the clause fact review dialog",
            )
        except (ValidationError, ValueError) as error:
            self._status.setText(f"Retraction refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._load_route()
        self._status.setText("Statement retracted for this route.")

    def complete_selected(self) -> None:
        """Assert the selected route's fact set is complete. The model owns the mutation."""

        position = self.table.currentRow()
        row = self._current_route_row()
        if row is None:
            self._status.setText("Select a rule route first.")
            return
        try:
            self._model.complete(
                row.rule_route,
                row.fragment_id,
                actor="maintainer",
                notes="completion recorded in the clause fact review dialog",
            )
        except (ValidationError, ValueError) as error:
            self._status.setText(f"Completion refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._load_route()
        self._status.setText("Completion recorded for this route.")

    def _current_route_row(self) -> ClauseFactRouteRow | None:
        rows = self._model.routes()
        position = self.table.currentRow()
        return rows[position] if 0 <= position < len(rows) else None

    def _current_fact_row(self) -> ClauseFactStatementRow | None:
        position = self.facts_list.currentRow()
        selected = bool(self.facts_list.selectedItems())
        return (
            self._fact_rows[position] if selected and 0 <= position < len(self._fact_rows) else None
        )

    def _selected_nodes(self) -> tuple[ClauseFactNodeRow, ...]:
        return tuple(
            self._node_rows[self.nodes_list.row(item)] for item in self.nodes_list.selectedItems()
        )

    def _load_route(self) -> None:
        """Show the selected route's nodes and facts, and offer its declared family's editor."""

        row = self._current_route_row()
        if row is None:
            self.nodes_list.clear()
            self.facts_list.clear()
            self._node_rows = ()
            self._fact_rows = ()
            self.author_button.setEnabled(False)
            self.complete_button.setEnabled(False)
            self.retract_button.setEnabled(False)
            return
        self._node_rows = self._model.nodes(row.fragment_id)
        self.nodes_list.clear()
        for node in self._node_rows:
            self.nodes_list.addItem(f"{node.node_order} · {node.node_kind} · {node.raw_text}")
        self._fact_rows = self._model.facts(row.rule_route)
        self.facts_list.clear()
        for fact_row in self._fact_rows:
            self.facts_list.addItem(
                f"statement {fact_row.statement_index} · {fact_row.fact.fact_kind}"
                f" · evidence {fact_row.evidence}"
            )
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        if self._editor_kind != family:
            self._build_editor(family)
        # A statement starts unchosen: authoring is writing down what was read, never
        # accepting what a widget happened to hold.
        self.statement_index.setValue(0)
        for combo in self._combos.values():
            combo.setCurrentIndex(0)
        for edit in self._edits.values():
            edit.clear()
        self.complete_button.setEnabled(True)
        self.retract_button.setEnabled(False)
        self._refresh_author_enabled()

    def _load_fact(self) -> None:
        """Pre-fill the editor with the selected statement, so authoring replaces it."""

        fact_row = self._current_fact_row()
        self.retract_button.setEnabled(fact_row is not None)
        if fact_row is None:
            return
        fact = fact_row.fact
        self.statement_index.setValue(fact.statement_index)
        for field, combo in self._combos.items():
            value = getattr(fact, field)
            if field in self._booleans:
                combo.setCurrentText("true" if value else "false")
            else:
                combo.setCurrentText(value)
        for field, edit in self._edits.items():
            edit.setText(getattr(fact, field))
        cited = {(item.fragment_id, item.node_order) for item in fact.node_references}
        for position, node in enumerate(self._node_rows):
            item = self.nodes_list.item(position)
            item.setSelected((node.fragment_id, node.node_order) in cited)
        self._refresh_author_enabled()

    def _build_editor(self, fact_kind: str) -> None:
        while self._editor_form.rowCount():
            self._editor_form.removeRow(0)
        self._combos = {}
        self._edits = {}
        self._booleans = set()
        # The family is the route's declared reading, displayed rather than chosen: offering
        # a choice would let a reviewer certify a route with a kind its clause never states.
        self._family_label = QLabel(fact_kind, self._editor_box)
        self._editor_form.addRow("fact family", self._family_label)
        self.statement_index = QSpinBox(self._editor_box)
        self.statement_index.setRange(0, 9999)
        self._editor_form.addRow("statement index", self.statement_index)
        for field, kind, options in _dimensions(fact_kind):
            if kind == "identifier":
                edit = QLineEdit(self._editor_box)
                edit.textChanged.connect(self._refresh_author_enabled)
                self._editor_form.addRow(field.replace("_", " "), edit)
                self._edits[field] = edit
                continue
            combo = QComboBox(self._editor_box)
            # A blank first entry, so every dimension starts unchosen: a reviewer must never
            # be able to record a reading they did not pick.
            combo.addItem("")
            combo.addItems(options)
            combo.currentIndexChanged.connect(self._refresh_author_enabled)
            self._editor_form.addRow(field.replace("_", " "), combo)
            self._combos[field] = combo
            if kind == "boolean":
                self._booleans.add(field)
        self._editor_kind = fact_kind

    def _refresh_author_enabled(self) -> None:
        self.author_button.setEnabled(
            bool(self._combos or self._edits)
            and all(combo.currentText() for combo in self._combos.values())
            and all(edit.text().strip() for edit in self._edits.values())
            and bool(self.nodes_list.selectedItems())
        )


__all__ = [
    "ClauseFactNodeRow",
    "ClauseFactReviewDialog",
    "ClauseFactReviewModel",
    "ClauseFactRouteRow",
    "ClauseFactStatementRow",
]
