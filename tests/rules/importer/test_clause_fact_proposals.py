"""Sentence-level clause fact proposals. Invented sentences only; no IEC content.

Every sentence below is written for this file out of the neutral terms a declared rule names.
None of them is a clause's wording, and no test here states how many statements any real clause
makes or which of its nodes states what.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import RulePackageError, SourceReference
from insulation_coordination.rules.importer.clause_fact_proposals import (
    SCOPE_UNRESTRICTED,
    ClauseFactGrammar,
    ClauseFactProposal,
    ClauseKeywordRule,
    ClauseSequenceRule,
    clause_sentences,
    fact_dimensions,
    fact_variants,
    keyword_proposer,
    pair_tokens,
    propose_clause_facts,
    proposed_fact,
    scope_from_wire,
    scope_wire,
)
from insulation_coordination.rules.importer.clause_facts import DimensionScope
from insulation_coordination.rules.importer.clauses import ClauseNode, RawClauseFragment
from insulation_coordination.rules.importer.extract import canonical_model_sha256

SOURCE = SourceReference(
    document_id="synthetic-proposals",
    standard="SYNTHETIC",
    edition="1",
    page=7,
    clause="7.7.7",
)

ROUTE = "synthetic.proposals.route"


def fragment_with_sentences(semantic_id: str, texts: tuple[str, ...]) -> RawClauseFragment:
    """A synthetic fragment carrying one node per given invented text."""

    nodes = tuple(
        ClauseNode(
            order=order,
            kind="paragraph",
            raw_text=text,
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order, text in enumerate(texts)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}", raw_sha256="0" * 64, nodes=nodes, tokens=(), source=SOURCE
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def scope_of(wire: str) -> DimensionScope[str]:
    """One synthetic statement's scope, from the wire form the editor and a proposal both spell.

    Shared by every test module that builds a fact by hand, so those helpers keep taking one string
    per dimension: ``"*"`` is the unrestricted reading and ``"a|b"`` a set. Parametrized with ``str``
    and re-validated by the field it is assigned to, which is what refuses a token the family never
    declared.
    """

    return DimensionScope[str].model_validate(scope_from_wire(wire))


def _keyword(dimension: str, value: str, *keywords: str, without: tuple[str, ...] = ()):
    return ClauseKeywordRule(
        dimension=dimension, value=value, keywords=keywords, excluded_keywords=without
    )


#: A grammar over the attenuation family, built from that family's own vocabulary and from terms
#: invented for this file.
#:
#: Kept in the public tree after amendment A1 moved the *recipe's* grammar out, on this line: every
#: keyword below either spells a token the public typed vocabulary already declares (``dvc_as`` reads
#: "DVC As"; ``test``, ``simulation`` and ``calculation`` are their own spellings) or is the
#: ISO/IEC drafting convention for modality, which no one standard owns. None of it says anything
#: about a licensed document that the models here do not already say, and the sentences it is
#: matched against are written for this file. What moved was every term the typed vocabulary does
#: *not* spell -- and the exclusion lists, which are where a reading of one clause's actual wording
#: lived.
_GRAMMAR = ClauseFactGrammar(
    fact_kind="hf_attenuation",
    keyword_rules=(
        _keyword("obligation", "requirement", "shall"),
        _keyword("obligation", "permission", "may"),
        _keyword("dvc_gate", "dvc_as", "DVC", "As"),
        _keyword("dvc_gate", "dvc_b", "DVC", "B"),
        # The unrestricted reading of a scope dimension, spelled in the scope's own wire form: a
        # sentence naming every route it accepts restricts the dimension to nothing.
        _keyword("evidence_kind", SCOPE_UNRESTRICTED, "test", "simulation", "calculation"),
        _keyword("comparison_required", "true", "shall", "shown"),
    ),
    constants={"threshold_reference": "synthetic.threshold.route"},
)


def _propose(texts: tuple[str, ...]):
    return propose_clause_facts(
        fragment_with_sentences(ROUTE, texts),
        rule_route=ROUTE,
        fact_kind="hf_attenuation",
        propose=keyword_proposer(_GRAMMAR),
    )


# --- sentence boundaries --------------------------------------------------------------


def test_one_node_carrying_several_sentences_yields_a_draft_for_each() -> None:
    """The shape the per-node seeding got wrong: one node can carry several statements."""

    proposals = _propose(("Synthetic first reading. Synthetic second reading.",))

    assert [item.sentence_index for item in proposals] == [0, 1]
    assert [item.sentence_text for item in proposals] == [
        "Synthetic first reading.",
        "Synthetic second reading.",
    ]
    # Both rest on the same node, so both cite it.
    assert {item.node_references[0].node_order for item in proposals} == {0}


def test_a_note_and_everything_after_it_is_skipped() -> None:
    """A ``NOTE`` prefix is a structural marker, not source phrasing.

    Without this the note's own text both extends the sentence it follows past its end -- a
    sentence ending in a semicolon does not end at all for a period-based splitter -- and
    proposes readings of its own that nobody stated.
    """

    node_text = (
        "Synthetic DVC As reading; may apply. "
        "NOTE 1 Synthetic aside naming DVC B and shall be shown. "
        "NOTE 2 Synthetic second aside."
    )

    proposals = _propose((node_text,))

    assert [item.sentence_text for item in proposals] == ["Synthetic DVC As reading; may apply."]
    assert proposals[0].chosen["dvc_gate"] == "dvc_as"
    assert proposals[0].chosen["obligation"] == "permission"
    assert "comparison_required" in proposals[0].unchosen


@pytest.mark.parametrize(
    "text",
    (
        # An abbreviation followed by a closing bracket, and one followed by a lower-case word.
        "Synthetic reading over items (one, two, etc.), which continues here.",
        "Synthetic reading over items, etc. and continuing in the same sentence.",
        # A clause identifier: its periods are followed by digits, never by a new sentence.
        "Synthetic reading according to 5.2.3.15 and nothing further.",
        # A quantity ending a clause reference mid-sentence.
        "Synthetic reading of value 1.5 stated once.",
    ),
)
def test_a_mid_sentence_period_does_not_split_a_statement(text: str) -> None:
    """One split statement is two half-readings, each missing what the other carries."""

    sentences = clause_sentences(fragment_with_sentences(ROUTE, (text,)))

    assert [item.text for item in sentences] == [text]


def test_a_sentence_naming_several_clause_references_is_emitted_once() -> None:
    """Regression for a duplicated draft row that was blamed on the splitter and is not its fault.

    A row appeared twice for one clause sentence, and a decimal clause reference splitting the
    sentence in two was the obvious suspect. It is not: a sentence carrying several of them is one
    sentence, emitted once. The duplication is a *fact model* defect -- a dimension whose source
    states a disjunction is forced into a scalar, so the proposer expands one statement into one
    draft per value -- and the fix is the schema work, not the splitter.

    This pins the half that is correct, so a later splitter change cannot silently reintroduce the
    symptom the diagnosis has already cleared.
    """

    text = "Synthetic reading through one route in 5.2.1 or another according to 5.2.3.15."

    sentences = clause_sentences(fragment_with_sentences(ROUTE, (text,)))

    assert [item.text for item in sentences] == [text]


def test_no_fragment_emits_one_sentence_twice() -> None:
    """A sentence emitted twice would cite one node twice and read as two statements."""

    fragment = fragment_with_sentences(
        ROUTE,
        (
            "Synthetic first reading in 5.2.1. Synthetic second reading in 5.2.3.15.",
            "Synthetic third reading, according to 5.2.1 or 5.2.3.15 as appropriate.",
        ),
    )

    texts = [item.text for item in clause_sentences(fragment)]

    assert len(texts) == len(set(texts)) == 3
    assert [item.index for item in clause_sentences(fragment)] == [0, 1, 2]


def test_a_sentence_ending_before_a_capital_does_split() -> None:
    """The other half of the same rule: a real boundary must still be found."""

    sentences = clause_sentences(fragment_with_sentences(ROUTE, ("Ends at 1.5 kHz. Starts here.",)))

    assert [item.text for item in sentences] == ["Ends at 1.5 kHz.", "Starts here."]


def test_sentences_are_numbered_across_the_whole_fragment() -> None:
    """A draft names the sentence it came from, so the numbering cannot restart per node."""

    sentences = clause_sentences(
        fragment_with_sentences(ROUTE, ("Synthetic one. Synthetic two.", "Synthetic three."))
    )

    assert [(item.index, item.node_order) for item in sentences] == [(0, 0), (1, 0), (2, 1)]


# --- expansion ------------------------------------------------------------------------


def test_a_sentence_restricting_a_scope_dimension_to_several_values_yields_one_draft() -> None:
    """The duplicate-draft defect, fixed at its cause: one statement is one draft.

    A scope dimension carries the set the sentence names, so a sentence naming two designations
    proposes one reading over both. Expanding it into one draft per value showed a reviewer two
    drafts for one statement and, once authored, recorded one reading twice.
    """

    proposals = _propose(("Synthetic gate naming DVC As and DVC B, which shall be shown.",))

    assert [item.chosen["dvc_gate"] for item in proposals] == ["dvc_as|dvc_b"]
    assert {item.sentence_index for item in proposals} == {0}


def test_a_scalar_dimension_naming_several_values_still_yields_a_draft_per_value() -> None:
    """The other half: a scalar field cannot carry a set, so its values still multiply.

    The scope dimension unions in the same sentence, so this also pins that the two behaviours
    coexist rather than one replacing the other. ``obligation`` is the scalar because it is what a
    scalar dimension is *for*: a statement is a requirement or a permission, never both, so a
    sentence carrying both modalities is two candidate readings rather than one over a set.
    """

    fragment = fragment_with_sentences(
        ROUTE, ("Synthetic DVC As and DVC B gate shall be shown, and may be relied on.",)
    )

    proposals = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="hf_attenuation",
        propose=keyword_proposer(_GRAMMAR),
    )

    assert {(item.chosen["dvc_gate"], item.chosen["obligation"]) for item in proposals} == {
        ("dvc_as|dvc_b", "requirement"),
        ("dvc_as|dvc_b", "permission"),
    }


def test_a_rule_may_declare_a_scopes_unrestricted_reading() -> None:
    """The reading that used to need an ``any_*`` member invented inside the vocabulary.

    A statement restricting a dimension to nothing is a reading, and it is one a declared rule has
    to be able to reach: without it, an unrestricted reading is prefilled as nothing at all and the
    reviewer states it by hand on every sentence that makes it. Spelled in the scope's own wire form
    rather than as a fake vocabulary member, so the fact model's own vocabulary stays exactly the
    values a statement can name.

    The unrestricted reading wins where a concrete value fires beside it: it is the wider one, so
    honouring it can never propose something narrower than the declarations matched.
    """

    grammar = _GRAMMAR.model_copy(
        update={"keyword_rules": (*_GRAMMAR.keyword_rules, _keyword("dvc_gate", "*", "either"))}
    )
    fragment = fragment_with_sentences(
        ROUTE, ("Synthetic reading for either gate. Synthetic DVC As reading for either gate.",)
    )

    unrestricted, alongside = propose_clause_facts(
        fragment, rule_route=ROUTE, fact_kind="hf_attenuation", propose=keyword_proposer(grammar)
    )

    assert unrestricted.chosen["dvc_gate"] == SCOPE_UNRESTRICTED
    assert alongside.chosen["dvc_gate"] == SCOPE_UNRESTRICTED


def test_a_scalar_dimension_may_not_declare_the_unrestricted_reading() -> None:
    """It is the scope's own wire form, not a value: on a scalar it would author that literal."""

    with pytest.raises(ValidationError, match="no value"):
        ClauseFactGrammar(
            fact_kind="hf_attenuation", keyword_rules=(_keyword("obligation", "*", "synthetic"),)
        )


