"""Private: the declared proposal grammars reach, on the real fragments, what they claim to.

Structural only. Nothing here states what any clause says, how many statements it makes, which
node or sentence states which statement, or what any proposed reading is: every expectation is
*derived from the recipe's own declarations* and compared against the shape of what the proposer
returns. A keyword that no longer matches the licensed text therefore fails this file without
any of that text having an anchor in the repository.

What it protects: a keyword rule is declared once and then silently stops matching -- a reprint
reflows a region, an extraction bbox moves, a term is mistyped -- and the only visible effect is
that a maintainer quietly does more typing. The gate never notices, because a proposal is a
prefill and an unreached dimension simply stays unchosen.
"""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.clause_fact_proposals import (
    clause_sentences,
    fact_dimensions,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_FACT_PROPOSAL_GRAMMARS,
    propose_supply_facts,
)

pytestmark = pytest.mark.private_standard

ROUTES = tuple(SUPPLY_FACT_PROPOSAL_GRAMMARS)

#: The routes sharing each declared grammar, keyed by the grammar's family. Two grammars are
#: shared by two routes each -- one rule stated across two subclauses -- so reachability is a
#: property of a grammar over its own routes rather than of a single route.
ROUTES_BY_GRAMMAR: dict[str, tuple[str, ...]] = {
    grammar.fact_kind: tuple(
        route for route, other in SUPPLY_FACT_PROPOSAL_GRAMMARS.items() if other == grammar
    )
    for grammar in SUPPLY_FACT_PROPOSAL_GRAMMARS.values()
}


def _fragment(draft: ImportedRuleDraft, route: str):
    return next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")


def _declared_dimensions(route: str) -> set[str]:
    """Every dimension the route's own declared rules claim to settle."""

    grammar = SUPPLY_FACT_PROPOSAL_GRAMMARS[route]
    return (
        {rule.dimension for rule in grammar.keyword_rules}
        | {name for rule in grammar.sequence_rules for name in rule.dimensions}
        | set(grammar.constants)
    )


@pytest.mark.parametrize("family", tuple(ROUTES_BY_GRAMMAR))
def test_every_declared_dimension_is_reached_on_the_real_fragments(
    extracted_draft: ImportedRuleDraft, family: str
) -> None:
    """A declared rule that reaches nothing is a keyword that has stopped matching.

    Per grammar and per dimension, never per statement: which dimensions come back chosen
    somewhere across the grammar's own routes is a property of the grammar, while which sentence
    settles which dimension is the clause's content and has no place here. A dimension the
    grammar deliberately does not reach carries no rule at all, so this holds in both
    directions -- an unreachable rule fails here, and a missing one is a gap the report names.
    """

    routes = ROUTES_BY_GRAMMAR[family]
    reached = {
        name
        for route in routes
        for proposal in propose_supply_facts(_fragment(extracted_draft, route), route)
        for name in proposal.chosen
    }
    unreached = sorted(_declared_dimensions(routes[0]) - reached)

    assert unreached == [], family


@pytest.mark.parametrize("route", ROUTES)
def test_a_reached_dimension_is_never_reached_with_a_value_outside_its_vocabulary(
    extracted_draft: ImportedRuleDraft, route: str
) -> None:
    """A proposal a reviewer cannot author is worse than no proposal at all."""

    vocabularies = {
        name: options
        for name, _kind, options in fact_dimensions(SUPPLY_FACT_PROPOSAL_GRAMMARS[route].fact_kind)
    }

    for proposal in propose_supply_facts(_fragment(extracted_draft, route), route):
        assert set(proposal.chosen) <= set(vocabularies), route
        assert set(proposal.chosen) | set(proposal.unchosen) == set(vocabularies), route
        for name, value in proposal.chosen.items():
            assert not vocabularies[name] or value in vocabularies[name], (route, name)


@pytest.mark.parametrize("route", ROUTES)
def test_every_sentence_of_every_route_yields_at_least_one_draft(
    extracted_draft: ImportedRuleDraft, route: str
) -> None:
    """The prefill's whole point: no sentence is left with a blank editor and no citation.

    Asserted as a relation between two counts derived at runtime -- drafts are at least
    sentences, because a sentence multiplying a dimension yields several -- so neither count is
    written down here.
    """

    fragment = _fragment(extracted_draft, route)
    sentences = clause_sentences(fragment)
    proposals = propose_supply_facts(fragment, route)

    assert sentences, route
    assert len(proposals) >= len(sentences), route
    assert {proposal.sentence_index for proposal in proposals} == {
        sentence.index for sentence in sentences
    }, route
    # Each draft cites exactly the node its own sentence came from, so its evidence digest
    # binds the node a reviewer read rather than the whole clause.
    by_index = {sentence.index: sentence for sentence in sentences}
    for proposal in proposals:
        (citation,) = proposal.node_references
        assert citation.fragment_id == fragment.id, route
        assert citation.node_order == by_index[proposal.sentence_index].node_order, route


@pytest.mark.parametrize("route", ROUTES)
def test_no_sentence_carries_a_structural_note_marker(
    extracted_draft: ImportedRuleDraft, route: str
) -> None:
    """The marker is structural, so a sentence that still carries one was not skipped."""

    for sentence in clause_sentences(_fragment(extracted_draft, route)):
        assert "NOTE" not in sentence.text, route


def test_proposing_twice_returns_the_same_drafts(extracted_draft: ImportedRuleDraft) -> None:
    """Deterministic and derived, which is why nothing is stored on the draft."""

    for route in ROUTES:
        fragment = _fragment(extracted_draft, route)
        assert propose_supply_facts(fragment, route) == propose_supply_facts(fragment, route), route


def test_no_proposal_is_recorded_anywhere_on_the_draft(
    extracted_draft: ImportedRuleDraft,
) -> None:
    """Computed on demand: a review binds its evidence and its fact's hash, never a proposal."""

    for route in ROUTES:
        assert propose_supply_facts(_fragment(extracted_draft, route), route), route

    assert not extracted_draft.clause_fact_reviews
    assert not extracted_draft.clause_fact_completions
