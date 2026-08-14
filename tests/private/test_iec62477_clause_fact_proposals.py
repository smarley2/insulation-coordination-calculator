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
    pair_tokens,
    scope_tokens,
)
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
    propose_supply_facts,
    supply_fact_proposal_grammars,
)
from tests.rules.importer.test_clause_fact_proposals import fragment_with_sentences

pytestmark = [pytest.mark.private_standard, pytest.mark.usefixtures("installed_grammars")]

#: Derived from the recipe's own public declarations rather than from the loaded grammar, so
#: collection does not depend on the private file being installed -- and so the parametrization is
#: the same set the loader's own agreement check demands of that file.
ROUTES = tuple(sorted(set(SUPPLY_FACT_FAMILY_BY_ROUTE) - LEGACY_BRANCH_AUTHORITY_RULE_IDS))

#: The families a declared grammar exists for, in route order.
FAMILIES = tuple(dict.fromkeys(SUPPLY_FACT_FAMILY_BY_ROUTE[route] for route in ROUTES))


def _routes_sharing_a_grammar(family: str) -> tuple[str, ...]:
    """The routes sharing one family's declared grammar.

    Two grammars are shared by two routes each -- one rule stated across two subclauses -- so
    reachability is a property of a grammar over its own routes rather than of a single route.
    """

    return tuple(route for route in ROUTES if SUPPLY_FACT_FAMILY_BY_ROUTE[route] == family)


def _fragment(draft: ImportedRuleDraft, route: str):
    return next(item for item in draft.raw_clause_fragments if item.id == f"raw-{route}")


def _declared_dimensions(route: str) -> set[str]:
    """Every dimension the route's own declared rules claim to settle."""

    grammar = supply_fact_proposal_grammars()[route]
    return (
        {rule.dimension for rule in grammar.keyword_rules}
        | {rule.dimension for rule in grammar.sequence_rules}
        | set(grammar.constants)
    )


@pytest.mark.parametrize("family", FAMILIES)
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

    routes = _routes_sharing_a_grammar(family)
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

    grammar = supply_fact_proposal_grammars()[route]
    # The grammar's own statement kind, not the family's: a family with variants has no single
    # dimension list, and the drafts this route proposes are of exactly one kind.
    declared = {
        name: (kind, options)
        for name, kind, options in fact_dimensions(grammar.fact_kind, grammar.variant)
    }

    for proposal in propose_supply_facts(_fragment(extracted_draft, route), route):
        assert set(proposal.chosen) <= set(declared), route
        assert set(proposal.chosen) | set(proposal.unchosen) == set(declared), route
        for name, value in proposal.chosen.items():
            kind, options = declared[name]
            # A scope dimension carries a set on the wire and a pair collection carries pairs, so
            # both are checked token by token: every token has to be authorable, and the
            # unrestricted reading names none.
            if kind == "scope":
                proposed: tuple[str, ...] = scope_tokens(value)
            elif kind == "pair_sequence":
                proposed = tuple(member for pair in pair_tokens(value) for member in pair)
            else:
                proposed = (value,)
            assert not options or set(proposed) <= set(options), (route, name)


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


def test_every_non_legacy_route_declares_a_grammar_of_its_own_family() -> None:
    """The real file agrees with the recipe's route-to-family declarations.

    The public suite asserts that the load-time check *fires*; only here can it be asserted that
    the maintainer's own file passes it. A route missing from the file silently loses every prefill
    while still looking authorable.
    """

    grammars = supply_fact_proposal_grammars()

    assert set(grammars) == set(ROUTES)
    assert all(
        grammar.fact_kind == SUPPLY_FACT_FAMILY_BY_ROUTE[route]
        for route, grammar in grammars.items()
    )


# --- the declared rules' own readings ------------------------------------------------
#
# Relocated here with the grammar they test (amendment A1). Their sentences are invented for these
# tests out of a family's own declared vocabulary, but what they assert is which reading a
# *declared rule* makes of a phrasing -- which is the licensed-derived half, so it cannot be
# asserted from the public tree at all.


def test_a_floor_sentence_proposes_no_insulation_class() -> None:
    """A reading the sentence does not make is worse than a blank field.

    A blank field cannot be confirmed by accident; a wrong value can. Both sentences below are
    invented for this test out of the reduction family's own declared vocabulary: one shapes a
    permission over two classes, the other names the two classes a floor is stated over. Only
    the first may propose a class.

    Also the A7 duplicate-expansion fix, on the real grammar: the permission's class dimension is a
    scope, so a sentence naming two classes yields **one** draft naming both rather than one per
    class.
    """

    route = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
    permission_sentence = (
        "Synthetic permission naming basic insulation and supplementary insulation."
    )
    floor_sentence = (
        "Synthetic floor naming double insulation and reinforced insulation, "
        "not less than basic insulation."
    )
    fragment = fragment_with_sentences(route, (permission_sentence, floor_sentence))

    proposals = propose_supply_facts(fragment, route)
    permission = [item for item in proposals if item.sentence_index == 0]
    floor = [item for item in proposals if item.sentence_index == 1]

    assert [item.chosen["insulation_classes"] for item in permission] == ["basic|supplementary"]
    assert floor
    assert all("insulation_classes" in item.unchosen for item in floor)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    (
        # The two explicit modal verbs.
        ("Synthetic reading which shall hold.", "requirement"),
        ("Synthetic reading which may hold.", "permission"),
        # Unmodalized present indicative, in three forms, binds.
        ("Synthetic reading is the stated one.", "requirement"),
        ("Synthetic readings are the stated ones.", "requirement"),
        ("Synthetic reading applies here.", "requirement"),
        # A permission that also carries a present-indicative verb must never read as binding:
        # this is the pair the whole exclusion list exists for.
        ("Synthetic readings are provided and may be designed for.", "permission"),
        ("Synthetic readings are supplied and may be determined.", "permission"),
        # Non-binding and capability modality settle nothing rather than binding.
        ("Synthetic reading should be the stated one.", None),
        ("Synthetic reading can be the stated one.", None),
        ("Synthetic reading might be the stated one.", None),
        # A negated present states an exemption; the grammar declines to read its obligation.
        ("Synthetic reading is not the stated one.", None),
        # No verb at all, and no stem to inherit from.
        ("synthetic fragment of a reading", None),
    ),
)
def test_the_obligation_rules_read_exactly_the_modality_the_sentence_states(
    sentence: str, expected: str | None
) -> None:
    """Every firing set was checked by hand against the document; these pin the shapes.

    A wrong obligation is the one proposal a maintainer is least likely to catch, because it
    reads plausibly either way. ``None`` means the sentence settles the dimension nowhere and it
    must stay unchosen -- never defaulted to the binding reading.
    """

    route = ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    (proposal,) = propose_supply_facts(fragment_with_sentences(route, (sentence,)), route)

    assert proposal.chosen.get("obligation") == expected
    assert ("obligation" in proposal.unchosen) is (expected is None)