def test_a_sentence_naming_several_earthing_arrangements_yields_one_draft() -> None:
    """The duplicate-draft defect, on the last family that was still multiplying.

    Two sentences of the mains system voltage clause each name three earthing arrangements. While
    ``earthing`` was a scalar with an ``any_*`` token the proposer had no choice but to multiply
    them: three drafts per sentence, differing in nothing a reviewer could see, and three statements
    of one reading if they were authored. As a scope it is one draft naming an exact set.

    The designations are the ordinary system-earthing arrangement designations, which the fact
    model's own vocabulary already spells; the sentence is written for this test.
    """

    grammar = ClauseFactGrammar(
        fact_kind="system_voltage",
        statement_kind="measure",
        keyword_rules=(
            _keyword("earthing", "tn", "TN"),
            _keyword("earthing", "tt", "TT"),
            _keyword("earthing", "it", "IT"),
        ),
    )
    fragment = fragment_with_sentences(
        ROUTE, ("Synthetic reading for TN, TT and IT arrangements alike.",)
    )

    proposals = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="system_voltage",
        statement_kind="measure",
        propose=keyword_proposer(grammar),
    )

    assert [item.chosen["earthing"] for item in proposals] == ["it|tn|tt"]


def test_two_rules_naming_one_value_propose_it_once() -> None:
    """Alternative wordings of one reading are one draft, not one per wording."""

    grammar = _GRAMMAR.model_copy(
        update={
            "keyword_rules": (
                *_GRAMMAR.keyword_rules,
                _keyword("dvc_gate", "dvc_as", "As"),
            )
        }
    )
    fragment = fragment_with_sentences(ROUTE, ("Synthetic DVC As gate.",))

    proposals = propose_clause_facts(
        fragment, rule_route=ROUTE, fact_kind="hf_attenuation", propose=keyword_proposer(grammar)
    )

    assert [item.chosen["dvc_gate"] for item in proposals] == ["dvc_as"]


