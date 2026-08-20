"""The advisory prompt: everything a model needs to answer, and nothing it has to guess.

Every fixture here is invented. The real prompt carries licensed clause text by design, which is
precisely why no sentence of the standard may appear in this file: what these tests assert is that
whatever text the context carries reaches the prompt, never what that text says.
"""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.clause_fact_ai_prompt import (
    ClauseFactPromptContext,
    ClauseFactPromptFact,
    ClauseFactPromptNode,
    ClauseFactPromptProposal,
    build_clause_fact_ai_prompt,
)
from insulation_coordination.rules.importer.clause_fact_proposals import (
    fact_dimensions,
    fact_variants,
)

#: Two invented rule ids, so the route-reference section is asserted against a list this file
#: states rather than against whatever the recipe happens to declare today.
_REFERENCES = ("synthetic.rule.alpha", "synthetic.rule.beta")


def _proposal(sentence_index: int) -> ClauseFactPromptProposal:
    """One open draft, distinguished from its siblings only by the label the dialog shows."""

    return ClauseFactPromptProposal(
        sentence_index=sentence_index,
        sentence_text=f"invented sentence {sentence_index}",
        statement_kind="requirement",
        cited_nodes=(sentence_index,),
        chosen=(("obligation", "requirement"),),
        unchosen=("evidence_kind",),
    )


def _context(**overrides: object) -> ClauseFactPromptContext:
    """One route's context with every collection empty, for a test to fill one of them in."""

    defaults: dict[str, object] = {
        "rule_route": "synthetic.route.one",
        "fragment_id": "raw-synthetic.route.one",
        "fact_family": "hf_attenuation",
        "status": "needs_facts",
        "defect": None,
        "next_statement_index": 0,
        "source_standard": "SYNTHETIC",
        "source_pages": (11, 12),
        "nodes": (),
        "facts": (),
        "open_proposals": (),
        "dismissed_proposals": (),
        "proposals_unavailable": "",
        "uncovered": (),
        "route_references": _REFERENCES,
        "fixed_dimensions": (),
    }
    return ClauseFactPromptContext.model_validate(defaults | overrides)


def test_the_prompt_names_the_route_it_is_about() -> None:
    prompt = build_clause_fact_ai_prompt(
        _context(status="needs_completion", defect="synthetic defect", next_statement_index=3)
    )

    assert "synthetic.route.one" in prompt
    assert "raw-synthetic.route.one" in prompt
    assert "hf_attenuation" in prompt
    assert "needs_completion" in prompt
    assert "synthetic defect" in prompt
    assert "next suggested statement index: 3" in prompt
    assert "SYNTHETIC" in prompt
    assert "11, 12" in prompt


def test_every_clause_node_reaches_the_prompt_in_order() -> None:
    """The evidence *is* the prompt: a node left out is a statement the model cannot see."""

    prompt = build_clause_fact_ai_prompt(
        _context(
            nodes=(
                ClauseFactPromptNode(order=0, kind="paragraph", text="invented lead sentence"),
                ClauseFactPromptNode(order=1, kind="bullet", text="invented bullet item"),
            )
        )
    )

    assert "node 0 (paragraph):" in prompt
    assert "invented lead sentence" in prompt
    assert "node 1 (bullet):" in prompt
    assert "invented bullet item" in prompt
    assert prompt.index("invented lead sentence") < prompt.index("invented bullet item")


def test_a_fragment_with_no_node_says_so_rather_than_showing_an_empty_section() -> None:
    assert "nothing to read" in build_clause_fact_ai_prompt(_context())


def test_every_statement_kind_and_dimension_of_the_family_is_offered() -> None:
    """Derived from the fact models, so a dimension added to one cannot go unasked."""

    prompt = build_clause_fact_ai_prompt(_context(fact_family="spd_monitoring"))

    for variant in fact_variants("spd_monitoring"):
        assert f'### Statement kind "{variant}"' in prompt
        for name, _kind, options in fact_dimensions("spd_monitoring", variant):
            assert name in prompt
            for option in options:
                assert option in prompt


def test_a_family_stating_one_kind_of_reading_offers_no_statement_kind_to_invent() -> None:
    """``fact_variants`` is empty for such a family, and a name offered here would be made up."""

    assert fact_variants("propagation_step") == ()

    prompt = build_clause_fact_ai_prompt(_context(fact_family="propagation_step"))

    assert "states one kind of reading" in prompt
    assert "### Statement kind" not in prompt
    assert "omit the statement kind line" in prompt


def test_a_scope_says_that_unrestricted_is_not_every_value() -> None:
    """The one semantic difference a model would otherwise flatten, and the reading would be wrong."""

    prompt = build_clause_fact_ai_prompt(_context(fact_family="hf_attenuation"))

    assert "scope over: test, simulation, calculation" in prompt
    assert "Never substitute one for the other." in prompt
    assert "places no restriction on this dimension" in prompt


