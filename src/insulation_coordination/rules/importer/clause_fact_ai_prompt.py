"""One copy/paste prompt asking an external model to *advise* on a route's clause facts.

Assembled on demand from live review state and formatted here, away from Qt, so what the
reviewer copies is deterministic and testable. Nothing in this module persists anything: the
context is built, rendered to a string, shown, and dropped. The rendered prompt deliberately
carries licensed clause text, which is exactly why it may never reach a log, an audit record, a
draft field, a temp file or a committed fixture -- it exists in memory and, if the reviewer
chooses, on their clipboard.

The formatter reads its schema from ``fact_variants`` and ``fact_dimensions`` rather than from a
second hand-written copy of the vocabularies, so a dimension added to a fact model cannot be
missing from the prompt that asks a model to fill it.
"""

from __future__ import annotations

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.rules.importer.clause_fact_proposals import (
    SCOPE_UNRESTRICTED,
    DimensionKind,
    fact_dimensions,
    fact_variants,
)

#: How a pair collection is spelled on the wire, restated for the model being prompted. The
#: separators themselves live in ``clause_fact_proposals``; these are the human-readable examples,
#: kept beside the sentence that explains them.
_PAIR_EXAMPLE = "first>second,second>third"


class ClauseFactPromptNode(FrozenModel):
    """One clause node as the prompt quotes it. ``text`` is licensed; never write it out."""

    order: int
    kind: str
    text: str


class ClauseFactPromptFact(FrozenModel):
    """One already-authored statement, as a finding rather than as authority."""

    statement_index: int
    #: Empty for a family that states one kind of reading.
    statement_kind: str
    #: Dimension name to the value as the editor spells it, in the model's own field order.
    dimensions: tuple[tuple[str, str], ...]
    cited_nodes: tuple[int, ...]
    evidence: str


class ClauseFactPromptProposal(FrozenModel):
    """One grammar draft of a sentence, open or dismissed.

    ``sentence_text`` is licensed clause text for the same reason a node's is.
    """

    sentence_index: int
    sentence_text: str
    statement_kind: str
    cited_nodes: tuple[int, ...]
    chosen: tuple[tuple[str, str], ...]
    unchosen: tuple[str, ...]


class ClauseFactPromptContext(FrozenModel):
    """Everything one route's prompt is rendered from, snapshotted at the moment it is asked for.

    Immutable and inert: assembling one reads the review model and mutates nothing, and holding
    one is holding a copy that is already out of date the moment the reviewer authors anything.
    That is why the dialog builds a fresh one per press rather than caching one per route.
    """

    rule_route: str
    fragment_id: str
    fact_family: str
    status: str
    defect: str | None
    next_statement_index: int
    source_standard: str
    source_pages: tuple[int, ...]
    nodes: tuple[ClauseFactPromptNode, ...]
    facts: tuple[ClauseFactPromptFact, ...]
    open_proposals: tuple[ClauseFactPromptProposal, ...]
    dismissed_proposals: tuple[ClauseFactPromptProposal, ...]
    #: Why this route offers no draft at all, or ``""`` when it offers some.
    proposals_unavailable: str
    uncovered: tuple[str, ...]
    #: The ids a ``route_reference`` dimension may name, from the recipe's own declaration --
    #: ``fact_dimensions`` deliberately leaves that vocabulary empty because it is the recipe's
    #: question, and a model asked to invent a rule id would invent one.
    route_references: tuple[str, ...]
    #: Dimensions the route itself determines, shown as fixed context rather than as a choice.
    fixed_dimensions: tuple[tuple[str, str], ...]


def build_clause_fact_ai_prompt(context: ClauseFactPromptContext) -> str:
    """One self-contained advisory prompt for one route, for the reviewer to copy by hand.

    Ordered so the authority boundary comes first and the response format that enforces it comes
    last: a model that skims the opening paragraph still has to produce an ``Action:`` line per
    block, which names what the *human* should consider doing.
    """

    return "\n".join(
        (
            *_role(),
            *_route(context),
            *_evidence(context),
            *_findings(context),
            *_schema(context),
            *_task(),
            *_response_format(context),
        )
    )