def _step_grammar(
    *tokens: tuple[str, str],
    keywords: tuple[str, ...] = (),
    settle_the_rest: bool = False,
) -> ClauseFactGrammar:
    """A grammar over the reduction permission's pair collection.

    ``settle_the_rest`` adds the variant's other dimensions, so a step sentence can be a *fully*
    proposed draft -- which is the only kind anything builds a candidate statement from. The supply
    kind is a constant here because the route determines it; the real proposer locks it per route.
    """

    return ClauseFactGrammar(
        fact_kind="spd_reduction",
        statement_kind="permission",
        keyword_rules=(
            (
                _keyword("obligation", "permission", "may"),
                _keyword("insulation_classes", "basic", "basic"),
            )
            if settle_the_rest
            else ()
        ),
        constants={"supply_kind": "mains"} if settle_the_rest else {},
        sequence_rules=(
            ClauseSequenceRule(tokens=tokens, dimension="permitted_steps", keywords=keywords),
        ),
    )


def _propose_steps(grammar: ClauseFactGrammar, sentence: str) -> tuple[ClauseFactProposal, ...]:
    return propose_clause_facts(
        fragment_with_sentences(ROUTE, (sentence,)),
        rule_route=ROUTE,
        fact_kind="spd_reduction",
        statement_kind="permission",
        propose=keyword_proposer(grammar),
    )


