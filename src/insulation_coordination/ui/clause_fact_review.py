"""Clause fact review: the reviewer reads the licensed fragment and authors typed statements.

Qt holds no review logic. Every mutation goes through ``author_clause_fact``,
``retract_clause_fact`` and ``record_fact_completion``, which record audited corrections, and
every status is read through the importer's own digest functions, so this surface agrees with
the approval gate it exists to clear. Fragment text is displayed from the private draft because
a reviewer must read the licensed clause to author a statement; it is never written anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from PySide6.QtCore import Qt
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
    QListView,
    QListWidget,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.clause_fact_proposals import (
    FACT_MODEL_BY_KIND,
    ClauseFactProposal,
    fact_dimensions,
    proposed_fact,
)
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    SupplyFact,
    same_clause_fact_reading,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
    SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE,
    propose_supply_facts,
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    clause_fact_route_defect,
    live_evidence_sha256,
    record_fact_completion,
    retract_clause_fact,
)
from insulation_coordination.ui.page_preview import PagePreview, Region

_HEADINGS = ("route", "authored", "status", "fragment")

#: Why each action is unavailable, shown as that button's tooltip whenever it is disabled. A
#: reviewer facing a grey button must never have to guess what would enable it.
_DISABLED_REASONS = {
    "author": (
        "Choose every dimension of the statement and select at least one clause node it rests on."
    ),
    "author_proposed": (
        "No draft for this route has every dimension proposed. Fill the unchosen ones in by hand "
        "and use Author fact."
    ),
    "retract": "Select an authored statement in the list first.",
    "duplicate": "Select an authored statement in the list first.",
}
_NO_SOURCE_REGION = (
    "Source region not available: re-extract from the licensed PDFs to see the clause's own page."
)


def _reading_summary(fact: SupplyFact) -> str:
    """One statement's reading, compactly, from whatever dimensions its family declares.

    Derived from the family's own dimension list rather than formatted per family: a hand-written
    format per family is one more place a new dimension can be forgotten, and a row that omits a
    dimension is exactly the blindness that let ten copies of one reading look distinct. Booleans
    read as the editor's own two values so a row and the editor beside it agree.
    """

    booleans = {
        name for name, kind, _options in fact_dimensions(fact.fact_kind) if kind == "boolean"
    }
    return " · ".join(
        ("true" if getattr(fact, name) else "false")
        if name in booleans
        else str(getattr(fact, name))
        for name, _kind, _options in fact_dimensions(fact.fact_kind)
    )


#: What each authoring path writes into a fact's notes, so the audit distinguishes a confirmed
#: proposal from a reading a maintainer typed from scratch. Both name the dialog; only the
#: proposed ones name the grammar, and the batch note also records that nothing was edited
#: between the proposal and the confirmation.
_HAND_AUTHORED_NOTES = "authored in the clause fact review dialog"
_FROM_PROPOSAL_NOTES = "authored from a grammar proposal in the clause fact review dialog"
_CONFIRMED_PROPOSAL_NOTES = (
    "confirmed a fully grammar-proposed statement in the clause fact review dialog"
)


class ClauseFactRouteRow(FrozenModel):
    """One rule route as the reviewer sees it."""

    rule_route: str
    fragment_id: str
    authored: int
    status: Literal["needs_facts", "needs_completion", "complete", "stale"]
    #: Why ``status`` is ``stale``, straight from ``clause_fact_route_defect``; ``None`` for
    #: every other status, ``needs_completion`` included -- that one names an ordinary next
    #: step, not a defect.
    defect: str | None


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

    def _fragment(self, rule_route: str) -> RawClauseFragment | None:
        return next(
            (item for item in self._draft.raw_clause_fragments if item.id == f"raw-{rule_route}"),
            None,
        )

    def source_regions(self, rule_route: str) -> tuple[str, tuple[Region, ...]]:
        """The standard, and the page regions one route's fragment was declared over.

        Exactly the reviewed segments, so the preview shows the evidence and not the unreviewed
        text around it. Empty for a fragment carrying no segment inventory -- a synthetic one --
        which the pane reports rather than filling in with a whole page nobody reviewed.
        """

        fragment = self._fragment(rule_route)
        if fragment is None:
            return "", ()
        return fragment.source.standard, tuple(
            (segment.page_number, segment.expected_bbox) for segment in fragment.segments
        )

    def routes(self) -> tuple[ClauseFactRouteRow, ...]:
        """Every declared non-legacy route whose fragment this draft carries.

        The same scope ``_clause_fact_blockers`` gates: a route in
        ``LEGACY_BRANCH_AUTHORITY_RULE_IDS`` keeps its branch authority in the recipe, and a
        route whose clause was never extracted gives the reviewer nothing to author from --
        the missing fragment is ``missing_required_content``'s finding, not this surface's.
        Status comes from ``clause_fact_route_defect``, the same predicate the gate calls, so
        a route this table calls complete is one the gate does not block; this table adds no
        digest comparison of its own. ``needs_facts`` and ``needs_completion`` are ordinary
        progress, not a defect -- everything else the predicate refuses reads as ``stale``,
        with the reason carried alongside for the reviewer.
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
            completions = tuple(
                item for item in self._draft.clause_fact_completions if item.rule_route == route
            )
            defect = clause_fact_route_defect(self._draft, route)
            status: Literal["needs_facts", "needs_completion", "complete", "stale"]
            reason: str | None = None
            if not reviews:
                status = "needs_facts"
            elif defect is None:
                status = "complete"
            elif not completions:
                status = "needs_completion"
            else:
                status = "stale"
                reason = defect
            rows.append(
                ClauseFactRouteRow(
                    rule_route=route,
                    fragment_id=fragment.id,
                    authored=len(reviews),
                    status=status,
                    defect=reason,
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

    def proposals(self, rule_route: str) -> tuple[ClauseFactProposal, ...]:
        """The route's sentence-level drafts, derived from the fragment and the recipe.

        Computed here on demand rather than stored on the draft: a review binds its evidence and
        its fact's own hash, never a proposal, so a re-extracted fragment simply re-proposes and
        re-opens nothing. A route this draft never extracted has nothing to propose from.
        """

        fragment = self._fragment(rule_route)
        return () if fragment is None else propose_supply_facts(fragment, rule_route)

    def covered_by(self, rule_route: str, proposal: ClauseFactProposal) -> int | None:
        """The authored statement already carrying this draft's reading, or ``None``.

        The same predicate ``clause_fact_defect`` refuses a duplicate with, so a draft this calls
        covered is exactly one Author would refuse -- the two cannot drift into disagreeing about
        what a duplicate is.

        Only a fully proposed draft can be covered. A draft with an unchosen dimension carries an
        incomplete reading, and an authored statement that settles more than the draft proposes is
        a *different* reading, not the same one -- so comparing on the chosen subset would call a
        draft done that nobody has finished reading. ``statement_index`` is arbitrary here because
        the predicate ignores it.
        """

        if not proposal.fully_proposed:
            return None
        candidate = proposed_fact(proposal, statement_index=0)
        return next(
            (
                row.statement_index
                for row in self.facts(rule_route)
                if same_clause_fact_reading(row.fact, candidate)
            ),
            None,
        )

    def open_proposals(self, rule_route: str) -> tuple[ClauseFactProposal, ...]:
        """The route's drafts whose reading no authored statement already carries.

        A draft the reviewer has authored is done, so it leaves the list rather than sitting there
        as an open item inviting a second copy of itself.
        """

        return tuple(
            item for item in self.proposals(rule_route) if self.covered_by(rule_route, item) is None
        )

    def next_statement_index(self, rule_route: str) -> int:
        """The first index this route's authored statements have not already used.

        One past the highest authored index, never a reused gap: a statement index a reviewer
        retracted stays retired rather than being silently handed to an unrelated later
        statement. Typing a specific index is still how a reviewer replaces one, through the
        same ``author_clause_fact`` -- this is only the editor's starting offer.
        """

        used = tuple(row.statement_index for row in self.facts(rule_route))
        return max(used, default=-1) + 1

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

    def author_proposed(self, rule_route: str, *, actor: str, notes: str) -> int:
        """Record every fully proposed draft of one route, and return how many were recorded.

        One ``author_clause_fact`` per statement, never a bulk write: each fact keeps its own
        actor, notes and audited correction, so the audit shows a human took each action rather
        than one action standing for several. A draft with any unchosen dimension is skipped --
        confirming a reading nobody has read is exactly what the unchosen state exists to
        prevent -- and the index is re-read each time so the batch appends without reusing one.

        A draft whose reading is already authored is skipped too. Without that the batch walked
        into the duplicate refusal on its first already-covered draft and died there, taking every
        later draft with it. Coverage is re-checked per draft rather than snapshotted, because a
        draft this batch has just authored can cover a later one -- two sentences of one node can
        state one reading.
        """

        recorded = 0
        for proposal in self.proposals(rule_route):
            if not proposal.fully_proposed or self.covered_by(rule_route, proposal) is not None:
                continue
            self._draft = author_clause_fact(
                self._draft,
                rule_route=rule_route,
                fact=proposed_fact(proposal, statement_index=self.next_statement_index(rule_route)),
                actor=actor,
                notes=notes,
            )
            recorded += 1
        return recorded

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
    nodes, and authors, replaces, duplicates, retracts or completes. Below the route's authored
    statements sit its proposed drafts, one per reading the recipe's grammar reads out of one
    clause sentence, described in ``_list_proposals``. The editor's fields come
    from the fact models themselves and its family is fixed by the route's declaration, so a
    statement can only be authored as the kind its clause states; a dimension the route itself
    determines, such as ``supply_kind``, is shown rather than chosen for the same reason.
    """

    def __init__(
        self,
        model: ClauseFactReviewModel,
        parent: object | None = None,
        *,
        pdf_paths: Mapping[str, Path] | None = None,
        pdf_passwords: Mapping[Path, str] | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("Review clause facts")
        self._model = model
        # Passwords stay in memory for region rendering only; they are never stored.
        self._pdf_paths = dict(pdf_paths or {})
        self._combos: dict[str, QComboBox] = {}
        self._edits: dict[str, QLineEdit] = {}
        self._booleans: set[str] = set()
        self._editor_kind: str | None = None
        self._node_rows: tuple[ClauseFactNodeRow, ...] = ()
        self._fact_rows: tuple[ClauseFactStatementRow, ...] = ()
        self._proposal_rows: tuple[ClauseFactProposal, ...] = ()

        self.table = QTableWidget(0, len(_HEADINGS), self)
        self.table.setHorizontalHeaderLabels([heading for heading in _HEADINGS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._load_route)
        header = self.table.horizontalHeader()
        # A route id and a fragment id are long and are what a reviewer picks a row by, so they
        # stretch and the two short columns size to their contents. ``ResizeToContents`` on all
        # four truncated both long ones to a few characters, which made the table unreadable.
        for column, heading in enumerate(_HEADINGS):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents
                if heading in ("authored", "status")
                else QHeaderView.ResizeMode.Stretch,
            )
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setWordWrap(True)

        nodes_box = QGroupBox("Clause nodes the statement rests on (select the cited ones)", self)
        nodes_layout = QVBoxLayout(nodes_box)
        self.nodes_list = QListWidget(nodes_box)
        self.nodes_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.nodes_list.itemSelectionChanged.connect(self._refresh_author_enabled)
        # A reviewer must read the node they are about to cite. Wrapped and un-elided, so a long
        # node grows taller rather than losing its tail; ``Adjust`` re-wraps on resize instead of
        # keeping the layout measured for whatever width existed at construction.
        self.nodes_list.setWordWrap(True)
        self.nodes_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.nodes_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.nodes_list.setMinimumHeight(220)
        nodes_layout.addWidget(self.nodes_list)

        facts_box = QGroupBox("Statements for the selected route", self)
        facts_layout = QVBoxLayout(facts_box)
        self.facts_list = QListWidget(facts_box)
        # On hover rather than as a label, so the caution never costs the drafts their space.
        self.facts_list.setToolTip(
            "Drafts are proposed one per clause sentence. Sentence count is not statement "
            "count -- author fewer, more, or differently cited statements as you read them, "
            "and check every proposed reading against the sentence beside it."
        )
        self.facts_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.facts_list.itemSelectionChanged.connect(self._load_fact)
        # A proposed draft carries the sentence it was read from, so the reviewer confirms a
        # reading against its own wording rather than against a row of tokens.
        self.facts_list.setWordWrap(True)
        self.facts_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.facts_list.setResizeMode(QListView.ResizeMode.Adjust)
        facts_layout.addWidget(self.facts_list)
        self.retract_button = QPushButton("Retract fact", facts_box)
        self.retract_button.setEnabled(False)
        self.retract_button.clicked.connect(self.retract_selected)
        facts_layout.addWidget(self.retract_button)
        self.duplicate_button = QPushButton("Duplicate as new statement", facts_box)
        self.duplicate_button.setEnabled(False)
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        facts_layout.addWidget(self.duplicate_button)

        # The clause as it is printed. A reviewer interpreting a statement needs the page it is
        # on -- the extracted text alone loses the list structure, the emphasis and the table
        # references that decide what a sentence means. Exactly the reviewed segments, so nothing
        # around them is displayed as if it were evidence.
        source_box = QGroupBox("The clause as printed (wheel to zoom, drag to pan)", self)
        source_layout = QVBoxLayout(source_box)
        self.source_preview = PagePreview(source_box)
        self.source_preview.set_passwords(dict(pdf_passwords or {}))
        self.source_preview.setMinimumWidth(260)
        source_layout.addWidget(self.source_preview)

        # A splitter rather than fixed stretches: the three panes are read in different
        # proportions depending on whether the reviewer is reading the page, the nodes or the
        # drafts, and the fixed layout left the widest content in the narrowest pane.
        panes = QSplitter(Qt.Orientation.Horizontal, self)
        panes.setChildrenCollapsible(False)
        panes.addWidget(source_box)
        panes.addWidget(nodes_box)
        panes.addWidget(facts_box)
        panes.setSizes([380, 420, 400])

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
        self.author_proposed_button = QPushButton("Author all fully proposed statements", self)
        self.author_proposed_button.setEnabled(False)
        self.author_proposed_button.clicked.connect(self.author_proposed_selected)
        self.complete_button = QPushButton("Record completion", self)
        self.complete_button.setEnabled(False)
        self.complete_button.clicked.connect(self.complete_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.author_button)
        actions.addWidget(self.author_proposed_button)
        actions.addWidget(self.complete_button)
        actions.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(panes, 1)
        layout.addWidget(self._editor_box)
        layout.addWidget(self._status)
        layout.addLayout(actions)
        self.refresh()
        # Room for every route at once plus the header, so the table does not open as a two-row
        # slit the reviewer has to scroll to find a route in.
        self.table.setMaximumHeight(self._table_height())
        self.resize(1280, 860)
        if self.table.rowCount():
            self.table.selectRow(0)

    def _table_height(self) -> int:
        """Enough for the header and every route row, without the table eating the dialog."""

        rows = sum(self.table.rowHeight(row) for row in range(self.table.rowCount()))
        return self.table.horizontalHeader().height() + rows + 2 * self.table.frameWidth()

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
            # ``defect`` is only ever set beside ``stale``, so a reviewer sees why a route is
            # not complete rather than just that it is not.
            status = row.status if row.defect is None else f"{row.status}: {row.defect}"
            for column, text in enumerate(
                (row.rule_route, str(row.authored), status, row.fragment_id)
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
        # A statement whose editor was filled from a draft is marked as such however much the
        # reviewer then changed: the reading started as a grammar proposal either way, and the
        # audit's job is to say so rather than to guess how much of it survived.
        notes = (
            _FROM_PROPOSAL_NOTES if self._current_proposal() is not None else _HAND_AUTHORED_NOTES
        )
        try:
            self._model.author(
                row.rule_route,
                FACT_MODEL_BY_KIND[family].model_validate(values),
                actor="maintainer",
                notes=notes,
            )
        except (ValidationError, ValueError) as error:
            self._status.setText(f"Fact refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._load_route()
        self._status.setText("Statement recorded for this route.")

    def author_proposed_selected(self) -> None:
        """Record every fully proposed draft of the selected route. The model owns the mutation.

        Per-statement Author stays the unit of confirmation: this is the same call, run once per
        draft, so every fact still carries an actor and notes and the audit shows a human took
        each action. What it removes is the clicking, not the gate -- which is why the drafts sit
        beside the sentences they were read from, and why a draft with any unchosen dimension is
        left for the reviewer.
        """

        position = self.table.currentRow()
        row = self._current_route_row()
        if row is None:
            self._status.setText("Select a rule route first.")
            return
        try:
            recorded = self._model.author_proposed(
                row.rule_route, actor="maintainer", notes=_CONFIRMED_PROPOSAL_NOTES
            )
        except (ValidationError, ValueError) as error:
            self._status.setText(f"Fact refused: {error}")
            return
        self.refresh()
        self.table.selectRow(position)
        self._load_route()
        self._status.setText(
            f"Recorded {recorded} confirmed proposal(s) for this route."
            if recorded
            else "No draft for this route has every dimension proposed."
        )

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

    def _current_proposal(self) -> ClauseFactProposal | None:
        """The selected proposed draft, or ``None`` when an authored statement is selected.

        The list holds the route's authored statements and then its drafts, so a position past
        the authored ones indexes into the drafts.
        """

        position = self.facts_list.currentRow() - len(self._fact_rows)
        selected = bool(self.facts_list.selectedItems())
        return (
            self._proposal_rows[position]
            if selected and 0 <= position < len(self._proposal_rows)
            else None
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
            self.source_preview.render_regions(None, (), unavailable=_NO_SOURCE_REGION)
            self._node_rows = ()
            self._fact_rows = ()
            self._proposal_rows = ()
            self._set_enabled(self.author_button, False, "author")
            self._set_enabled(self.author_proposed_button, False, "author_proposed")
            self.complete_button.setEnabled(False)
            self._set_enabled(self.retract_button, False, "retract")
            self._set_enabled(self.duplicate_button, False, "duplicate")
            return
        standard, regions = self._model.source_regions(row.rule_route)
        self.source_preview.render_regions(
            self._pdf_paths.get(standard) if regions else None,
            regions,
            unavailable=_NO_SOURCE_REGION,
        )
        self._node_rows = self._model.nodes(row.fragment_id)
        self.nodes_list.clear()
        for node in self._node_rows:
            self.nodes_list.addItem(f"{node.node_order} · {node.node_kind} · {node.raw_text}")
        self._fact_rows = self._model.facts(row.rule_route)
        self.facts_list.clear()
        for fact_row in self._fact_rows:
            # The reading itself, not just the family: rows naming only the index and the family
            # made ten copies of one statement look like ten statements.
            self.facts_list.addItem(
                f"statement {fact_row.statement_index} · {_reading_summary(fact_row.fact)}"
                f" · evidence {fact_row.evidence}"
            )
        # Only the drafts still open: an authored one is done and leaves the list, rather than
        # sitting there as an open item inviting a second copy of itself.
        self._proposal_rows = self._model.open_proposals(row.rule_route)
        self._list_proposals()
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        if self._editor_kind != family:
            self._build_editor(family)
        # A statement starts unchosen: authoring is writing down what was read, never
        # accepting what a widget happened to hold. The index is the one exception: it defaults
        # to the next free slot for this route rather than starting blank, because appending a
        # statement is the normal case and typing an index is only for the sanctioned replace path.
        self.statement_index.setValue(self._model.next_statement_index(row.rule_route))
        self._reset_dimensions(row.rule_route)
        self.complete_button.setEnabled(True)
        self._set_enabled(
            self.author_proposed_button,
            any(proposal.fully_proposed for proposal in self._proposal_rows),
            "author_proposed",
        )
        self._set_enabled(self.retract_button, False, "retract")
        self._set_enabled(self.duplicate_button, False, "duplicate")
        self._refresh_author_enabled()

    def _reset_dimensions(self, rule_route: str) -> None:
        """Put every dimension back to unchosen for one route, ready to be filled in."""

        for combo in self._combos.values():
            combo.setCurrentIndex(0)
        for edit in self._edits.values():
            edit.clear()
        # ``supply_kind`` is not a reviewed choice on a route the recipe already determines it
        # for: import-time validation guarantees every such route has a declared expectation, so
        # this can look it up unconditionally rather than falling back to an editable combo.
        if "supply_kind" in self._combos:
            supply_kind_combo = self._combos["supply_kind"]
            supply_kind_combo.setCurrentText(SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE[rule_route])
            supply_kind_combo.setEnabled(False)

    def _list_proposals(self) -> None:
        """Offer one draft per proposed reading of one clause sentence, below the authored ones.

        Authoring a statement used to be every dimension blank *and* a decision about how many
        statements to write and which node each rests on. These drafts remove the second half and
        most of the first: each carries one sentence's citation, the sentence itself to read, and
        whatever dimensions the recipe's grammar settles from that sentence.

        A sentence is the unit rather than a node because one node can carry several distinct
        normative statements, and because a node's trailing notes are not statements at all. They
        are still drafts to edit, never a reading of the source: their count says nothing about
        how many statements the clause makes, a reviewer is free to author fewer, more, or
        differently cited ones -- a statement resting on two nodes is still selected by hand --
        and nothing is recorded until an Author button is pressed.
        """

        for proposal in self._proposal_rows:
            reading = (
                "every dimension proposed"
                if proposal.fully_proposed
                else f"unchosen: {', '.join(proposal.unchosen)}"
            )
            self.facts_list.addItem(
                f"draft · sentence {proposal.sentence_index} · cites node "
                f"{proposal.node_references[0].node_order} · {reading} · "
                f"{proposal.sentence_text}"
            )

    def _fill_editor_from_fact(self, fact: SupplyFact) -> None:
        """Load one statement's field values and cited nodes into the editor.

        Shared by the replace path, which keeps the statement's own index, and duplicate, which
        calls this and then overwrites the index with the next free one: both editor fills go
        through the same code so they cannot drift on which fields they copy.
        """

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

    def _load_fact(self) -> None:
        """Pre-fill the editor from the selected entry of the list.

        An authored statement fills every field, so authoring replaces it. A proposed draft fills
        its own node, the next free index and whatever the grammar settled, and there is nothing
        to retract or duplicate, because nothing has been authored.
        """

        fact_row = self._current_fact_row()
        self._set_enabled(self.retract_button, fact_row is not None, "retract")
        self._set_enabled(self.duplicate_button, fact_row is not None, "duplicate")
        if fact_row is None:
            self._load_proposal()
            return
        self._fill_editor_from_fact(fact_row.fact)

    def _load_proposal(self) -> None:
        """Load the selected draft: its own node cited, the next free index, its proposed reading.

        A dimension the grammar did not settle stays unchosen, so Author stays disabled until the
        reviewer reads it out of the sentence themselves. Never a default and never an ``any_*``
        fallback: "this sentence does not restrict that dimension" is a reading, and "we could not
        tell" is not.
        """

        row = self._current_route_row()
        proposal = self._current_proposal()
        if row is None or proposal is None:
            return
        self._reset_dimensions(row.rule_route)
        self.statement_index.setValue(self._model.next_statement_index(row.rule_route))
        for field, value in proposal.chosen.items():
            if field in self._combos:
                self._combos[field].setCurrentText(value)
            elif field in self._edits:
                self._edits[field].setText(value)
        cited = {(item.fragment_id, item.node_order) for item in proposal.node_references}
        for position, node in enumerate(self._node_rows):
            self.nodes_list.item(position).setSelected((node.fragment_id, node.node_order) in cited)
        self._refresh_author_enabled()

    def duplicate_selected(self) -> None:
        """Load the selected statement under the next free index, for authoring a sibling.

        Statements within a clause usually differ in only one dimension, so this is a prefill of
        the editor, not a new mutation path: the reviewer changes the one field that differs and
        presses Author, which still goes through ``author_clause_fact`` like everything else.
        """

        fact_row = self._current_fact_row()
        if fact_row is None:
            self._status.setText("Select an authored statement to duplicate first.")
            return
        self._fill_editor_from_fact(fact_row.fact)
        self.statement_index.setValue(self._model.next_statement_index(fact_row.rule_route))

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
        for field, kind, options in fact_dimensions(fact_kind):
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

    @staticmethod
    def _set_enabled(button: QPushButton, enabled: bool, reason: str) -> None:
        """Enable a button, or disable it and say on the button itself why.

        A grey button with no explanation is what left the maintainer with no path forward. The
        tooltip is cleared when the button works, so it never states a reason that is no longer
        true.
        """

        button.setEnabled(enabled)
        button.setToolTip("" if enabled else _DISABLED_REASONS[reason])

    def _unchosen_dimensions(self) -> tuple[str, ...]:
        """Which editor dimensions are still blank, in the order the editor shows them."""

        return tuple(
            field
            for field in (*self._combos, *self._edits)
            if not (
                self._combos[field].currentText()
                if field in self._combos
                else self._edits[field].text().strip()
            )
        )

    def _refresh_author_enabled(self) -> None:
        unchosen = self._unchosen_dimensions()
        cited = bool(self.nodes_list.selectedItems())
        self._set_enabled(
            self.author_button,
            bool(self._combos or self._edits) and not unchosen and cited,
            "author",
        )
        self._describe_next_step(unchosen, cited)

    def _describe_next_step(self, unchosen: tuple[str, ...], cited: bool) -> None:
        """Say exactly what is missing before this statement can be authored.

        Only while a draft or statement is loaded and something is missing: an outcome message
        from a mutation must not be overwritten by a running commentary on the editor.
        """

        if self._current_proposal() is None and self._current_fact_row() is None:
            return
        missing: list[str] = []
        if unchosen:
            missing.append(f"unchosen dimension(s): {', '.join(unchosen)}")
        if not cited:
            missing.append("no clause node cited")
        self._status.setText(
            "This draft is ready: press Author fact to record it."
            if not missing
            else f"{'; '.join(missing)}. Choose them to enable Author fact."
        )


__all__ = [
    "ClauseFactNodeRow",
    "ClauseFactReviewDialog",
    "ClauseFactReviewModel",
    "ClauseFactRouteRow",
    "ClauseFactStatementRow",
]