def _role() -> tuple[str, ...]:
    return (
        "# Advisory clause-fact review",
        "",
        (
            "You are an advisory clause-fact reviewer for one route of a standards import. You "
            "produce a recommendation and nothing else. A human maintainer reads it, re-reads the "
            "clause, and is the only party who authors a fact, dismisses a sentence, or records a "
            "route complete. This application never acts on your answer; there is no path from your "
            "text into a recorded fact."
        ),
        "",
        "Follow these rules without exception.",
        "",
        (
            "- The clause evidence in section 2 is the only source of truth. Do not fill any value "
            "from remembered standard wording, from another edition, or from outside knowledge."
        ),
        (
            "- Never invent a field value. Exact-choice fields must use one of the options listed "
            "for that field and no other spelling, however equivalent another looks."
        ),
        (
            "- Where the evidence does not settle a field, write UNRESOLVED and ask one precise "
            "question that would settle it. An unresolved field is a correct answer here; a "
            "plausible guess is not."
        ),
        (
            "- One node or sentence may carry several normative statements, and one statement may "
            "rest on several nodes. Never assume one node is one statement."
        ),
        (
            "- The application's own proposals in section 3 are machine prefills from a keyword "
            "grammar. They are suggestions: routinely incomplete, and capable of being wrong about "
            "the statement kind. Judge them against the clause instead of agreeing with them."
        ),
        (
            "- A dimension is restricted only where the statement's own sentence restricts it. "
            "The unrestricted reading is the default, and it is not the weaker answer. A sentence "
            "that only scopes the ones after it states nothing of this family itself, and it "
            "narrows a statement under it only where it restricts that same dimension -- never "
            "where it restricts a neighbouring property of the same situation, however related "
            "the two feel. Before you narrow a dimension, look for another node that leans on the "
            'statement you are narrowing: a later sentence pointing back at it -- "as determined '
            'above", "taking into account X", "according to the preceding", any wording of that '
            "form -- is evidence that the statement reaches cases your narrowing would cut it off "
            "from. Where you do inherit a restriction, name that node and say what you took from "
            "it on the block's Scoping line: that inheritance is the reviewer's judgement to make "
            "and is invisible to them otherwise."
        ),
        (
            '- A dimension a proposal reports as "settled by nobody yet" is not thereby '
            "unrestricted either: that line records that the keyword grammar matched nothing, "
            f"which is a fact about the grammar and not about the clause. {SCOPE_UNRESTRICTED}, a "
            "named set and UNRESOLVED are three different answers, and the grammar's silence is "
            "evidence for none of them. UNRESOLVED is only for a dimension the evidence could "
            "settle and did not: a dimension the statement never speaks to is unrestricted, not "
            "unresolved. That holds even where the dimension's vocabulary describes something "
            "this statement's subject is not, so that no value can be right and the clause names "
            "none -- the schema has no not-applicable value, and refusing the field there strands "
            "the statement, and on a one-statement route the whole route, on a question with no "
            f"answer. Answer {SCOPE_UNRESTRICTED} and note the misfit on the Why line instead: "
            "that observation is how a vocabulary the schema is missing gets noticed, and it is "
            "never grounds to refuse the field."
        ),
        (
            "- The quoted text is extracted, so it has lost typography, list indentation, table "
            "placement and emphasis. If a reading genuinely depends on any of those, do not infer "
            "it: say so and ask the reviewer for the printed page."
        ),
        (
            '- Only the human presses "Author fact", "Record: states nothing this route models" and '
            '"Record completion". Never phrase any part of your answer as approval, as '
            "authorisation, or as an action the application should take."
        ),
        "",
    )


def _route(context: ClauseFactPromptContext) -> tuple[str, ...]:
    pages = ", ".join(str(page) for page in context.source_pages)
    return (
        "## 1. Route under review",
        "",
        f"route: {context.rule_route}",
        f"fragment: {context.fragment_id}",
        f"fact family: {context.fact_family}",
        f"route status: {context.status}",
        f"route defect: {context.defect or 'none'}",
        f"next suggested statement index: {context.next_statement_index}",
        f"source standard: {context.source_standard or 'not recorded'}",
        f"source pages: {pages or 'not recorded'}",
        "",
    )


def _evidence(context: ClauseFactPromptContext) -> tuple[str, ...]:
    lines = [
        "## 2. Clause evidence",
        "",
        (
            "Every node of this route's fragment, in reading order. Cite nodes by the order number "
            "shown here."
        ),
        "",
        (
            "A citation is an evidence binding, not a bibliography. The application digests the "
            "text of every node a statement cites and re-checks that digest against these nodes "
            "each time the route is read; the moment any cited node's text changes, the statement "
            "is marked stale and has to be read again before it counts for anything. So cite "
            "every node whose wording your reading depends on -- exactly the nodes where a later "
            "change to the wording should force that re-reading -- and no others: a node cited "
            "for context alone manufactures staleness and costs the reviewer a re-reading that "
            "gains nothing."
        ),
        "",
    ]
    for node in context.nodes:
        lines += [f"node {node.order} ({node.kind}):", node.text, ""]
    if not context.nodes:
        lines += ["(this fragment carries no node, so there is nothing to read)", ""]
    return tuple(lines)