def test_a_sequence_rule_states_every_pair_it_finds_as_one_reading() -> None:
    """Which value is the step's start and which its end is order, not wording.

    And a sentence naming several steps is **one** statement naming all of them, not one per step:
    two independent value sets, or one draft per pair, would read as a cartesian product of the
    endpoints and would author several statements where the reviewer read one.

    The collection comes back in the *declared* scale order rather than the order the sentence
    happens to state its steps in -- see ``test_a_proposed_collection_can_be_built_into_a_statement``
    for why a proposal that does not is unauthorable.
    """

    grammar = _step_grammar(("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii"), ("I", "ovc_i"))

    (proposal,) = _propose_steps(grammar, "Synthetic step IV to III, then III to II.")

    assert pair_tokens(proposal.chosen["permitted_steps"]) == (
        ("ovc_iii", "ovc_ii"),
        ("ovc_iv", "ovc_iii"),
    )


def test_a_proposed_collection_can_be_built_into_a_statement() -> None:
    """A prefill nothing can author is worse than no prefill: it takes its whole draft list down.

    A proposal is validated per dimension -- each name and value one the variant declares -- and
    nothing checks it against the refusals the fact model makes *across* fields. A collection is
    where those live: the reduction family refuses a step collection out of the declared scale's
    order, so a positional reading of a sentence stating its steps downward proposed a draft the
    model would not accept, and every caller that builds a candidate statement from a draft raised
    on it rather than skipping the draft.

    Both orders of the same two stated steps, because the defect was invisible for the ascending
    one: the sentence's own order happened to be the declared order there.
    """

    grammar = _step_grammar(
        ("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii"), settle_the_rest=True
    )
    downward = "Synthetic reading over basic which may step IV to III, then III to II."
    upward = "Synthetic reading over basic which may step III to II, then IV to III."

    for sentence in (downward, upward):
        (proposal,) = _propose_steps(grammar, sentence)

        assert proposal.fully_proposed, sentence
        fact = proposed_fact(proposal, statement_index=0)
        assert [(step.source_ovc, step.target_ovc) for step in fact.permitted_steps] == [
            ("ovc_iii", "ovc_ii"),
            ("ovc_iv", "ovc_iii"),
        ], sentence


def test_a_sequence_rule_states_one_transition_named_twice_once() -> None:
    """One sentence naming a transition twice states it once, exactly as a scope's values do.

    The collection's own refusal of a repeat is about a reviewer's rows, where a duplicate they
    typed is something to see rather than to silently drop. A positional reading has no such
    arrangement to respect, so its repeat is an artifact of the wording and the reading is one
    transition.
    """

    grammar = _step_grammar(("IV", "ovc_iv"), ("III", "ovc_iii"))

    (proposal,) = _propose_steps(grammar, "Synthetic step IV to III, and again IV to III.")

    assert pair_tokens(proposal.chosen["permitted_steps"]) == (("ovc_iv", "ovc_iii"),)