def test_a_pair_collection_says_its_rows_are_ordered_pairs_in_a_meaningful_order() -> None:
    prompt = build_clause_fact_ai_prompt(_context(fact_family="spd_reduction"))

    assert "ordered sequence of pairs drawn from:" in prompt
    assert "the order of the rows is part of the reading" in prompt
    assert "Do not sort, deduplicate or reorder it." in prompt


def test_route_reference_options_come_from_the_recipe_and_are_listed_once() -> None:
    """``fact_dimensions`` leaves that vocabulary empty on purpose; unlisted, a model invents one.

    Listed once for the whole family rather than under each referencing dimension: reinforced
    treatment declares one in both of its statement kinds, and forty-odd ids twice over buries the
    dimensions that differ.
    """

    assert all(
        options == ()
        for variant in fact_variants("reinforced_treatment")
        for name, kind, options in fact_dimensions("reinforced_treatment", variant)
        if kind == "route_reference"
    )

    prompt = build_clause_fact_ai_prompt(_context(fact_family="reinforced_treatment"))

    assert prompt.count("synthetic.rule.alpha") == 1
    assert prompt.count("synthetic.rule.beta") == 1
    assert "Never compose an id of your own." in prompt


def test_a_free_identifier_is_marked_as_free_text_and_must_cite_its_evidence() -> None:
    prompt = build_clause_fact_ai_prompt(_context(fact_family="reinforced_treatment"))

    assert "factor -- FREE TEXT, no vocabulary." in prompt
    assert "quote the node number and the exact phrase" in prompt


def test_a_route_fixed_dimension_is_context_rather_than_a_choice() -> None:
    prompt = build_clause_fact_ai_prompt(
        _context(fact_family="spd_reduction", fixed_dimensions=(("supply_kind", "mains"),))
    )

    assert "Fixed by the route itself, not your choice" in prompt
    assert "supply_kind: mains" in prompt
    assert "- supply_kind -- exact choice" not in prompt


def test_authored_facts_reach_the_prompt_with_their_citations_and_values() -> None:
    prompt = build_clause_fact_ai_prompt(
        _context(
            facts=(
                ClauseFactPromptFact(
                    statement_index=2,
                    statement_kind="requirement",
                    dimensions=(("obligation", "requirement"), ("evidence_kind", "test")),
                    cited_nodes=(0, 3),
                    evidence="current",
                ),
            )
        )
    )

    assert "statement 2, kind requirement, cites node(s) 0, 3, evidence current" in prompt
    assert "obligation: requirement" in prompt
    assert "evidence_kind: test" in prompt


def test_a_stale_authored_fact_is_labelled_stale_and_the_label_is_explained() -> None:
    """Otherwise the model compares a reading against a clause the reading no longer matches."""

    prompt = build_clause_fact_ai_prompt(
        _context(
            facts=(
                ClauseFactPromptFact(
                    statement_index=0,
                    statement_kind="",
                    dimensions=(("obligation", "requirement"),),
                    cited_nodes=(0,),
                    evidence="stale",
                ),
            )
        )
    )

    assert "evidence stale" in prompt
    assert "cites a node whose text has changed" in prompt


def test_open_and_dismissed_proposals_are_reported_separately() -> None:
    open_proposal = ClauseFactPromptProposal(
        sentence_index=0,
        sentence_text="invented open sentence",
        statement_kind="requirement",
        cited_nodes=(1,),
        chosen=(("obligation", "requirement"),),
        unchosen=("evidence_kind", "threshold_reference"),
    )
    dismissed = ClauseFactPromptProposal(
        sentence_index=1,
        sentence_text="invented dismissed sentence",
        statement_kind="requirement",
        cited_nodes=(2,),
        chosen=(),
        unchosen=(),
    )

    prompt = build_clause_fact_ai_prompt(
        _context(open_proposals=(open_proposal,), dismissed_proposals=(dismissed,))
    )

    assert "sentence 0, proposed kind requirement, cites node(s) 1" in prompt
    assert "settled obligation: requirement" in prompt
    assert "settled by nobody yet: evidence_kind, threshold_reference" in prompt
    assert "invented open sentence" in prompt
    assert "stating nothing this route models" in prompt
    assert "invented dismissed sentence" in prompt
    assert prompt.index("invented open sentence") < prompt.index("invented dismissed sentence")


def test_no_proposal_at_all_is_stated_rather_than_shown_as_an_empty_list() -> None:
    """A public checkout has no private grammar, which is the ordinary case, not a claim."""

    prompt = build_clause_fact_ai_prompt(
        _context(proposals_unavailable="synthetic reason there is no grammar")
    )

    assert "no proposal at all: synthetic reason there is no grammar" in prompt