def _dimension_lines(pairs: tuple[tuple[str, str], ...], indent: str) -> list[str]:
    return [f"{indent}{name}: {value}" for name, value in pairs]


def _proposal_lines(proposal: ClauseFactPromptProposal) -> list[str]:
    cited = ", ".join(str(order) for order in proposal.cited_nodes)
    kind = proposal.statement_kind or "not declared (one-kind family)"
    lines = [f"- sentence {proposal.sentence_index}, proposed kind {kind}, cites node(s) {cited}"]
    lines += _dimension_lines(proposal.chosen, "  settled ")
    if proposal.unchosen:
        lines.append(f"  settled by nobody yet: {', '.join(proposal.unchosen)}")
    lines.append(f"  sentence: {proposal.sentence_text}")
    return lines


def _findings(context: ClauseFactPromptContext) -> tuple[str, ...]:
    lines = [
        "## 3. What the application already knows",
        "",
        (
            "Findings, not authority. Each of these is deterministic application state and each can "
            "be incomplete, or wrong about what the clause says."
        ),
        "",
        "### Statements already authored",
        "",
    ]
    if not context.facts:
        lines.append("(none authored for this route yet)")
    for fact in context.facts:
        cited = ", ".join(str(order) for order in fact.cited_nodes)
        kind = fact.statement_kind or "one-kind family"
        lines.append(
            f"- statement {fact.statement_index}, kind {kind}, cites node(s) {cited}, "
            f"evidence {fact.evidence}"
        )
        lines += _dimension_lines(fact.dimensions, "  ")
    lines += [
        "",
        "### Open grammar proposals",
        "",
    ]
    if context.proposals_unavailable:
        lines.append(f"(no proposal at all: {context.proposals_unavailable})")
    elif not context.open_proposals:
        lines.append("(every proposal for this route has been authored from or dismissed)")
    for proposal in context.open_proposals:
        lines += _proposal_lines(proposal)
    lines += [
        "",
        "### Sentences the reviewer has already recorded as stating nothing this route models",
        "",
    ]
    if not context.dismissed_proposals:
        lines.append("(none)")
    for proposal in context.dismissed_proposals:
        lines += _proposal_lines(proposal)
    lines += [
        "",
        "### Completion guard: statements no authored fact covers",
        "",
    ]
    if not context.uncovered:
        lines.append("(none outstanding)")
    lines += [f"- {item}" for item in context.uncovered]
    lines.append("")
    return tuple(lines)


def _dimension_entry(name: str, kind: DimensionKind, options: tuple[str, ...]) -> list[str]:
    """One dimension as the prompt offers it, with the semantics its kind carries.

    A ``route_reference`` points at the one list of declared rule ids section 4 prints rather
    than repeating it: several statement kinds of one family carry such a dimension, and forty-odd
    ids restated per dimension buries the two lines that actually differ between them.
    """

    if kind == "scope":
        return [
            f"- {name} -- scope over: {', '.join(options)}",
            (
                f"    A scope is either the unrestricted reading, written {SCOPE_UNRESTRICTED}, or "
                f"an explicit set of the values above joined by |. {SCOPE_UNRESTRICTED} says the "
                "statement places no restriction on this dimension; naming every value says it "
                "names exactly those values. Never substitute one for the other."
            ),
        ]
    if kind == "pair_sequence":
        return [
            f"- {name} -- ordered sequence of pairs drawn from: {', '.join(options)}",
            (
                f"    Each row is one ordered pair written source>target, and the order of the rows "
                f"is part of the reading. Write the whole collection as {_PAIR_EXAMPLE}. Do not "
                "sort, deduplicate or reorder it."
            ),
        ]
    if kind == "route_reference":
        return [
            (
                f"- {name} -- a declared rule id: one entry of the list above, spelled exactly as "
                "it is spelled there. Never compose an id of your own."
            ),
        ]
    if kind == "identifier":
        return [
            (
                f"- {name} -- FREE TEXT, no vocabulary. If you propose a value, quote the node "
                "number and the exact phrase in the evidence that fixes it; otherwise write "
                "UNRESOLVED."
            ),
        ]
    return [f"- {name} -- exact choice; one of: {', '.join(options)}"]


