"""Sentence-level clause fact proposals. Invented sentences only; no IEC content.

Every sentence below is written for this file out of the neutral terms a declared rule names.
None of them is a clause's wording, and no test here states how many statements any real clause
makes or which of its nodes states what.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.clause_fact_proposals import (
    ClauseFactGrammar,
    ClauseKeywordRule,
    ClauseSequenceRule,
    clause_sentences,
    fact_dimensions,
    keyword_proposer,
    propose_clause_facts,
    proposed_fact,
)
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


def _keyword(dimension: str, value: str, *keywords: str, without: tuple[str, ...] = ()):
    return ClauseKeywordRule(
        dimension=dimension, value=value, keywords=keywords, excluded_keywords=without
    )


#: A grammar over the attenuation family, built from that family's own vocabulary and from terms
#: invented for this file.
_GRAMMAR = ClauseFactGrammar(
    fact_kind="hf_attenuation",
    keyword_rules=(
        _keyword("obligation", "requirement", "shall"),
        _keyword("obligation", "permission", "may"),
        _keyword("dvc_gate", "dvc_as", "DVC", "As"),
        _keyword("dvc_gate", "dvc_b", "DVC", "B"),
        _keyword("evidence_kind", "any_evidence", "test", "simulation", "calculation"),
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


def test_a_sentence_restricting_one_dimension_to_several_values_yields_a_draft_per_value() -> None:
    """An unrestricted token would answer for the values the sentence leaves out."""

    proposals = _propose(("Synthetic gate naming DVC As and DVC B, which shall be shown.",))

    assert [item.chosen["dvc_gate"] for item in proposals] == ["dvc_as", "dvc_b"]
    assert {item.sentence_index for item in proposals} == {0}


def test_two_multiplied_dimensions_expand_as_a_cartesian_product() -> None:
    grammar = _GRAMMAR.model_copy(
        update={
            "keyword_rules": (
                *_GRAMMAR.keyword_rules,
                # A second value for the same dimension the same sentence also names.
                _keyword("evidence_kind", "test", "test"),
            )
        }
    )
    fragment = fragment_with_sentences(
        ROUTE, ("Synthetic DVC As and DVC B gate shall be shown by test, simulation, calculation.",)
    )

    proposals = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="hf_attenuation",
        propose=keyword_proposer(grammar),
    )

    assert {(item.chosen["dvc_gate"], item.chosen["evidence_kind"]) for item in proposals} == {
        ("dvc_as", "any_evidence"),
        ("dvc_as", "test"),
        ("dvc_b", "any_evidence"),
        ("dvc_b", "test"),
    }


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


def test_a_sequence_rule_pairs_its_tokens_in_the_order_the_sentence_states_them() -> None:
    """Which value is the step's start and which its end is order, not wording."""

    grammar = ClauseFactGrammar(
        fact_kind="spd_reduction",
        sequence_rules=(
            ClauseSequenceRule(
                tokens=(("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii"), ("I", "ovc_i")),
                dimensions=("source_ovc", "target_ovc"),
            ),
        ),
    )
    fragment = fragment_with_sentences(ROUTE, ("Synthetic step IV to III, then III to II.",))

    proposals = propose_clause_facts(
        fragment, rule_route=ROUTE, fact_kind="spd_reduction", propose=keyword_proposer(grammar)
    )

    assert [(item.chosen["source_ovc"], item.chosen["target_ovc"]) for item in proposals] == [
        ("ovc_iv", "ovc_iii"),
        ("ovc_iii", "ovc_ii"),
    ]


def test_a_sequence_rules_trailing_unpaired_token_settles_nothing() -> None:
    """Half a step is not a step, and guessing its other half would invent a reading."""

    grammar = ClauseFactGrammar(
        fact_kind="spd_reduction",
        sequence_rules=(
            ClauseSequenceRule(
                tokens=(("IV", "ovc_iv"), ("III", "ovc_iii"), ("II", "ovc_ii")),
                dimensions=("source_ovc", "target_ovc"),
            ),
        ),
    )
    fragment = fragment_with_sentences(ROUTE, ("Synthetic step IV to III, and also II.",))

    (proposal,) = propose_clause_facts(
        fragment, rule_route=ROUTE, fact_kind="spd_reduction", propose=keyword_proposer(grammar)
    )

    assert (proposal.chosen["source_ovc"], proposal.chosen["target_ovc"]) == ("ovc_iv", "ovc_iii")


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


def test_an_unchosen_dimension_cannot_be_turned_into_a_statement() -> None:
    (proposal,) = _propose(("Synthetic DVC As gate and nothing else.",))

    with pytest.raises(ValueError, match="unchosen"):
        proposed_fact(proposal, statement_index=0)


def test_a_locked_dimension_is_never_overridden_by_a_reading() -> None:
    """The route determines it, so a sentence must not be able to state the other value."""

    grammar = ClauseFactGrammar(
        fact_kind="spd_reduction",
        keyword_rules=(_keyword("supply_kind", "non_mains", "synthetic"),),
    )
    fragment = fragment_with_sentences(ROUTE, ("Synthetic reading.",))

    (proposal,) = propose_clause_facts(
        fragment,
        rule_route=ROUTE,
        fact_kind="spd_reduction",
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
    rule = _keyword("purpose", "any_purpose", without=("withstand",))

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
            sequence_rules=(
                ClauseSequenceRule(
                    tokens=(("IV", "ovc_iv"), ("X", "ovc_x")),
                    dimensions=("source_ovc", "target_ovc"),
                ),
            ),
        )


def test_a_sequence_rule_filling_one_dimension_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="two different dimensions"):
        ClauseSequenceRule(tokens=(("IV", "ovc_iv"),), dimensions=("source_ovc", "source_ovc"))


def test_an_unknown_fact_family_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown fact family"):
        ClauseFactGrammar(fact_kind="synthetic_family")
