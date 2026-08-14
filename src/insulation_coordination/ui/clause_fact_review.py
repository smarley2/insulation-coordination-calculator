"""Clause fact review: the reviewer reads the licensed fragment and authors typed statements.

Qt holds no review logic. Every mutation goes through ``author_clause_fact``,
``retract_clause_fact`` and ``record_fact_completion``, which record audited corrections, and
every status is read through the importer's own digest functions, so this surface agrees with
the approval gate it exists to clear. Fragment text is displayed from the private draft because
a reviewer must read the licensed clause to author a statement; it is never written anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
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
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.clause_fact_proposals import (
    PRIVATE_MATERIAL_DIRECTORY_VARIABLE,
    SCOPE_UNRESTRICTED,
    ClauseFactProposal,
    DimensionKind,
    authored_dimension,
    authored_pair_wire,
    fact_dimensions,
    fact_model,
    fact_variants,
    pair_tokens,
    pair_wire,
    proposed_fact,
    scope_tokens,
    scope_wire,
)
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    DimensionScope,
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
    supply_fact_proposal_grammars,
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    clause_fact_route_defect,
    live_evidence_sha256,
    record_fact_completion,
    retract_clause_fact,
    uncovered_clause_fact_statements,
)
from insulation_coordination.ui.page_preview import PagePreview, Region

_HEADINGS = ("route", "authored", "status", "fragment")

#: Why each action is unavailable, shown as that button's tooltip whenever it is disabled. A
#: reviewer facing a grey button must never have to guess what would enable it.
_DISABLED_REASONS = {
    "author": (
        "Choose the kind of statement and every dimension of it, and select at least one clause "
        "node it rests on."
    ),
    "use_suggested": "Select a proposed draft in the list first.",
    "retract": "Select an authored statement in the list first.",
    "duplicate": "Select an authored statement in the list first.",
}
_NO_SOURCE_REGION = (
    "Source region not available: re-extract from the licensed PDFs to see the clause's own page."
)

#: Why a route offers no draft at all. Three separate reasons, kept separate: an empty list on its
#: own reads as "this clause proposes nothing", and only the last of the three means that. The
#: grammar mapping phrasing to meaning is licensed-derived and loads from beside the licensed
#: material (amendment A1), so on a public checkout the first of the three is the normal state --
#: statements are still authored, entirely by hand.
_NO_PRIVATE_GRAMMAR = (
    "No drafts: the private clause-fact grammar is not installed, so nothing can be suggested for "
    f"any route. Set {PRIVATE_MATERIAL_DIRECTORY_VARIABLE} to the folder holding the licensed "
    "material and reopen. Every statement can still be authored by hand, which is what a draft "
    "only ever prefills."
)
_NO_GRAMMAR_FOR_ROUTE = (
    "No drafts: this route's branch authority is declared in the recipe, so its clause proposes "
    "nothing. Author any statement it states by hand."
)
_NO_STATEMENT_SENTENCES = (
    "No drafts: this fragment carries no sentence that states a branch. A sentence that only "
    "scopes the ones after it is evidence, not a statement."
)


def _completion_blocked_text(uncovered: tuple[str, ...]) -> str:
    """Why completion is unavailable, and the action that honestly makes it available.

    Named statements and a next step, never a bare grey button: the reviewer has to be able to see
    which statements the clause still carries unauthored, and that authoring them -- or re-authoring
    one statement so it cites the nodes they rest on -- is what clears this.

    What this must **not** say is "select each draft below and author a statement for it", which is
    what it did say. A grammar declares exactly one ``statement_kind``, so on a clause stating
    several kinds of reading the only draft offered for a node stating a *different* kind is of the
    wrong kind -- and authoring it would satisfy this guard, because coverage is deliberately
    variant-agnostic so that a corrected fact still covers the statement it corrects. Following the
    instruction literally therefore recorded a wrong-kind reading and cleared the block with it.

    So the instruction is to author from the *node*: choose the kind of reading that node states,
    and use a draft only where its kind is that kind. The residual gap -- that nothing offers a
    draft of the other kinds at all -- is recorded in the plan; closing it needs declarations that
    do not exist rather than a mechanism.
    """

    return (
        "Completion is blocked while this clause carries a statement no authored fact covers: "
        f"{'; '.join(uncovered)}. Author one statement per item listed, reading that item's own "
        "nodes: choose the kind of reading the node states, then its dimensions. A draft below is a "
        "prefill of one kind of reading only -- where a node states a different kind, choose that "
        "kind and fill it in yourself rather than authoring the draft. Re-authoring one statement "
        "so it cites every node it rests on clears an item too, and Record completion becomes "
        "available."
    )


#: The scope widget's explicit unrestricted row. Its own entry rather than "select every value",
#: because the two are different readings: unrestricted projects over the reviewed domain, while a
#: set of every value projects over exactly those values -- identical only where the reviewed and
#: consumer domains coincide, and a reviewer must be able to state either.
_UNRESTRICTED_ENTRY = "(unrestricted)"


def _dimension_text(kind: DimensionKind, value: object) -> str:
    """One authored dimension as the editor spells it, so a row and the editor agree.

    The inverse of ``authored_dimension``: booleans read as its own two values and a scope as its
    wire form, which is what the scope widget's selection encodes.
    """

    if kind == "boolean":
        return "true" if value else "false"
    if kind == "scope":
        return scope_wire(cast("DimensionScope[Any]", value))
    if kind == "pair_sequence":
        return authored_pair_wire(cast("Sequence[object]", value))
    return str(value)


def _statement_kind(fact: SupplyFact | ClauseFactProposal) -> str | None:
    """Which variant a statement or draft is of, or ``None`` for a one-kind family."""

    return getattr(fact, "statement_kind", "") or None


def _reading_summary(fact: SupplyFact) -> str:
    """One statement's reading, compactly, from whatever dimensions its own kind declares.

    Derived from the model's own dimension list rather than formatted per family: a hand-written
    format per family is one more place a new dimension can be forgotten, and a row that omits a
    dimension is exactly the blindness that let ten copies of one reading look distinct.

    A variant family's rows lead with the statement kind, because two kinds of one family carry
    different dimensions and a bare field list would read as two unrelated statements.
    """

    variant = _statement_kind(fact)
    reading = " · ".join(
        _dimension_text(kind, getattr(fact, name))
        for name, kind, _options in fact_dimensions(fact.fact_kind, variant)
    )
    return reading if variant is None else f"{variant} · {reading}"


#: What each authoring path writes into a fact's notes, so the audit distinguishes a statement
#: whose editor was prefilled from a suggestion from one a maintainer typed from scratch. Both
#: name the dialog; only the prefilled one names the grammar.
_HAND_AUTHORED_NOTES = "authored in the clause fact review dialog"
_FROM_PROPOSAL_NOTES = "authored from a grammar proposal in the clause fact review dialog"


class ClauseFactRouteRow(FrozenModel):
    """One rule route as the reviewer sees it."""

    rule_route: str
    fragment_id: str
    authored: int
    status: Literal["needs_facts", "needs_completion", "complete", "stale"]
    #: Why this route is not complete, straight from ``clause_fact_route_defect``, for the two
    #: statuses a reviewer cannot act on without being told: ``stale``, and the
    #: ``needs_completion`` that the completion guard is blocking. ``None`` for a
    #: ``needs_completion`` that only awaits the maintainer's own assertion -- that one names an
    #: ordinary next step, not a defect.
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
                # The one reason a route short of completion needs stated in the table: the
                # reviewer cannot record completion at all until it is cleared, so leaving it to
                # a hover would be a route that simply refuses with no visible cause.
                reason = defect if self.uncovered(route) else None
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

    def proposals_unavailable(self, rule_route: str) -> str:
        """Why this route offers no draft at all, or ``""`` when it offers some.

        The honest half of the relocation: with the grammar private, "no drafts" is the ordinary
        state of a public checkout, and an empty list alone would read as a claim about the clause.
        Asked of every draft rather than of the open ones, so a route whose drafts are all authored
        stays quiet -- that is the finished case, not an unavailable one.
        """

        if self.proposals(rule_route):
            return ""
        if not supply_fact_proposal_grammars():
            return _NO_PRIVATE_GRAMMAR
        if rule_route not in supply_fact_proposal_grammars():
            return _NO_GRAMMAR_FOR_ROUTE
        return _NO_STATEMENT_SENTENCES

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

    def uncovered(self, rule_route: str) -> tuple[str, ...]:
        """The known statements of one route no authored fact covers, for the reviewer.

        The completion guard's own list, through the same function ``record_fact_completion`` and
        the approval gate call, so this surface can never offer a completion the importer refuses
        or withhold one it would accept.
        """

        return uncovered_clause_fact_statements(self._draft, rule_route)

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


class PairSequenceEditor(QWidget):
    """One row per stated pair of a pair-collection dimension, in the order the reviewer states them.

    Repeating rows rather than two multi-selections over the vocabulary. Two independent value sets
    would fabricate a cartesian product nobody stated -- a statement permitting one transition and
    another would read as permitting every crossing of their endpoints -- which is exactly what the
    pair member model exists to refuse. Each row is one stated pair, and the row order is the
    collection's order: nothing here sorts, deduplicates or drops a row, so the value authored is the
    one on screen.

    A row starts with both members unchosen, like every other dimension, and a row still missing a
    member leaves the whole dimension unchosen: half a pair is not a reading. An empty list is not a
    choice either, so Author stays disabled until the reviewer has stated at least one whole pair.

    ponytail: add and remove, with no reordering affordance. A statement names a handful of pairs, and
    remove-and-re-add reorders one; add row moves if a clause ever states enough of them to matter.
    """

    #: Any change to the rows or their members, for the dialog's own enable/refusal refresh. One
    #: signal for the whole collection rather than per row: what the dialog reads is the collection.
    changed = Signal()

    def __init__(self, options: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options
        self._rows: list[tuple[QWidget, QComboBox, QComboBox]] = []
        self._row_layout = QVBoxLayout()
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self.add_button = QPushButton("Add pair", self)
        self.add_button.clicked.connect(self._add_button_pressed)
        # The model's own refusal of the rows as they stand, shown where the rows are rather than
        # left for the reviewer to discover by pressing Author.
        self._refusal = QLabel("", self)
        self._refusal.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._row_layout)
        layout.addWidget(self.add_button)
        layout.addWidget(self._refusal)

    @property
    def options(self) -> tuple[str, ...]:
        """The vocabulary both members of every row draw from."""

        return self._options

    @property
    def refusal_text(self) -> str:
        return self._refusal.text()

    def show_refusal(self, text: str) -> None:
        self._refusal.setText(text)

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """Every row's two members, in the reviewer's order, including any still unchosen."""

        return tuple(
            (source.currentText(), target.currentText()) for _row, source, target in self._rows
        )

    def add_pair(self, source: str = "", target: str = "") -> None:
        """Append one row, unchosen unless this is a prefill of a stated pair."""

        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        combos: list[QComboBox] = []
        for value in (source, target):
            combo = QComboBox(row)
            # Blank first, as every dimension combo is: a member the reviewer has not picked must
            # never read as the first value of the vocabulary.
            combo.addItem("")
            combo.addItems(self._options)
            combo.setCurrentText(value)
            combo.currentIndexChanged.connect(self._member_chosen)
            line.addWidget(combo)
            combos.append(combo)
        remove = QPushButton("Remove", row)
        remove.clicked.connect(lambda: self.remove_pair(self._row_index(row)))
        line.addWidget(remove)
        self._row_layout.addWidget(row)
        self._rows.append((row, combos[0], combos[1]))
        self.changed.emit()

    def remove_pair(self, index: int) -> None:
        """Drop one row, leaving the rest in the order the reviewer arranged them."""

        row, _source, _target = self._rows.pop(index)
        self._row_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.changed.emit()

    def set_pairs(self, pairs: Sequence[Sequence[str]]) -> None:
        """Show exactly these pairs in this order, replacing whatever rows are there.

        The one loading path: an authored statement, a proposed draft and the reset to unchosen all
        arrive here, so none of them can drift on how a stated collection becomes rows.
        """

        while self._rows:
            self.remove_pair(0)
        for members in pairs:
            self.add_pair(*tuple(members)[:2])

    def _row_index(self, row: QWidget) -> int:
        return next(index for index, item in enumerate(self._rows) if item[0] is row)

    def _add_button_pressed(self) -> None:
        self.add_pair()

    def _member_chosen(self) -> None:
        self.changed.emit()


class ClauseFactReviewDialog(QDialog):
    """One table of routes, a node reader, the route's authored facts, and a typed editor.

    No wizard: the reviewer sees every route at once, reads the selected route's fragment
    nodes, and authors, replaces, duplicates, retracts or completes. Below the route's authored
    statements sit its proposed drafts, one per reading the private grammar reads out of one
    clause sentence, described in ``_list_proposals`` -- and, where a route has none, the reason
    there are no drafts rather than a bare empty list. A draft's suggested values reach the editor
    only as a prefill, one draft at a time, and **no action records more than one statement**: a
    suggestion is assistance, the maintainer is the authority, and a press that certified several
    machine-derived normative facts at once would not be review. The editor's fields come
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
        self._scope_lists: dict[str, QListWidget] = {}
        self._pair_editors: dict[str, PairSequenceEditor] = {}
        self._kinds: dict[str, DimensionKind] = {}
        self._editor_kind: str | None = None
        self._variant_combo: QComboBox | None = None
        self._fixed_rows = 0
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
        # A prefill the reviewer asks for by name, beside the drafts it reads from. Selecting a
        # draft already loads it; this makes the suggestion an explicit act rather than a side
        # effect of looking at a row, and it records nothing -- Author still does that.
        self.use_suggested_button = QPushButton("Use suggested values", facts_box)
        self.use_suggested_button.setEnabled(False)
        self.use_suggested_button.clicked.connect(self.use_suggested_selected)
        facts_layout.addWidget(self.use_suggested_button)
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

    @property
    def scope_options(self) -> dict[str, tuple[str, ...]]:
        """The visible editor's vocabulary per scope dimension, without the unrestricted entry."""

        return {
            field: tuple(
                widget.item(row).text()
                for row in range(widget.count())
                if widget.item(row).text() != _UNRESTRICTED_ENTRY
            )
            for field, widget in self._scope_lists.items()
        }

    @property
    def pair_options(self) -> dict[str, tuple[str, ...]]:
        """The visible editor's vocabulary per pair-collection dimension, as its rows offer it."""

        return {field: editor.options for field, editor in self._pair_editors.items()}

    def dimension_combo(self, field: str) -> QComboBox:
        return self._combos[field]

    def dimension_edit(self, field: str) -> QLineEdit:
        return self._edits[field]

    def dimension_scope(self, field: str) -> QListWidget:
        return self._scope_lists[field]

    def dimension_pairs(self, field: str) -> PairSequenceEditor:
        return self._pair_editors[field]

    def choose_pairs(self, field: str, *pairs: Sequence[str]) -> None:
        """State one pair-collection dimension's reading as the rows the reviewer would build.

        Order is the reading, not a presentation of it, so this states the rows in the order given
        and sorts nothing: the model refuses a collection out of its declared order, and quietly
        reordering here would author a collection the reviewer never arranged.
        """

        self._pair_editors[field].set_pairs(pairs)

    def choose_scope(self, field: str, *values: str, unrestricted: bool = False) -> None:
        """Select one scope dimension's reading: named values, or the unrestricted entry.

        Selecting every value is deliberately *not* the same action as selecting unrestricted: the
        two project differently wherever the reviewed and consumer domains coincide, so the widget
        keeps them separately reachable and this helper does not translate one into the other.
        """

        widget = self._scope_lists[field]
        wanted = set(values) | ({_UNRESTRICTED_ENTRY} if unrestricted else set())
        for row in range(widget.count()):
            item = widget.item(row)
            item.setSelected(item.text() in wanted)

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
        if self._variant_unchosen():
            self._status.setText("Choose which kind of statement this is first.")
            return
        chosen = self._chosen_text()
        # Blankness is checked before any conversion: a blank boolean combo converted first
        # would read as a chosen ``false``, and an empty scope selection as an empty set.
        if not all(chosen.values()):
            self._status.setText("Choose every dimension before authoring this statement.")
            return
        values: dict[str, object] = {
            "statement_index": self.statement_index.value(),
            "node_references": citations,
            **{
                field: authored_dimension(self._kinds[field], text)
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
                fact_model(family, self._editor_variant()).model_validate(values),
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

    def use_suggested_selected(self) -> None:
        """Load one selected draft's suggested dimensions and its citation into the editor.

        A prefill and nothing else: it records no statement, and every dimension the grammar could
        not settle stays unchosen, so Author stays disabled until the reviewer reads it out of the
        sentence themselves. There is no action that authors several statements at once -- one
        explicit authoring action records exactly one statement, because one press certifying
        several machine-derived normative facts is not review.

        The same ``_load_proposal`` that selecting a draft runs, rather than a second prefill path
        beside it: two paths could disagree about which dimensions a suggestion fills.
        """

        if self._current_proposal() is None:
            self._status.setText("Select a proposed draft to load its suggested values first.")
            return
        self._load_proposal()

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
            self._set_enabled(self.use_suggested_button, False, "use_suggested")
            self.complete_button.setEnabled(False)
            self.complete_button.setToolTip("")
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
        self._list_proposals(row.rule_route)
        family = SUPPLY_FACT_FAMILY_BY_ROUTE[row.rule_route]
        if self._editor_kind != family:
            self._build_editor(family)
        # A statement starts unchosen, its kind included: authoring is writing down what was read,
        # never accepting what a widget happened to hold, and which kind of reading this is is part
        # of that. The index is the one exception: it defaults to the next free slot for this route
        # rather than starting blank, because appending a statement is the normal case and typing an
        # index is only for the sanctioned replace path.
        self._reset_statement_kind()
        self.statement_index.setValue(self._model.next_statement_index(row.rule_route))
        self._reset_dimensions(row.rule_route)
        uncovered = self._model.uncovered(row.rule_route)
        self.complete_button.setEnabled(not uncovered)
        self.complete_button.setToolTip(
            "" if not uncovered else _completion_blocked_text(uncovered)
        )
        self._set_enabled(self.use_suggested_button, False, "use_suggested")
        self._set_enabled(self.retract_button, False, "retract")
        self._set_enabled(self.duplicate_button, False, "duplicate")
        self._refresh_author_enabled()

    def _reset_statement_kind(self) -> None:
        """Put the variant chooser back to unchosen, and with it the dimensions it decides."""

        if self._variant_combo is not None:
            self._variant_combo.setCurrentIndex(0)

    def _reset_dimensions(self, rule_route: str) -> None:
        """Put every dimension back to unchosen for one route, ready to be filled in."""

        for combo in self._combos.values():
            combo.setCurrentIndex(0)
        for edit in self._edits.values():
            edit.clear()
        for scope_list in self._scope_lists.values():
            scope_list.clearSelection()
        # No row at all, which is unchosen exactly as an empty scope selection is: a pair collection
        # the reviewer has not stated must never start with a row inviting the first value of the
        # vocabulary.
        for pair_editor in self._pair_editors.values():
            pair_editor.set_pairs(())
        # ``supply_kind`` is not a reviewed choice on a route the recipe already determines it
        # for: import-time validation guarantees every such route has a declared expectation, so
        # this can look it up unconditionally rather than falling back to an editable combo.
        if "supply_kind" in self._combos:
            supply_kind_combo = self._combos["supply_kind"]
            supply_kind_combo.setCurrentText(SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE[rule_route])
            supply_kind_combo.setEnabled(False)

    def _list_proposals(self, rule_route: str) -> None:
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

        A route with no draft at all ends with an unselectable row saying why, because an empty
        list would otherwise read as a claim that the clause states nothing.
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
        unavailable = self._model.proposals_unavailable(rule_route)
        if unavailable:
            # Unselectable, so it can never be loaded as if it were a draft: both row readers
            # index by position into the authored statements and then the drafts, and neither
            # reaches past them.
            notice = QListWidgetItem(unavailable, self.facts_list)
            notice.setFlags(Qt.ItemFlag.NoItemFlags)

    def _fill_editor_from_fact(self, fact: SupplyFact) -> None:
        """Load one statement's field values and cited nodes into the editor.

        Shared by the replace path, which keeps the statement's own index, and duplicate, which
        calls this and then overwrites the index with the next free one: both editor fills go
        through the same code so they cannot drift on which fields they copy.
        """

        # The kind first: it decides which dimension widgets exist at all, and choosing it rebuilds
        # them unchosen -- so filling values before it would fill widgets about to be replaced.
        self.choose_statement_kind(_statement_kind(fact))
        self.statement_index.setValue(fact.statement_index)
        for field, combo in self._combos.items():
            combo.setCurrentText(_dimension_text(self._kinds[field], getattr(fact, field)))
        for field, edit in self._edits.items():
            edit.setText(_dimension_text(self._kinds[field], getattr(fact, field)))
        for field in self._scope_lists:
            scope: DimensionScope[str] = getattr(fact, field)
            self.choose_scope(field, *scope.values, unrestricted=scope.mode == "unrestricted")
        for field in self._pair_editors:
            # Through the same wire form the row summary and a proposal use, so a stored collection
            # becomes rows one way only.
            self.choose_pairs(field, *pair_tokens(authored_pair_wire(getattr(fact, field))))
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
        self._set_enabled(
            self.use_suggested_button, self._current_proposal() is not None, "use_suggested"
        )
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
        self.choose_statement_kind(_statement_kind(proposal))
        self._reset_dimensions(row.rule_route)
        self.statement_index.setValue(self._model.next_statement_index(row.rule_route))
        for field, value in proposal.chosen.items():
            if field in self._combos:
                self._combos[field].setCurrentText(value)
            elif field in self._edits:
                self._edits[field].setText(value)
            elif field in self._scope_lists:
                self.choose_scope(
                    field, *scope_tokens(value), unrestricted=value == SCOPE_UNRESTRICTED
                )
            elif field in self._pair_editors:
                self.choose_pairs(field, *pair_tokens(value))
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

    @property
    def statement_kind_combo(self) -> QComboBox | None:
        """The variant chooser, or ``None`` for a family that states one kind of reading."""

        return self._variant_combo

    def _editor_variant(self) -> str | None:
        return None if self._variant_combo is None else (self._variant_combo.currentText() or None)

    def _variant_unchosen(self) -> bool:
        return self._variant_combo is not None and not self._variant_combo.currentText()

    def choose_statement_kind(self, statement_kind: str | None) -> None:
        """Put the variant chooser on one statement kind, rebuilding its dimensions if it moves.

        Does nothing for a family that states one kind of reading: there is no chooser, and no
        statement kind to record.
        """

        if self._variant_combo is None or statement_kind is None:
            return
        if self._variant_combo.currentText() != statement_kind:
            self._variant_combo.setCurrentText(statement_kind)

    def _build_editor(self, fact_kind: str) -> None:
        """The head of the editor: the family, the statement kind, and the index.

        The statement-kind chooser lives here rather than among the dimension rows because
        choosing it *rebuilds* those rows: a variant carries only the dimensions its own kind of
        statement states, so switching kind is a different form, and a widget cannot safely
        destroy itself from inside its own signal.
        """

        while self._editor_form.rowCount():
            self._editor_form.removeRow(0)
        # The family is the route's declared reading, displayed rather than chosen: offering
        # a choice would let a reviewer certify a route with a kind its clause never states.
        self._family_label = QLabel(fact_kind, self._editor_box)
        self._editor_form.addRow("fact family", self._family_label)
        variants = fact_variants(fact_kind)
        self._variant_combo = None
        if variants:
            # Blank first, like every dimension: which kind of statement this is is part of the
            # reading, and the family's two kinds answer normatively different questions.
            variant_combo = QComboBox(self._editor_box)
            variant_combo.addItem("")
            variant_combo.addItems(variants)
            variant_combo.currentIndexChanged.connect(self._variant_chosen)
            self._editor_form.addRow("statement kind", variant_combo)
            self._variant_combo = variant_combo
        self.statement_index = QSpinBox(self._editor_box)
        self.statement_index.setRange(0, 9999)
        self._editor_form.addRow("statement index", self.statement_index)
        self._fixed_rows = self._editor_form.rowCount()
        self._editor_kind = fact_kind
        self._build_dimensions()

    def _variant_chosen(self) -> None:
        """Offer the chosen statement kind's own dimensions, unchosen."""

        self._build_dimensions()
        row = self._current_route_row()
        if row is not None:
            self._reset_dimensions(row.rule_route)
        self._refresh_author_enabled()

    def _build_dimensions(self) -> None:
        """One row per dimension of the selected statement kind; none until a kind is chosen."""

        while self._editor_form.rowCount() > self._fixed_rows:
            self._editor_form.removeRow(self._editor_form.rowCount() - 1)
        self._combos = {}
        self._edits = {}
        self._scope_lists = {}
        self._pair_editors = {}
        self._kinds = {}
        fact_kind = self._editor_kind
        if fact_kind is None or self._variant_unchosen():
            return
        declared = fact_dimensions(fact_kind, self._editor_variant())
        self._kinds = {name: kind for name, kind, _options in declared}
        for field, kind, options in declared:
            if kind == "pair_sequence":
                # One row per stated pair, never two independent multi-selections: see
                # ``PairSequenceEditor``. Rebuilt with the rest of the rows, so a collection stated
                # under one statement kind cannot survive into a kind that states no such dimension.
                pair_editor = PairSequenceEditor(options, self._editor_box)
                pair_editor.changed.connect(self._refresh_author_enabled)
                self._editor_form.addRow(field.replace("_", " "), pair_editor)
                self._pair_editors[field] = pair_editor
                continue
            if kind == "identifier":
                edit = QLineEdit(self._editor_box)
                edit.textChanged.connect(self._refresh_author_enabled)
                self._editor_form.addRow(field.replace("_", " "), edit)
                self._edits[field] = edit
                continue
            if kind == "scope":
                # A multi-selection over the vocabulary plus the explicit unrestricted row: a
                # statement naming several values is one statement, and nothing selected is
                # unchosen, exactly as a blank combo is.
                scope_list = QListWidget(self._editor_box)
                scope_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
                scope_list.addItem(_UNRESTRICTED_ENTRY)
                scope_list.addItems(options)
                scope_list.setMaximumHeight(
                    scope_list.sizeHintForRow(0) * (len(options) + 1) + 2 * scope_list.frameWidth()
                )
                scope_list.itemSelectionChanged.connect(self._refresh_author_enabled)
                self._editor_form.addRow(field.replace("_", " "), scope_list)
                self._scope_lists[field] = scope_list
                continue
            combo = QComboBox(self._editor_box)
            # A blank first entry, so every dimension starts unchosen: a reviewer must never
            # be able to record a reading they did not pick.
            combo.addItem("")
            combo.addItems(options)
            combo.currentIndexChanged.connect(self._refresh_author_enabled)
            self._editor_form.addRow(field.replace("_", " "), combo)
            self._combos[field] = combo

    @staticmethod
    def _set_enabled(button: QPushButton, enabled: bool, reason: str) -> None:
        """Enable a button, or disable it and say on the button itself why.

        A grey button with no explanation is what left the maintainer with no path forward. The
        tooltip is cleared when the button works, so it never states a reason that is no longer
        true.
        """

        button.setEnabled(enabled)
        button.setToolTip("" if enabled else _DISABLED_REASONS[reason])

    def _scope_text(self, field: str) -> str:
        """One scope dimension's wire value, blank while nothing is selected.

        The unrestricted row wins over any value rows selected with it. It is the wider reading, so
        honouring it can never record a narrower reading than the reviewer selected -- and the two
        are never merged, because unrestricted is not "these values" and must not become them.
        """

        selected = {item.text() for item in self._scope_lists[field].selectedItems()}
        if _UNRESTRICTED_ENTRY in selected:
            return SCOPE_UNRESTRICTED
        return scope_wire(DimensionScope[str].of(*selected)) if selected else ""

    def _pair_text(self, field: str) -> str:
        """One pair collection's wire value, blank while the reviewer has stated no whole pair.

        The same single encode point a proposal and a row summary use, over the rows in the order
        they are shown. Blank for no row -- an empty collection is not a choice -- and blank while
        any row is still missing a member, because half a pair is not a stated pair either.
        """

        pairs = self._pair_editors[field].pairs()
        if not pairs or not all(all(members) for members in pairs):
            return ""
        return pair_wire(pairs)

    def _pair_refusal(self, field: str) -> str:
        """The model's own refusal of one pair collection as the rows stand, or ``""``.

        Asked of the fact model rather than re-checked here. The refusals -- a collection out of the
        declared scale's order, one transition named twice, a pair pointing a category at itself --
        are the model's, and a second copy of them in Qt is the drift this dialog avoids everywhere
        else; this slice adds no rule of its own. Only this dimension's errors are read, so the other
        dimensions being unchosen is never reported as a problem with these rows.

        Surfaced rather than prevented, and the button is not disabled for it. The model *rejects* an
        out-of-order or duplicated collection instead of quietly sorting it, precisely so a duplicate
        the reviewer meant to notice stays visible -- so a widget that reordered or filtered rows to
        keep them acceptable would hide the very thing the refusal exists to show, and would also
        stop the rows being the collection in the order the reviewer arranged them.
        """

        text = self._pair_text(field)
        if not text or self._editor_kind is None:
            return ""
        try:
            fact_model(self._editor_kind, self._editor_variant()).model_validate(
                {field: authored_dimension(self._kinds[field], text)}
            )
        except ValidationError as error:
            refusals = [
                str(item["msg"]).removeprefix("Value error, ")
                for item in error.errors()
                if item["loc"][:1] == (field,)
            ]
            return refusals[0] if refusals else ""
        return ""

    def _refresh_pair_refusals(self) -> None:
        """Show beside each pair dimension's rows what the model would refuse them for."""

        for field, editor in self._pair_editors.items():
            refusal = self._pair_refusal(field)
            editor.show_refusal(f"Refused as it stands: {refusal}." if refusal else "")

    def _chosen_text(self) -> dict[str, str]:
        """Every editor dimension's current text, blank where the reviewer chose nothing.

        One reader for every widget kind, so the enable check and the authoring path cannot
        disagree about which dimensions are still unchosen.
        """

        values = {field: combo.currentText() for field, combo in self._combos.items()}
        values.update({field: edit.text().strip() for field, edit in self._edits.items()})
        values.update({field: self._scope_text(field) for field in self._scope_lists})
        values.update({field: self._pair_text(field) for field in self._pair_editors})
        return values

    def _unchosen_dimensions(self) -> tuple[str, ...]:
        """Which editor dimensions are still blank, in the order the editor shows them."""

        chosen = self._chosen_text()
        return tuple(field for field in self._kinds if not chosen.get(field))

    def _refresh_author_enabled(self) -> None:
        unchosen = self._unchosen_dimensions()
        self._refresh_pair_refusals()
        cited = bool(self.nodes_list.selectedItems())
        self._set_enabled(
            self.author_button,
            bool(self._kinds) and not unchosen and cited and not self._variant_unchosen(),
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
        if self._variant_unchosen():
            missing.append("no statement kind chosen")
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
    "PairSequenceEditor",
]
