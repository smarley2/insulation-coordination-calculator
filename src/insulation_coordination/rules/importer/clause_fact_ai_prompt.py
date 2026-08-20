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
    last: a model that skims the opening paragraph still has to produce a ``Decision:`` line per
    statement, which names what the *human* should consider doing.
    """

    return "\n".join(
        (
            *_role(),
            *_route(context),
            *_evidence(context),
            *_findings(context),
            *_schema(context),
            *_task(),
            *_response_format(),
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
        (
            'A statement whose evidence reads "stale" cites a node whose text has changed since it '
            "was authored, so its reading is no longer known to match the clause quoted above."
        ),
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
                "an explicit set of the values above joined by |. These are different readings: "
                f"{SCOPE_UNRESTRICTED} says the statement places no restriction on this dimension, "
                "while naming every value says the statement names exactly those values. Never "
                "substitute one for the other."
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
    return (
        "## 5. What to do, in this order",
        "",
        (
            "1. Identify every normative statement in the evidence that belongs to this route's "
            "fact family. Do not assume one node is one statement, and ignore sentences that only "
            "scope the ones after them."
        ),
        "2. For each statement, choose its statement kind from the list in section 4.",
        "3. State which node orders the statement should cite.",
        "4. Fill every dimension of that kind, using only the values section 4 allows.",
        (
            "5. Write UNRESOLVED for any dimension the evidence does not settle, and ask one "
            "precise question per unresolved dimension."
        ),
        (
            "6. Compare your reading against the application's proposal for the same sentence, "
            "where there is one, and state every disagreement explicitly."
        ),
        (
            "7. Name any open proposal whose sentence appears to state nothing this family models, "
            "and say why -- that is the reviewer's dismissal decision to make, not yours."
        ),
        (
            "8. Check the already-authored statements for citations they appear to be missing, "
            "citations they should not carry, and dimensions inconsistent with the evidence."
        ),
        (
            "9. Finish with what still has to be authored, dismissed or re-read before the human "
            "should even consider recording completion."
        ),
        "",
    )


def _response_format() -> tuple[str, ...]:
    return (
        "## 6. Required response format",
        "",
        (
            "Answer in exactly this structure, repeating the first block once per statement you "
            "identify. Every Decision line names what the human should consider doing; it is never "
            "an instruction to the application and never an approval. If you cannot complete a "
            "section, say so inside that section rather than dropping it."
        ),
        "",
        "```",
        "## Statement <suggested index>",
        "Decision: AUTHOR | DISMISS_PROPOSAL | NEEDS_HUMAN_REVIEW",
        "Cite nodes: <ordered node numbers>",
        "Statement kind: <exact allowed value>",
        "",
        "Fields:",
        "- <field_name>: <exact allowed value | UNRESOLVED>",
        "",
        "Compared with app proposal:",
        "- AGREE | DISAGREE | NO_PROPOSAL",
        "- differences: ...",
        "",
        "Evidence summary:",
        (
            "- <short explanation referencing node numbers; do not reproduce clause text you do not "
            "need>"
        ),
        "",
        "Questions:",
        "- <only the questions needed to resolve an UNRESOLVED field>",
        "",
        "## Existing authored-fact review",
        "- statement <n>: OK | REVIEW",
        "- issue: ...",
        "",
        "## Completion assessment",
        "Recommendation: NOT_READY | APPEARS_READY_FOR_HUMAN_CONFIRMATION",
        "Still unresolved:",
        "- ...",
        "```",
        "",
        (
            "APPEARS_READY_FOR_HUMAN_CONFIRMATION means only that you found nothing outstanding. It "
            "is not approval, and it does not permit the application or anyone else to record "
            "completion on the maintainer's behalf."
        ),
    )


__all__ = [
    "ClauseFactPromptContext",
    "ClauseFactPromptFact",
    "ClauseFactPromptNode",
    "ClauseFactPromptProposal",
    "build_clause_fact_ai_prompt",
]