def test_a_sequence_rules_trailing_unpaired_token_settles_nothing() -> None:
    """Half a step is not a step, and guessing its other half would invent a reading."""

    grammar = _step_grammar(("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii"))

    (proposal,) = _propose_steps(grammar, "Synthetic step IV to III, and also II.")

    assert pair_tokens(proposal.chosen["permitted_steps"]) == (("ovc_iv", "ovc_iii"),)


def test_a_sequence_rule_finds_no_pair_where_the_sentence_states_no_relation() -> None:
    """Two tokens of a scale in order are not a transition unless the sentence relates them.

    A scale token carries no role of its own, so a sentence naming the position that applies and
    the position that applies instead names two in order exactly as a transition between them does.
    Ungated it proposed a step -- and one running the wrong way up the scale, which is the reading
    a reviewer is least likely to catch, because both endpoints are real values of the dimension.
    Unchosen rather than defaulted: a blank field cannot be confirmed by accident.
    """

    tokens = (("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii"))
    grammar = _step_grammar(*tokens, keywords=("reduce",))

    (listing,) = _propose_steps(grammar, "Synthetic reading of III, and of IV where so required.")
    (relating,) = _propose_steps(grammar, "Synthetic reading which shall reduce IV to III.")

    assert "permitted_steps" in listing.unchosen
    assert pair_tokens(relating.chosen["permitted_steps"]) == (("ovc_iv", "ovc_iii"),)


# --- a bullet inherits from the stem it completes -------------------------------------