def _schema(context: ClauseFactPromptContext) -> tuple[str, ...]:
    variants = fact_variants(context.fact_family)
    lines = ["## 4. The exact authoring schema", ""]
    if variants:
        lines += [
            (
                f'Family "{context.fact_family}" states {len(variants)} kinds of reading. Choose '
                "exactly one of these per statement, spelled exactly as shown, and nothing else:"
            ),
            *(f"- {variant}" for variant in variants),
            "",
        ]
    else:
        lines += [
            (
                f'Family "{context.fact_family}" states one kind of reading. There is no statement '
                "kind to choose, so omit the statement kind line from your answer entirely rather "
                "than inventing a name for it."
            ),
            "",
        ]
    if context.fixed_dimensions:
        lines += [
            (
                "Fixed by the route itself, not your choice -- state them as given if you restate "
                "them at all:"
            ),
            *_dimension_lines(context.fixed_dimensions, "- "),
            "",
        ]
    fixed = {name for name, _value in context.fixed_dimensions}
    declared = tuple(
        (name, kind, options)
        for variant in variants or (None,)
        for name, kind, options in fact_dimensions(context.fact_family, variant)
        if name not in fixed
    )
    if any(kind == "route_reference" for _name, kind, _options in declared):
        lines += [
            (
                "Rule ids a reference field may name. This is the complete list, and a field below "
                "that asks for a declared rule id takes one of these and nothing else:"
            ),
            *(f"- {item}" for item in context.route_references),
            "",
        ]
    for variant in variants or (None,):
        if variant is not None:
            lines += [f'### Statement kind "{variant}"', ""]
        for name, kind, options in fact_dimensions(context.fact_family, variant):
            if name in fixed:
                continue
            lines += _dimension_entry(name, kind, options)
        lines.append("")
    return tuple(lines)


def _task() -> tuple[str, ...]:
    """The order of reasoning, which the response format cannot impose.

    Everything said elsewhere is cut from here rather than said twice: comparing against the
    proposal field by field and naming a proposal that states nothing this family models, both
    of which the template forces; writing UNRESOLVED and asking a question per unresolved
    dimension, which the role's rules state and the template's FILL and Questions lines carry;
    and not assuming one node is one statement, which is a standing rule. What is left is the
    sequence: the clause is read into statements *before* the proposals are opened, so a
    proposal-keyed answer is still a reading of the clause and not a critique of the grammar.
    """

    return (
        "## 5. What to do, in this order",
        "",
        (
            "1. Read section 2 and identify every normative statement in it that belongs to this "
            "route's fact family, before you read the proposals in section 3."
        ),
        (
            "2. For each statement, in this order: choose its statement kind from section 4, state "
            "which node orders it cites, then fill every dimension that kind carries using only "
            "the values section 4 allows. The kind decides which dimensions exist, so it comes "
            "first."
        ),
        (
            "3. Only now read the proposals in section 3 and map your statements onto them, as "
            "section 6 lays out. Where a proposal and your reading of the clause differ, the "
            "clause decides."
        ),
        (
            "4. Check the already-authored statements for citations they appear to be missing, "
            "citations they should not carry, and dimensions inconsistent with the evidence."
        ),
        (
            "5. Finish with what still has to be authored, dismissed or re-read before the human "
            "should even consider recording completion."
        ),
        "",
    )