def test_the_completion_guard_items_are_carried_as_findings() -> None:
    prompt = build_clause_fact_ai_prompt(_context(uncovered=("synthetic uncovered statement",)))

    assert "statements no authored fact covers" in prompt
    assert "- synthetic uncovered statement" in prompt
    assert "Findings, not authority." in prompt


@pytest.mark.parametrize(
    "instruction",
    [
        "UNRESOLVED",
        "Never invent a field value.",
        "is the only party who authors a fact",
        "Never phrase any part of your answer as approval",
        "It is not approval",
        "ask the reviewer for the printed page",
    ],
)
def test_the_conservative_instructions_are_present(instruction: str) -> None:
    """The whole safety framing, asserted one clause at a time so a deletion cannot pass."""

    assert instruction in build_clause_fact_ai_prompt(_context())


def test_each_block_recommends_one_action_naming_what_the_human_would_press() -> None:
    """One word per block, and the reviewer knows which button it heads for."""

    prompt = build_clause_fact_ai_prompt(_context())

    for action in (
        "AUTHOR_AS_PROPOSED",
        "AUTHOR_WITH_EDITS",
        "AUTHOR_UNPROPOSED",
        "DISMISS",
        "ASK_HUMAN",
    ):
        assert action in prompt
    # An action the reviewer cannot carry out is worse than no action: a block still holding an
    # UNRESOLVED field is a question, however many of its other fields came out settled.
    assert "Any block carrying an UNRESOLVED line takes this action and no other" in prompt
    assert "Recommendation: NOT_READY | APPEARS_READY_FOR_HUMAN_CONFIRMATION" in prompt
    # The authority statement comes last as well as first: a model that skimmed the opening
    # paragraph still has to read this to produce the final block.
    assert prompt.rstrip().endswith("on the maintainer's behalf.")


def test_the_blocks_to_produce_are_named_after_the_rows_the_dialog_shows() -> None:
    """The fault this replaced: the model numbered its own blocks and nothing matched a row."""

    prompt = build_clause_fact_ai_prompt(_context(open_proposals=(_proposal(2), _proposal(5))))

    listed = prompt[prompt.index("Blocks to produce") :]
    assert "- sentence 2" in listed
    assert "- sentence 5" in listed
    assert listed.index("- sentence 2") < listed.index("- sentence 5")


def test_a_route_with_no_open_proposal_asks_only_for_unproposed_blocks() -> None:
    prompt = build_clause_fact_ai_prompt(_context(proposals_unavailable="synthetic reason"))

    assert "Section 3 lists no open proposal" in prompt
    assert "Blocks to produce, in this order:" not in prompt


def test_every_field_is_marked_kept_changed_or_filled_rather_than_described_in_prose() -> None:
    """The prose delta is what the reviewer had to interpret; a marker per field replaces it."""

    prompt = build_clause_fact_ai_prompt(_context())

    assert "- keep <field>: <value>" in prompt
    assert "- SET <field>: <value> (proposal had <value>)" in prompt
    assert "- FILL <field>: <value | UNRESOLVED> (proposal left this open)" in prompt
    assert "Compared with app proposal" not in prompt
    assert "differences" not in prompt


def test_the_summary_lists_the_whole_route_before_the_first_block() -> None:
    prompt = build_clause_fact_ai_prompt(_context())

    assert "## Summary" in prompt
    assert prompt.index("## Summary") < prompt.index("Action: <exactly one")


def test_a_dimension_the_grammar_left_open_is_not_thereby_unrestricted() -> None:
    """Grammar silence and "the clause restricts nothing" are different claims."""

    prompt = build_clause_fact_ai_prompt(_context())

    assert "is not thereby unrestricted" in prompt
    assert "a fact about the grammar and not about the clause" in prompt
    assert "are three different answers" in prompt


def test_a_restriction_inherited_from_a_scoping_sentence_must_be_named() -> None:
    """Folding one in silently is the failure: the inheritance is the reviewer's judgement."""

    prompt = build_clause_fact_ai_prompt(_context())

    assert "Never carry a restriction down from such a sentence silently" in prompt
    assert "Scoping: none | node <order>" in prompt


def test_the_reading_is_formed_before_the_proposals_are_read() -> None:
    """The one ordering the proposal-keyed template would otherwise invert."""

    prompt = build_clause_fact_ai_prompt(_context())

    assert "before you read the proposals in section 3" in prompt
    assert "Only now read the proposals in section 3" in prompt


def test_one_context_always_renders_the_same_prompt() -> None:
    """Nothing here reads a clock, a set or a dict order, so two presses can be compared."""

    context = _context(
        nodes=(ClauseFactPromptNode(order=0, kind="paragraph", text="invented text"),),
        fact_family="spd_reduction",
        fixed_dimensions=(("supply_kind", "mains"),),
    )

    assert build_clause_fact_ai_prompt(context) == build_clause_fact_ai_prompt(context)