def _bullet_fragment(texts: tuple[tuple[str, str], ...]) -> RawClauseFragment:
    """A fragment whose nodes carry the given (kind, text) pairs, in order."""

    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=text,
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order, (kind, text) in enumerate(texts)
    )
    fragment = RawClauseFragment(
        id=f"raw-{ROUTE}", raw_sha256="0" * 64, nodes=nodes, tokens=(), source=SOURCE
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


_INHERITING_GRAMMAR = _GRAMMAR.model_copy(update={"inherited_dimensions": ("obligation",)})


def _propose_nodes(texts: tuple[tuple[str, str], ...]):
    return propose_clause_facts(
        _bullet_fragment(texts),
        rule_route=ROUTE,
        fact_kind="hf_attenuation",
        propose=keyword_proposer(_INHERITING_GRAMMAR),
    )


def test_a_bullet_carries_the_colon_stem_it_completes() -> None:
    """A list item has no finite verb of its own; its stem is where the modality lives."""

    sentences = clause_sentences(
        _bullet_fragment(
            (
                ("paragraph", "Synthetic stem which the items complete:"),
                ("bullet", "synthetic first item;"),
                ("bullet", "synthetic second item."),
            )
        )
    )

    assert [item.stem_text for item in sentences] == [
        "",
        "Synthetic stem which the items complete:",
        "Synthetic stem which the items complete:",
    ]


def test_a_paragraph_not_ending_in_a_colon_is_not_a_stem() -> None:
    """A colon is what marks a sentence as completed by what follows it."""

    sentences = clause_sentences(
        _bullet_fragment(
            (("paragraph", "Synthetic standalone reading."), ("bullet", "synthetic item;"))
        )
    )

    assert [item.stem_text for item in sentences] == ["", ""]


def test_an_inherited_dimension_is_read_from_the_stem() -> None:
    proposals = _propose_nodes(
        (
            ("paragraph", "Synthetic stem which shall be completed by the items:"),
            ("bullet", "synthetic item naming DVC As;"),
        )
    )

    bullet = next(item for item in proposals if item.node_references[0].node_order == 1)
    assert bullet.chosen["obligation"] == "requirement"
    assert bullet.chosen["dvc_gate"] == "dvc_as"


def test_a_bullet_stating_its_own_value_does_not_also_inherit_one() -> None:
    """A fallback, not an addition: inheriting alongside would yield two contradictory drafts."""

    proposals = _propose_nodes(
        (
            ("paragraph", "Synthetic stem which shall be completed by the items:"),
            ("bullet", "synthetic item which may apply, naming DVC As;"),
        )
    )

    bullets = [item for item in proposals if item.node_references[0].node_order == 1]
    assert [item.chosen["obligation"] for item in bullets] == ["permission"]


def test_a_dimension_not_declared_inheritable_is_never_read_from_the_stem() -> None:
    """Inheritance is declared per dimension, so a stem cannot leak its whole reading."""

    proposals = propose_clause_facts(
        _bullet_fragment(
            (
                ("paragraph", "Synthetic stem naming DVC As, which shall be completed:"),
                ("bullet", "synthetic item stating no gate;"),
            )
        ),
        rule_route=ROUTE,
        fact_kind="hf_attenuation",
        propose=keyword_proposer(_INHERITING_GRAMMAR),
    )

    bullet = next(item for item in proposals if item.node_references[0].node_order == 1)
    assert bullet.chosen["obligation"] == "requirement"
    assert "dvc_gate" in bullet.unchosen


def test_a_stem_carries_across_node_boundaries() -> None:
    """A list routinely opens at the foot of one region and continues in the next."""

    proposals = _propose_nodes(
        (
            ("paragraph", "Synthetic stem which shall be completed by the items:"),
            ("bullet", "synthetic first item;"),
            ("bullet", "synthetic later item on another node."),
        )
    )

    assert [
        item.chosen.get("obligation")
        for item in proposals
        if item.node_references[0].node_order in (1, 2)
    ] == ["requirement", "requirement"]


def test_a_sentence_that_scopes_the_ones_after_it_yields_no_draft() -> None:
    """Amendment A4: a context node selects no branch, so it is never offered as authorable.

    Offering one asks the reviewer to invent the dimensions it does not state, and a statement
    manufactured for it -- unstated dimensions filled with wildcards and an arbitrary answer -- is a
    reading nobody made. It stays a sentence of the fragment, because it is still evidence and still
    where its items' modality is read from.
    """

    nodes = (
        ("paragraph", "Synthetic stem which shall be completed by the items:"),
        ("bullet", "synthetic first item naming DVC As;"),
        ("bullet", "synthetic second item naming DVC B."),
    )

    assert {item.node_references[0].node_order for item in _propose_nodes(nodes)} == {1, 2}
    # Still a sentence, and still the stem its items inherit from.
    assert [item.node_order for item in clause_sentences(_bullet_fragment(nodes))] == [0, 1, 2]


def test_a_paragraph_no_item_completes_still_yields_its_own_draft() -> None:
    """The other half: a colon is only a lead-in when something leads on from it.

    Without this the rule would silently swallow any sentence that happens to end in a colon,
    which is a statement lost rather than a context node skipped.
    """

    proposals = _propose_nodes(
        (
            ("paragraph", "Synthetic standalone reading naming DVC As, listing nothing:"),
            ("paragraph", "Synthetic second standalone reading naming DVC B."),
        )
    )

    assert {item.node_references[0].node_order for item in proposals} == {0, 1}


def test_a_grammar_declaring_an_unknown_inherited_dimension_is_refused() -> None:
    with pytest.raises(ValidationError, match="no dimension"):
        ClauseFactGrammar(fact_kind="hf_attenuation", inherited_dimensions=("device_placement",))


# --- what stays unchosen --------------------------------------------------------------


def test_a_dimension_no_rule_settles_stays_out_of_the_reading() -> None:
    """Never a default and never an ``any_*`` fallback: unrestricted and unread are not the same."""

    (proposal,) = _propose(("Synthetic reading naming nothing the grammar looks for.",))

    assert proposal.chosen == {"threshold_reference": "synthetic.threshold.route"}
    assert set(proposal.unchosen) == {
        name for name, _kind, _options in fact_dimensions("hf_attenuation")
    } - {"threshold_reference"}
    assert proposal.fully_proposed is False


def test_a_fully_proposed_draft_builds_its_typed_statement() -> None:
    (proposal,) = _propose(
        ("Synthetic DVC As gate shall be shown by test, simulation or calculation.",)
    )

    fact = proposed_fact(proposal, statement_index=3)

    assert proposal.fully_proposed is True
    assert fact.statement_index == 3
    assert fact.fact_kind == "hf_attenuation"
    # The boolean dimension arrives as text and is converted exactly once.
    assert fact.comparison_required is True
    assert fact.node_references == proposal.node_references
    # The scope dimension arrives as its wire form and is decoded exactly once.
    assert fact.dvc_gate == DimensionScope.of("dvc_as")


def test_a_variant_family_offers_each_kinds_own_dimensions() -> None:
    """A family with variants has no single model whose fields answer for all of it.

    ``fact_dimensions`` reads the variant the caller names, so the editor and the proposer cannot
    offer one kind's dimensions while building the other kind's statement.
    """

    measure = {name for name, _kind, _options in fact_dimensions("system_voltage", "measure")}
    applicability = {
        name for name, _kind, _options in fact_dimensions("system_voltage", "applicability")
    }

    assert fact_variants("system_voltage") == ("measure", "applicability")
    assert "measure" in measure and "measure" not in applicability
    assert "counts_as_system_voltage" in applicability
    # The kind itself is not a dimension of the statement: it decides which dimensions there are.
    assert "statement_kind" not in measure | applicability


def test_a_one_kind_family_declares_no_variant_and_refuses_one() -> None:
    """Naming a kind for a family that states one would author a variant nobody declared."""

    assert fact_variants("hf_attenuation") == ()
    with pytest.raises(RulePackageError, match="one statement kind"):
        fact_dimensions("hf_attenuation", "measure")


def test_a_variant_family_refuses_to_be_read_without_a_kind() -> None:
    """Defaulting to the first variant would silently author the wrong kind of statement."""

    with pytest.raises(RulePackageError, match="applicability"):
        fact_dimensions("system_voltage")


def test_a_grammar_for_a_variant_family_must_name_the_kind_it_proposes() -> None:
    with pytest.raises(ValidationError, match="applicability"):
        ClauseFactGrammar(
            fact_kind="system_voltage",
            keyword_rules=(_keyword("earthing", "tn", "synthetic"),),
        )


def test_a_grammar_naming_a_dimension_of_another_variant_is_refused() -> None:
    """Each variant's rules are validated against its own model, not against the family's union."""

    with pytest.raises(ValidationError, match="no dimension"):
        ClauseFactGrammar(
            fact_kind="system_voltage",
            statement_kind="applicability",
            keyword_rules=(_keyword("measure", "phase_to_phase_rms", "synthetic"),),
        )


def test_a_draft_of_one_kind_builds_that_kinds_statement() -> None:
    """The draft carries its own kind, so the typed statement it records is of that kind."""

    grammar = ClauseFactGrammar(
        fact_kind="system_voltage",
        statement_kind="applicability",
        keyword_rules=(
            _keyword("obligation", "requirement", "shall"),
            _keyword("supply_kind", "mains", "synthetic"),
            _keyword("input_topology", "isolated_secondary", "secondaries"),
            _keyword("purpose", "impulse", "impulse"),
            _keyword("counts_as_system_voltage", "true", "shall"),
        ),
    )
    fragment = fragment_with_sentences(
        ROUTE, ("Synthetic impulse reading of secondaries which shall apply.",)
    )

    (proposal,) = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="system_voltage",
        statement_kind="applicability",
        propose=keyword_proposer(grammar),
    )
    fact = proposed_fact(proposal, statement_index=0)

    assert proposal.statement_kind == "applicability"
    assert proposal.fully_proposed is True
    assert fact.fact_kind == "system_voltage"
    assert fact.statement_kind == "applicability"
    assert fact.counts_as_system_voltage is True