def _response_format(context: ClauseFactPromptContext) -> tuple[str, ...]:
    """A per-proposal answer the reviewer executes beside the dialog without interpreting it.

    Keyed on the labels section 3 already prints, and enumerated here from the same proposals, so
    a block cannot be numbered independently of the row it is about. Every value the reviewer
    might have to change is marked as kept, changed or filled instead of being described in
    prose, because the prose delta is exactly the part that had to be read twice.
    """

    lines = [
        "## 6. Required response format",
        "",
        (
            "Answer in exactly this structure and nothing else. It is written to be executed "
            "beside the application's own list of drafts, so every line is a value to select "
            "rather than a paragraph to interpret. Every Action names what the human should "
            "consider doing; none of them is an instruction to the application and none of them "
            "is an approval."
        ),
        "",
    ]
    if context.open_proposals:
        lines += [
            (
                "One block per open proposal, keyed on the label section 3 gives it and carrying "
                "the nodes it cites, in that order; then one further block per statement you find "
                "that none of them covers. Never renumber a proposal, never merge two into one "
                "block, and never leave one out."
            ),
            "",
            "Blocks to produce, in this order:",
            *(
                f"- sentence {proposal.sentence_index} (cites node "
                f"{', '.join(str(order) for order in proposal.cited_nodes)})"
                for proposal in context.open_proposals
            ),
            (
                '- then one "unproposed statement <k>" block, numbered from 1, per statement of '
                "yours none of the above covers"
            ),
            "",
        ]
    else:
        lines += [
            (
                'Section 3 lists no open proposal, so every block is an "unproposed statement '
                '<k>" block, numbered from 1, one per statement you found.'
            ),
            "",
        ]
    lines += [
        "Action is exactly one of:",
        (
            "- AUTHOR_AS_PROPOSED -- the proposal is right as it stands; the reviewer loads it and "
            "changes nothing. This is the expected answer wherever the grammar settled the "
            "statement correctly, and it is a complete one: an edit is forced by the evidence, "
            "never manufactured to show diligence."
        ),
        (
            "- AUTHOR_WITH_EDITS -- the reviewer loads it and changes the lines this block marks "
            "SET or FILL first."
        ),
        (
            "- AUTHOR_UNPROPOSED -- no proposal covers this statement; the reviewer enters every "
            "line from scratch."
        ),
        (
            "- DISMISS -- the sentence states nothing this route's fact family models, so the "
            "reviewer may consider recording that instead of authoring."
        ),
        (
            "- ASK_HUMAN -- do not act on this block at all; it turns on a question only the "
            "reviewer can settle. Any block carrying an UNRESOLVED line takes this action and no "
            "other: a statement with a field nobody has settled cannot be authored."
        ),
        "",
        (
            "Mark the statement kind, the citation and every single dimension of the chosen kind "
            "-- in section 4's order, the unchanged ones included -- with one of:"
        ),
        "- keep -- the proposal's value is right and the reviewer touches nothing.",
        "- SET -- the reviewer changes it; name the proposed value being replaced.",
        (
            '- FILL -- the proposal offered no value ("settled by nobody yet", or there is no '
            "proposal at all); the reviewer enters it."
        ),
        "",
        "```",
        "## Summary",
        "- sentence <n>: AUTHOR_AS_PROPOSED, nothing to change",
        "- sentence <n>: AUTHOR_WITH_EDITS, <count> line(s) to change or fill",
        "- sentence <n>: DISMISS, <why, at most eight words>",
        "- sentence <n>: ASK_HUMAN, <the blocking question, at most eight words>",
        "- unproposed statement <k>: AUTHOR_UNPROPOSED, <count> line(s) to fill",
        "",
        "## sentence <n>",
        "Action: <exactly one of the five>",
        "Statement kind: keep <value> | SET <value> (proposal had <value>)",
        "Cite nodes: keep <orders> | SET <orders> (proposal had <orders>)",
        "Fields:",
        "- keep <field>: <value>",
        "- SET <field>: <value> (proposal had <value>)",
        "- FILL <field>: <value | UNRESOLVED> (proposal left this open)",
        "Scoping: none | node <order> restricts <what>, carried into <field> as <value>",
        "Why: <at most two sentences, citing node numbers>",
        "Questions: none | <one per UNRESOLVED field>",
        "",
        "## unproposed statement <k>",
        "<the same lines, with Action AUTHOR_UNPROPOSED and every line marked FILL>",
        "",
        "## Authored facts",
        "- statement <n>: OK | REVIEW -- <the citation or dimension at issue, one line>",
        "",
        "## Completion",
        "Recommendation: NOT_READY | APPEARS_READY_FOR_HUMAN_CONFIRMATION",
        "Outstanding:",
        "- none | <only what the blocks above do not already say, one line each>",
        "```",
        "",
        (
            "A DISMISS block carries Action, Scoping and Why only: there is nothing to author, so "
            "field lines would be noise. An ASK_HUMAN block carries every line you can fill and "
            "puts the blocking question in Questions. Omit the statement kind line entirely for a "
            "family that states one kind of reading."
        ),
        "",
        (
            "APPEARS_READY_FOR_HUMAN_CONFIRMATION means only that you found nothing outstanding. It "
            "is not approval, and it does not permit the application or anyone else to record "
            "completion on the maintainer's behalf."
        ),
    ]
    return tuple(lines)


__all__ = [
    "ClauseFactPromptContext",
    "ClauseFactPromptFact",
    "ClauseFactPromptNode",
    "ClauseFactPromptProposal",
    "build_clause_fact_ai_prompt",
]