def test_a_scope_dimension_is_offered_as_a_scope_over_its_own_vocabulary() -> None:
    """The editor's widget kind comes from the model, so a new scope cannot be missed.

    Without this the shared machinery refused every scope field outright -- a dimension the editor
    cannot offer is a fact no reviewer can author -- and the route would block approval with
    nothing saying why.
    """

    kinds = {name: (kind, options) for name, kind, options in fact_dimensions("hf_attenuation")}

    assert kinds["dvc_gate"] == ("scope", ("dvc_as", "dvc_b"))
    assert kinds["evidence_kind"] == ("scope", ("test", "simulation", "calculation"))
    assert kinds["obligation"][0] == "choice"


@pytest.mark.parametrize(
    ("scope", "wire"),
    (
        (DimensionScope[str].unrestricted(), "*"),
        (DimensionScope[str].of("dvc_as"), "dvc_as"),
        (DimensionScope[str].of("dvc_b", "dvc_as"), "dvc_as|dvc_b"),
    ),
)
def test_a_scope_survives_its_wire_form_in_both_directions(
    scope: DimensionScope[str], wire: str
) -> None:
    """One encode point and one decode point, so the two authoring paths cannot disagree."""

    assert scope_wire(scope) == wire
    assert scope_from_wire(wire) == scope.model_dump()


def test_an_unchosen_dimension_cannot_be_turned_into_a_statement() -> None:
    (proposal,) = _propose(("Synthetic DVC As gate and nothing else.",))

    with pytest.raises(ValueError, match="unchosen"):
        proposed_fact(proposal, statement_index=0)


def test_a_locked_dimension_is_never_overridden_by_a_reading() -> None:
    """The route determines it, so a sentence must not be able to state the other value."""

    grammar = ClauseFactGrammar(
        fact_kind="spd_reduction",
        statement_kind="permission",
        keyword_rules=(_keyword("supply_kind", "non_mains", "synthetic"),),
    )
    fragment = fragment_with_sentences(ROUTE, ("Synthetic reading.",))

    (proposal,) = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="spd_reduction",
        statement_kind="permission",
        propose=keyword_proposer(grammar),
        locked={"supply_kind": "mains"},
    )

    assert proposal.chosen["supply_kind"] == "mains"


# --- declaration guards ---------------------------------------------------------------


def test_a_keyword_matches_on_word_boundaries_only() -> None:
    """A term found inside a longer word is a different term and a wrong proposal."""

    rule = _keyword("dvc_gate", "dvc_as", "test")

    assert rule.matches("Synthetic test applies.") is True
    assert rule.matches("Synthetic testing applies.") is False


def test_a_keyword_carrying_a_capital_is_matched_case_sensitively() -> None:
    """A designation must not be found by the ordinary lower-case word that spells it."""

    designation = _keyword("earthing", "it", "IT")
    lower_case_term = _keyword("purpose", "impulse", "impulse")

    assert designation.matches("Synthetic IT reading.") is True
    assert designation.matches("Synthetic reading, whatever it states.") is False
    # A lower-case term is still found where a sentence happens to open with it.
    assert lower_case_term.matches("Impulse reading stated first.") is True


def test_a_rule_naming_only_exclusions_records_the_unrestricted_reading() -> None:
    rule = _keyword("purpose", SCOPE_UNRESTRICTED, without=("withstand",))

    assert rule.matches("Synthetic reading restricting nothing.") is True
    assert rule.matches("Synthetic withstand reading.") is False


@pytest.mark.parametrize(
    "keyword",
    (
        "",
        " padded",
        "five separate words in one",
        "an extremely long declared keyword that is really a sentence",
    ),
)
def test_a_keyword_that_is_not_a_short_term_is_refused(keyword: str) -> None:
    """The content boundary, enforced where a rule is declared: keywords are short terms."""

    with pytest.raises(ValidationError):
        _keyword("dvc_gate", "dvc_as", keyword)


def test_a_rule_with_no_keyword_at_all_is_refused() -> None:
    with pytest.raises(ValidationError, match="every sentence"):
        ClauseKeywordRule(dimension="dvc_gate", value="dvc_as")


def test_a_grammar_naming_a_dimension_its_family_lacks_is_refused() -> None:
    """Caught where it is declared: such a rule proposes a reading nothing could author."""

    with pytest.raises(ValidationError, match="no dimension"):
        ClauseFactGrammar(
            fact_kind="hf_attenuation",
            keyword_rules=(_keyword("device_placement", "internal_to_pecs", "internal"),),
        )


def test_a_grammar_naming_a_value_outside_its_dimensions_vocabulary_is_refused() -> None:
    with pytest.raises(ValidationError, match="no value"):
        ClauseFactGrammar(
            fact_kind="hf_attenuation",
            keyword_rules=(_keyword("dvc_gate", "dvc_c", "synthetic"),),
        )


def test_a_sequence_rule_naming_a_value_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(ValidationError, match="no value"):
        ClauseFactGrammar(
            fact_kind="spd_reduction",
            statement_kind="permission",
            sequence_rules=(
                ClauseSequenceRule(
                    tokens=(("IV", "ovc_iv"), ("X", "ovc_x")), dimension="permitted_steps"
                ),
            ),
        )


def test_a_sequence_rule_filling_a_dimension_that_holds_no_pairs_is_refused() -> None:
    """Its reading is a collection of pairs, so a scalar dimension could not hold it."""

    with pytest.raises(ValidationError, match="no pairs"):
        ClauseFactGrammar(
            fact_kind="spd_reduction",
            statement_kind="permission",
            sequence_rules=(
                ClauseSequenceRule(tokens=(("IV", "ovc_iv"),), dimension="supply_kind"),
            ),
        )


def test_an_unknown_fact_family_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown fact family"):
        ClauseFactGrammar(fact_kind="synthetic_family")
