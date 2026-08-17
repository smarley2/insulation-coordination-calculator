"""Authoring facts, asserting completion, and the gate that requires both."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.clause_facts import (
    AttenuationEvidence,
    CitedNode,
    ClauseFactCompletion,
    ClauseFactReview,
    DimensionScope,
    HfAttenuationRequirementFact,
    OvercategoryStep,
    SpdReductionPermissionFact,
    SupplyFact,
    evidence_sha256,
)
from insulation_coordination.rules.importer.clauses import ClauseNode, RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    SUPPLY_CLAUSES,
    SUPPLY_FACT_FAMILY_BY_ROUTE,
    SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE,
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
    _require_declared_fact_families,
    _require_declared_supply_kinds,
    propose_supply_facts,
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    clause_fact_statement_dismissed,
    dismiss_clause_fact_statement,
    fact_set_sha256,
    record_fact_completion,
    retract_clause_fact,
    retract_clause_fact_dismissal,
    uncovered_clause_fact_statements,
)
from tests.conftest import _logged
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import SOURCE, _fragment
from tests.rules.importer.test_clause_fact_proposals import scope_of

# draft_with_supply_fragments is a shared fixture; see tests/conftest.py.

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
HF_FRAGMENT_ID = f"raw-{HF_ROUTE}"
MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
NON_MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"


def _cited(draft: ImportedRuleDraft, fragment_id: str) -> CitedNode:
    """A citation of one fragment's own first node, matching its current content."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == fragment_id)
    node = fragment.nodes[0]
    return CitedNode(
        fragment_id=fragment.id,
        node_order=node.order,
        node_sha256=canonical_model_sha256(node),
    )


def _hf_fact(
    draft: ImportedRuleDraft,
    *,
    statement_index: int,
    fragment_id: str = HF_FRAGMENT_ID,
    evidence_kind: str = "test",
) -> HfAttenuationRequirementFact:
    """One authored demonstration requirement citing the synthetic HF fragment's own first node.

    The family's requirement variant rather than its permission, because it is the one carrying a
    scope, a boolean and a route reference between them -- so one statement exercises every shape the
    surfaces under test have to round-trip.

    The evidence scope is built through the constructor rather than patched in with ``model_copy``: a
    scope reaching a fact unvalidated is a fact whose digest covers a value its own family never
    declared.
    """

    return HfAttenuationRequirementFact(
        statement_index=statement_index,
        node_references=(_cited(draft, fragment_id),),
        obligation="requirement",
        evidence_kind=scope_of(evidence_kind),  # type: ignore[arg-type]
        threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        comparison_required=True,
    )


def _reduction_fact(draft: ImportedRuleDraft, *, fragment_id: str) -> SpdReductionPermissionFact:
    """One reduction statement, citing whichever fragment the caller names."""

    return SpdReductionPermissionFact(
        statement_index=0,
        node_references=(_cited(draft, fragment_id),),
        obligation="permission",
        supply_kind="non_mains",
        permitted_steps=(OvercategoryStep(source_ovc="ovc_iii", target_ovc="ovc_ii"),),
        insulation_classes=DimensionScope.of("basic"),
    )


def _hand_built(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    fact: SupplyFact,
    fact_sha256: str | None = None,
) -> ImportedRuleDraft:
    """A draft carrying one review the authoring API refuses, completed for that route.

    Every digest in it is honestly computed unless the caller says otherwise, which is the point:
    the gate has to refuse on the fact's identity, because nothing about its hashes is stale.

    The completion record is hand-built for the same reason the review is. ``record_fact_completion``
    now also refuses a route whose known statements no authored fact covers, and a review resting
    only on another clause covers none of its own -- so going through the API here would refuse
    before the gate this helper exists to exercise ever ran.
    """

    review = ClauseFactReview(
        rule_route=rule_route,
        statement_index=fact.statement_index,
        fact=fact,
        fact_sha256=fact_sha256 or canonical_model_sha256(fact),
        evidence_sha256=evidence_sha256(fact.node_references),
        actor="tester",
        recorded_at=datetime.now(UTC),
        notes="hand built",
    )
    # Appended rather than replacing, so two calls build the two-review draft a duplicate-reading
    # test needs; every existing caller starts from no reviews.
    reviews = (*draft.clause_fact_reviews, review)
    fragment = next(item for item in draft.raw_clause_fragments if item.id == f"raw-{rule_route}")
    completion = ClauseFactCompletion(
        rule_route=rule_route,
        fragment_id=fragment.id,
        fragment_sha256=fragment.raw_sha256,
        fact_set_sha256=fact_set_sha256(
            tuple(item.fact for item in reviews if item.rule_route == rule_route)
        ),
        actor="tester",
        recorded_at=datetime.now(UTC),
        notes="hand built completion",
    )
    return record_correction(
        draft,
        draft.model_copy(
            update={
                "clause_fact_reviews": reviews,
                "clause_fact_completions": (
                    *(
                        item
                        for item in draft.clause_fact_completions
                        if item.rule_route != rule_route
                    ),
                    completion,
                ),
            }
        ),
        actor="tester",
        notes="inject a review and completion the authoring API refuses",
    )


def _blocked(draft: ImportedRuleDraft) -> set[str]:
    return {
        item.semantic_id
        for item in approval_blockers(draft)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }


@pytest.fixture
def hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationRequirementFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=0)


@pytest.fixture
def second_hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationRequirementFact:
    """A genuinely second statement: another index *and* another reading.

    One dimension differs, because a statement that repeats a reading under a new index is now
    refused as a duplicate -- so a fixture that only bumped the index would be testing that
    refusal instead of the staleness it is here for.
    """

    return _hf_fact(draft_with_supply_fragments, statement_index=1, evidence_kind="simulation")


def test_a_route_without_facts_blocks_approval(draft_with_supply_fragments) -> None:
    codes = {item.code for item in approval_blockers(draft_with_supply_fragments)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_facts_without_a_completion_record_still_block(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Authoring fewer statements than the source states would silently narrow the rule."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )

    codes = {item.code for item in approval_blockers(draft)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_facts_plus_completion_clear_the_gate_for_that_route(
    draft_with_supply_fragments, hf_fact
) -> None:
    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    draft = record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete for this route",
    )

    assert HF_ROUTE not in _blocked(draft)


def test_the_legacy_branch_authority_route_is_never_gated(draft_with_supply_fragments) -> None:
    """Its contract is an ordinal category comparison no honest reviewed fact can express."""

    assert LEGACY_BRANCH_AUTHORITY_RULE_IDS
    assert not _blocked(draft_with_supply_fragments) & LEGACY_BRANCH_AUTHORITY_RULE_IDS


def test_completion_recorded_before_a_later_fact_goes_stale(
    draft_with_supply_fragments, hf_fact, second_hf_fact
) -> None:
    """The completion binds the fact-set digest, so authoring another fact invalidates it."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    draft = record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete",
    )
    draft = author_clause_fact(
        draft,
        rule_route=HF_ROUTE,
        fact=second_hf_fact,
        actor="tester",
        notes="one more",
    )

    codes = {item.code for item in approval_blockers(draft)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_authoring_the_same_statement_index_twice_replaces_it(
    draft_with_supply_fragments, hf_fact
) -> None:
    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="first",
    )
    corrected = hf_fact.model_copy(update={"comparison_required": False})
    draft = author_clause_fact(
        draft,
        rule_route=HF_ROUTE,
        fact=corrected,
        actor="tester",
        notes="corrected",
    )

    matching = [
        item
        for item in draft.clause_fact_reviews
        if item.rule_route == HF_ROUTE and item.statement_index == hf_fact.statement_index
    ]

    assert len(matching) == 1
    assert matching[0].fact.comparison_required is False


def test_retracting_a_statement_reopens_the_gate_for_its_route(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The completion is left to go stale rather than repaired: completeness is re-asserted
    by the reviewer, never inferred from the deletion that invalidated it."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    draft = record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete",
    )
    assert HF_ROUTE not in _blocked(draft)

    draft = retract_clause_fact(
        draft,
        rule_route=HF_ROUTE,
        statement_index=hf_fact.statement_index,
        actor="tester",
        notes="retracted",
    )

    assert not draft.clause_fact_reviews
    assert draft.clause_fact_completions
    assert HF_ROUTE in _blocked(draft)


def test_retracting_an_unknown_statement_is_refused(draft_with_supply_fragments) -> None:
    """A retraction that removed nothing would append an audited correction of nothing."""

    with pytest.raises(ValueError, match="no authored statement"):
        retract_clause_fact(
            draft_with_supply_fragments,
            rule_route=HF_ROUTE,
            statement_index=0,
            actor="tester",
            notes="nothing there",
        )


def test_retract_actor_and_notes_are_required(draft_with_supply_fragments, hf_fact) -> None:
    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )

    with pytest.raises(ApprovalError):
        retract_clause_fact(
            draft,
            rule_route=HF_ROUTE,
            statement_index=hf_fact.statement_index,
            actor=" ",
            notes="",
        )


def test_actor_and_notes_are_required(draft_with_supply_fragments, hf_fact) -> None:
    with pytest.raises(ApprovalError):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=HF_ROUTE,
            fact=hf_fact,
            actor=" ",
            notes="",
        )


def test_a_fact_citing_a_node_that_does_not_exist_is_refused(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Evidence must be real, or the digest binds nothing."""

    invented = hf_fact.model_copy(
        update={
            "node_references": (hf_fact.node_references[0].model_copy(update={"node_order": 99}),)
        }
    )

    with pytest.raises(ValueError):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=HF_ROUTE,
            fact=invented,
            actor="tester",
            notes="bad citation",
        )


def test_every_gated_route_declares_the_family_its_facts_must_belong_to() -> None:
    """A route the map forgets could be certified by a fact of any family at all."""

    assert set(SUPPLY_FACT_FAMILY_BY_ROUTE) == {spec.semantic_id for spec in SUPPLY_CLAUSES}


def test_a_clause_spec_with_no_fact_family_is_refused_at_import() -> None:
    """Otherwise a forgotten entry deadlocks approval instead of failing where it was made.

    The gate blocks the route for want of facts while authoring one is refused as an undeclared
    route, so the draft becomes unapprovable with nothing naming the cause. Importing the recipe
    runs this check over the real pair, so the deadlock cannot be shipped.
    """

    invented = SUPPLY_CLAUSES[0].model_copy(update={"semantic_id": "invented.route"})

    with pytest.raises(ValueError, match="invented.route"):
        _require_declared_fact_families((*SUPPLY_CLAUSES, invented), SUPPLY_FACT_FAMILY_BY_ROUTE)


def test_a_statement_repeating_an_authored_reading_is_refused(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Pressing Author twice on one draft used to record the same reading under two indices.

    Silently, and repeatably: a reviewer reached statement 10 without noticing they had authored
    one reading ten times, and the route certified as reviewed with a fact set whose size claimed
    ten readings. The refusal names the index that already carries it, so the reviewer can go and
    read that statement instead of guessing which of ten is the original.
    """

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    repeat = hf_fact.model_copy(update={"statement_index": 1})

    with pytest.raises(ValueError, match="already authored as statement 0"):
        author_clause_fact(draft, rule_route=HF_ROUTE, fact=repeat, actor="tester", notes="again")


def test_replacing_a_statement_at_its_own_index_stays_free(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The sanctioned replace path: a statement is never compared against itself."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )

    replaced = author_clause_fact(
        draft, rule_route=HF_ROUTE, fact=hf_fact, actor="tester", notes="re-authored"
    )

    reviews = [item for item in replaced.clause_fact_reviews if item.rule_route == HF_ROUTE]
    assert [item.statement_index for item in reviews] == [0]


def test_two_statements_may_share_every_dimension_on_different_nodes(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Different cited nodes make a different evidentiary claim, not a duplicate reading.

    Two parts of a clause can state the same thing, and each is its own statement resting on its
    own node. Whether their projected branches then collide is
    ``_require_distinct_branches``'s judgement, not this predicate's.
    """

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )
    elsewhere = hf_fact.model_copy(
        update={
            "statement_index": 1,
            "node_references": (_cited(draft, HF_FRAGMENT_ID), _cited(draft, f"raw-{MAINS_ROUTE}")),
        }
    )

    accepted = author_clause_fact(
        draft, rule_route=HF_ROUTE, fact=elsewhere, actor="tester", notes="another node"
    )

    reviews = [item for item in accepted.clause_fact_reviews if item.rule_route == HF_ROUTE]
    assert [item.statement_index for item in reviews] == [0, 1]


def test_a_hand_built_duplicate_reading_still_blocks_the_route(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The gate cannot trust the authoring API to have been the only writer."""

    draft = _hand_built(draft_with_supply_fragments, rule_route=HF_ROUTE, fact=hf_fact)
    draft = _hand_built(
        draft, rule_route=HF_ROUTE, fact=hf_fact.model_copy(update={"statement_index": 1})
    )

    assert HF_ROUTE in _blocked(draft)


def test_a_fact_of_the_wrong_family_cannot_be_authored_on_a_route(
    draft_with_supply_fragments,
) -> None:
    """An HF attenuation fact cannot state a category step, so it cannot stand for reduction.

    It cites the mains fragment's own node, so the family is the only thing wrong with it.
    """

    foreign_family = _hf_fact(
        draft_with_supply_fragments, statement_index=0, fragment_id=f"raw-{MAINS_ROUTE}"
    )

    with pytest.raises(ValueError, match="hf_attenuation"):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=MAINS_ROUTE,
            fact=foreign_family,
            actor="tester",
            notes="wrong family",
        )


def test_a_hand_built_wrong_family_review_still_blocks_the_route(
    draft_with_supply_fragments,
) -> None:
    """The gate cannot trust the authoring API to have been the only writer."""

    foreign_family = _hf_fact(
        draft_with_supply_fragments, statement_index=0, fragment_id=f"raw-{MAINS_ROUTE}"
    )

    draft = _hand_built(draft_with_supply_fragments, rule_route=MAINS_ROUTE, fact=foreign_family)

    assert MAINS_ROUTE in _blocked(draft)


def test_a_fact_resting_only_on_another_clause_cannot_be_authored(
    draft_with_supply_fragments,
) -> None:
    """Otherwise reprinting the cited clause blocks a route whose rule it never stated."""

    elsewhere = _reduction_fact(draft_with_supply_fragments, fragment_id=HF_FRAGMENT_ID)

    with pytest.raises(ValueError, match=f"raw-{NON_MAINS_ROUTE}"):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=NON_MAINS_ROUTE,
            fact=elsewhere,
            actor="tester",
            notes="cites someone else's clause only",
        )


def test_a_hand_built_review_resting_only_on_another_clause_still_blocks(
    draft_with_supply_fragments,
) -> None:
    elsewhere = _reduction_fact(draft_with_supply_fragments, fragment_id=HF_FRAGMENT_ID)

    draft = _hand_built(draft_with_supply_fragments, rule_route=NON_MAINS_ROUTE, fact=elsewhere)

    assert NON_MAINS_ROUTE in _blocked(draft)


def test_a_fact_may_cite_a_second_fragment_as_well_as_its_own(
    draft_with_supply_fragments,
) -> None:
    """The requirement is 'at least one', not 'all': a statement may rest on two clauses."""

    both = _reduction_fact(draft_with_supply_fragments, fragment_id=f"raw-{NON_MAINS_ROUTE}")
    both = both.model_copy(
        update={
            "node_references": (
                *both.node_references,
                _cited(draft_with_supply_fragments, HF_FRAGMENT_ID),
            )
        }
    )

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=NON_MAINS_ROUTE,
        fact=both,
        actor="tester",
        notes="rests on two clauses",
    )
    draft = record_fact_completion(
        draft,
        rule_route=NON_MAINS_ROUTE,
        fragment_id=f"raw-{NON_MAINS_ROUTE}",
        actor="tester",
        notes="complete",
    )

    assert NON_MAINS_ROUTE not in _blocked(draft)


def test_an_undeclared_rule_route_is_refused_rather_than_recorded(
    draft_with_supply_fragments, hf_fact
) -> None:
    """The gate only walks declared routes, so a typo would file a review nothing ever reads."""

    with pytest.raises(ValueError, match="undeclared rule route"):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=f"{HF_ROUTE}.typo",
            fact=hf_fact,
            actor="tester",
            notes="misfiled",
        )


def test_a_review_whose_fact_hash_is_not_its_facts_blocks(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Task 8's dialog becomes a second writer of fact_sha256, so the gate has to read it.

    The symmetry ``axis_review_is_current`` already keeps for a review's ``proposal_sha256``.
    """

    draft = _hand_built(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        fact_sha256="0" * 64,
    )

    assert HF_ROUTE in _blocked(draft)


def test_a_completion_must_name_its_own_route_fragment(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Completion binds a fragment hash to a route; a foreign fragment binds the wrong region."""

    draft = author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=hf_fact,
        actor="tester",
        notes="authored",
    )

    with pytest.raises(ValueError, match=f"raw-{HF_ROUTE}"):
        record_fact_completion(
            draft,
            rule_route=HF_ROUTE,
            fragment_id=f"raw-{MAINS_ROUTE}",
            actor="tester",
            notes="complete against the wrong clause",
        )


# --- the completion guard -------------------------------------------------------------


def _with_fragment(draft: ImportedRuleDraft, fragment: RawClauseFragment) -> ImportedRuleDraft:
    """The same draft with one of its clause fragments replaced, and its audit record restamped."""

    fragments = tuple(
        fragment if item.id == fragment.id else item for item in draft.raw_clause_fragments
    )
    return _logged(draft.model_copy(update={"raw_clause_fragments": fragments}))


def _shaped_fragment(semantic_id: str, rows: tuple[tuple[str, str], ...]) -> RawClauseFragment:
    """A synthetic fragment of the given node kinds and invented texts, in order.

    Invented neutral text under the real fragment id, exactly as the shared fixture's is. The only
    thing any of it says is structural: which node is a paragraph, which are bullets, and where a
    sentence ends.
    """

    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=text,
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order, (kind, text) in enumerate(rows)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}", raw_sha256="0" * 64, nodes=nodes, tokens=(), source=SOURCE
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


@pytest.fixture
def three_node_hf_draft(
    draft_with_supply_fragments: ImportedRuleDraft, synthetic_private_grammars: Path
) -> ImportedRuleDraft:
    """Every supply fragment, with the attenuation route's carrying three single-sentence nodes.

    Three nodes rather than one, because a one-node fragment cannot tell a guard that counts
    obligations from one that counts routes.

    The guard derives its obligations from proposals, and a route proposes nothing at all without a
    grammar installed -- which, since amendment A1 moved every grammar beside the licensed material,
    is the public checkout's normal state. So the guard's own tests install the synthetic one; see
    ``synthetic_private_grammars``. Without it these tests pass vacuously, which is worse than
    failing.
    """

    return _with_fragment(draft_with_supply_fragments, _fragment(HF_ROUTE, kind="bullet", count=3))


def _author_hf_citing(
    draft: ImportedRuleDraft, *, statement_index: int, node_orders: tuple[int, ...]
) -> ImportedRuleDraft:
    """One attenuation statement resting on exactly the named nodes of its own fragment."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    citations = tuple(
        CitedNode(
            fragment_id=fragment.id,
            node_order=node.order,
            node_sha256=canonical_model_sha256(node),
        )
        for node in fragment.nodes
        if node.order in node_orders
    )
    # One dimension varies with the index, so sibling statements are distinct readings rather
    # than duplicates the authoring API refuses.
    fact = _hf_fact(
        draft,
        statement_index=statement_index,
        evidence_kind="test" if statement_index % 2 else "simulation",
    )
    return author_clause_fact(
        draft,
        rule_route=HF_ROUTE,
        fact=fact.model_copy(update={"node_references": citations}),
        actor="tester",
        notes=f"the statement resting on {node_orders}",
    )


def test_an_uncovered_known_statement_prohibits_completion(three_node_hf_draft) -> None:
    """Amendment A5: a route with several known statements cannot be completed with one authored."""

    draft = _author_hf_citing(three_node_hf_draft, statement_index=0, node_orders=(0,))

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == (
        "the statement resting on clause node(s) 1",
        "the statement resting on clause node(s) 2",
    )
    with pytest.raises(ApprovalError, match="node\\(s\\) 1"):
        record_fact_completion(
            draft,
            rule_route=HF_ROUTE,
            fragment_id=HF_FRAGMENT_ID,
            actor="tester",
            notes="complete on one of three",
        )
    assert HF_ROUTE in _blocked(draft)


def test_no_uncovered_statement_permits_completion_without_constituting_it(
    three_node_hf_draft,
) -> None:
    """The distinction the guard must not dissolve: a lower bound on review, never its definition.

    Consuming every known proposal makes the assertion *available*. It is not the assertion, because
    no proposal count can say that no statement the engine never suggested was missed -- so the gate
    still blocks until the maintainer records completion themselves.
    """

    draft = three_node_hf_draft
    for index in range(3):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(index,))

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()
    # Every known statement covered, and the route is still blocked: nobody has asserted anything.
    assert HF_ROUTE in _blocked(draft)
    assert not any(item.rule_route == HF_ROUTE for item in draft.clause_fact_completions)

    completed = record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete, and asserted as such",
    )

    assert HF_ROUTE not in _blocked(completed)


def test_a_corrected_fact_covers_the_statement_it_was_authored_for(
    three_node_hf_draft,
) -> None:
    """Amendment A5-C, first direction: coverage binds to the statement, never to its values.

    A maintainer who reads the source, finds a machine suggestion wrong and authors corrected
    dimensions has reviewed that statement. Binding coverage to proposal-value equality would leave
    it permanently uncovered *because* they exercised judgement, which inverts the authority rule.
    """

    draft = three_node_hf_draft
    for index in range(3):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(index,))
    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()

    # Every dimension the reviewer can change, changed, on the same cited evidence.
    corrected = next(
        item.fact for item in draft.clause_fact_reviews if item.statement_index == 0
    ).model_copy(
        update={
            "obligation": "permission",
            "evidence_kind": DimensionScope[AttenuationEvidence].of("calculation"),
            "comparison_required": False,
        }
    )
    draft = author_clause_fact(
        draft,
        rule_route=HF_ROUTE,
        fact=corrected,
        actor="tester",
        notes="the machine suggestion was wrong",
    )

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()
    record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete, with one reading corrected",
    )


def test_one_authored_fact_never_covers_two_distinct_statements(three_node_hf_draft) -> None:
    """Amendment A5-C, second direction, asserted both ways round.

    The statement the fact cites is covered, and the two it does not cite are not -- so a route
    cannot be certified with fewer statements than the clause is known to carry.
    """

    draft = _author_hf_citing(three_node_hf_draft, statement_index=0, node_orders=(1,))

    uncovered = uncovered_clause_fact_statements(draft, HF_ROUTE)

    assert "the statement resting on clause node(s) 1" not in uncovered
    assert uncovered == (
        "the statement resting on clause node(s) 0",
        "the statement resting on clause node(s) 2",
    )


def _sentence_indexes(draft: ImportedRuleDraft) -> tuple[int, ...]:
    """Every sentence index the attenuation route's drafts carry, to show a renumbering happened."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    return tuple(item.sentence_index for item in propose_supply_facts(fragment, HF_ROUTE))


def test_coverage_survives_a_sentence_renumbering(three_node_hf_draft) -> None:
    """Why the anchor is cited evidence and not the sentence index.

    The clause-region slice widens the extracted regions, so an earlier node gaining a sentence
    renumbers every sentence after it. A statement whose own cited node is untouched must still be
    covered afterwards; anchoring on the sentence index would silently orphan it.
    """

    draft = _author_hf_citing(three_node_hf_draft, statement_index=0, node_orders=(1,))
    before = uncovered_clause_fact_statements(draft, HF_ROUTE)

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    renumbered = fragment.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={"raw_text": "Synthetic neutral opener. Synthetic neutral second half."}
                )
                if node.order == 0
                else node
                for node in fragment.nodes
            )
        }
    )
    moved = _with_fragment(
        draft, renumbered.model_copy(update={"raw_sha256": canonical_model_sha256(renumbered)})
    )

    # Node 0 now carries two sentences, so node 1's sentence is numbered one later than before.
    assert _sentence_indexes(moved) != _sentence_indexes(draft)
    assert uncovered_clause_fact_statements(moved, HF_ROUTE) == before


def test_a_context_only_node_is_not_an_outstanding_obligation(
    draft_with_supply_fragments,
    synthetic_private_grammars: Path,
) -> None:
    """Amendment A4: a clause's opening sentence scopes what follows and selects no branch.

    So it is evidence and a modality source, not a statement: no draft is offered for it, no
    obligation is counted for it, and a route whose bullets are all authored completes without
    anybody inventing a statement for the opener.

    Asserted end to end rather than at the proposer, because it is the guard that would block
    completion for ever on an obligation nobody can cover.
    """

    draft = _with_fragment(
        draft_with_supply_fragments,
        _shaped_fragment(
            HF_ROUTE,
            (
                ("paragraph", "Synthetic neutral opener scoping the items that follow:"),
                ("bullet", "synthetic neutral first item"),
                ("bullet", "synthetic neutral second item"),
            ),
        ),
    )
    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    # No draft for the opener at all, which is where A4 is now enforced.
    assert {
        item.node_references[0].node_order for item in propose_supply_facts(fragment, HF_ROUTE)
    } == {1, 2}
    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == (
        "the statement resting on clause node(s) 1",
        "the statement resting on clause node(s) 2",
    )

    # Each bullet's statement cites the opener as well as its own node, which is the shape a
    # statement completing an opener has: the opener's movement re-opens the dependent statement.
    for index, node_order in enumerate((1, 2)):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(0, node_order))

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()
    record_fact_completion(
        draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete; the opener states no branch of its own",
    )


# --- route-determined supply kind ----------------------------------------------------


def test_a_fact_whose_supply_kind_contradicts_its_route_is_refused(
    draft_with_supply_fragments,
) -> None:
    """The mains route states mains; a non-mains reading cannot certify it.

    ``_reduction_fact`` always authors ``supply_kind="non_mains"``, and it cites the mains
    route's own fragment, so supply kind is the only thing wrong with it.
    """

    contradicting = _reduction_fact(draft_with_supply_fragments, fragment_id=f"raw-{MAINS_ROUTE}")

    with pytest.raises(ValueError, match="supply_kind"):
        author_clause_fact(
            draft_with_supply_fragments,
            rule_route=MAINS_ROUTE,
            fact=contradicting,
            actor="tester",
            notes="wrong supply kind for this route",
        )


def test_a_hand_built_contradicting_supply_kind_review_still_blocks_the_route(
    draft_with_supply_fragments,
) -> None:
    """The gate cannot trust the authoring API to have been the only writer."""

    contradicting = _reduction_fact(draft_with_supply_fragments, fragment_id=f"raw-{MAINS_ROUTE}")

    draft = _hand_built(draft_with_supply_fragments, rule_route=MAINS_ROUTE, fact=contradicting)

    assert MAINS_ROUTE in _blocked(draft)


def test_supply_kind_expectations_cover_exactly_the_routes_whose_family_states_one() -> None:
    """System voltage's two subclauses and each SPD reduction subclause, and no others."""

    assert set(SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE) == {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        MAINS_ROUTE,
        NON_MAINS_ROUTE,
    }


def test_a_route_whose_family_carries_supply_kind_needs_a_declared_expectation() -> None:
    """Otherwise a forgotten entry leaves a route open to either supply kind, silently.

    The same deadlock shape ``_require_declared_fact_families`` guards for a forgotten family:
    caught at import over the real declarations, so it cannot ship unnoticed.
    """

    missing = {
        route: value
        for route, value in SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE.items()
        if route != MAINS_ROUTE
    }

    with pytest.raises(ValueError, match="disagree"):
        _require_declared_supply_kinds(SUPPLY_FACT_FAMILY_BY_ROUTE, missing)


# --- a sentence this route models nothing of -------------------------------------------


def _hf_citation(draft: ImportedRuleDraft, node_order: int) -> tuple[CitedNode, ...]:
    """The attenuation fragment's node, cited as its own draft cites it."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    node = next(item for item in fragment.nodes if item.order == node_order)
    return (
        CitedNode(
            fragment_id=fragment.id,
            node_order=node.order,
            node_sha256=canonical_model_sha256(node),
        ),
    )


def _dismiss_hf(draft: ImportedRuleDraft, node_order: int, **overrides: str) -> ImportedRuleDraft:
    arguments = {"actor": "tester", "notes": "another rule's basis; this route models none of it"}
    arguments.update(overrides)
    return dismiss_clause_fact_statement(
        draft, rule_route=HF_ROUTE, nodes=_hf_citation(draft, node_order), **arguments
    )


def test_a_statement_stating_nothing_this_route_models_stops_being_an_obligation(
    three_node_hf_draft,
) -> None:
    """The widened regions made unauthorable sentences reachable; their drafts never close.

    A route whose pane permanently reads as outstanding makes completion an assertion over a list
    that always looks unfinished. Recording the reviewer's decision removes the obligation without
    removing the record of it -- and still only *permits* completion, which the maintainer asserts.
    """

    draft = three_node_hf_draft
    for index, node_order in enumerate((0, 1)):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(node_order,))
    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == (
        "the statement resting on clause node(s) 2",
    )

    draft = _dismiss_hf(draft, 2)

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()
    assert clause_fact_statement_dismissed(draft, HF_ROUTE, _hf_citation(draft, 2)) is True
    # Attributable, and carrying the reason: an audit record, not a filter.
    (dismissal,) = draft.clause_fact_dismissals
    assert (dismissal.rule_route, dismissal.actor) == (HF_ROUTE, "tester")
    assert dismissal.notes
    # A5 is intact: the guard is clear and the route is still blocked until the assertion is made.
    assert HF_ROUTE in _blocked(draft)
    assert HF_ROUTE not in _blocked(
        record_fact_completion(
            draft,
            rule_route=HF_ROUTE,
            fragment_id=HF_FRAGMENT_ID,
            actor="tester",
            notes="complete: two statements, and one sentence this route models nothing of",
        )
    )


def test_a_decision_never_outlives_the_sentence_it_was_made_about(three_node_hf_draft) -> None:
    """Anchored on the sentence's evidence identity, so its text moving brings the obligation back.

    A decision that survived the evidence would be a permanent hole in the guard, opened by one press
    against wording nobody has read since.
    """

    draft = three_node_hf_draft
    for index, node_order in enumerate((0, 1)):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(node_order,))
    draft = _dismiss_hf(draft, 2)
    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    rewritten = fragment.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"raw_text": "Synthetic neutral replacement sentence."})
                if node.order == 2
                else node
                for node in fragment.nodes
            )
        }
    )
    moved = _with_fragment(
        draft, rewritten.model_copy(update={"raw_sha256": canonical_model_sha256(rewritten)})
    )

    assert uncovered_clause_fact_statements(moved, HF_ROUTE) == (
        "the statement resting on clause node(s) 2",
    )
    assert clause_fact_statement_dismissed(moved, HF_ROUTE, _hf_citation(moved, 2)) is False
    assert HF_ROUTE in _blocked(moved)


def test_a_decision_must_name_a_statement_the_route_actually_proposes(
    three_node_hf_draft,
) -> None:
    """Otherwise a route could be quietened by recording decisions about nothing."""

    invented = (CitedNode(fragment_id=HF_FRAGMENT_ID, node_order=7, node_sha256="b" * 64),)

    with pytest.raises(ValueError, match="proposes no statement"):
        dismiss_clause_fact_statement(
            three_node_hf_draft,
            rule_route=HF_ROUTE,
            nodes=invented,
            actor="tester",
            notes="a statement nobody suggested",
        )


def test_a_decision_and_an_authored_statement_are_not_recorded_about_one_sentence(
    three_node_hf_draft,
) -> None:
    """One sentence never carries a reading *and* the claim that there was nothing to read."""

    draft = _author_hf_citing(three_node_hf_draft, statement_index=0, node_orders=(0,))

    with pytest.raises(ValueError, match="rather than finding nothing"):
        _dismiss_hf(draft, 0)

    draft = _dismiss_hf(draft, 1)
    with pytest.raises(ValueError, match="already dismissed"):
        _dismiss_hf(draft, 1)


def test_a_decision_is_attributable_or_it_is_not_recorded(three_node_hf_draft) -> None:
    """The minimum an audit record is: who decided, and what they read."""

    for missing in ({"actor": " "}, {"notes": " "}):
        with pytest.raises(ApprovalError, match="actor and notes"):
            _dismiss_hf(three_node_hf_draft, 2, **missing)


def test_a_decision_is_retractable_and_its_statement_returns(three_node_hf_draft) -> None:
    """A reviewer who reads a sentence again and finds a statement in it must be able to say so."""

    draft = three_node_hf_draft
    for index, node_order in enumerate((0, 1)):
        draft = _author_hf_citing(draft, statement_index=index, node_orders=(node_order,))
    draft = _dismiss_hf(draft, 2)

    withdrawn = retract_clause_fact_dismissal(
        draft,
        rule_route=HF_ROUTE,
        nodes=_hf_citation(draft, 2),
        actor="tester",
        notes="read again; it states a branch after all",
    )

    assert withdrawn.clause_fact_dismissals == ()
    assert uncovered_clause_fact_statements(withdrawn, HF_ROUTE) == (
        "the statement resting on clause node(s) 2",
    )
    with pytest.raises(ValueError, match="has not dismissed"):
        retract_clause_fact_dismissal(
            withdrawn,
            rule_route=HF_ROUTE,
            nodes=_hf_citation(withdrawn, 2),
            actor="tester",
            notes="nothing to withdraw",
        )


def test_a_route_cannot_be_certified_by_finding_nothing_in_all_of_it(three_node_hf_draft) -> None:
    """The floor under the whole mechanism: a route still has to state something.

    Every sentence dismissed clears the guard's own count, and the route is still refused, because a
    route that projects a rule from no reviewed statement is not a reviewed route.
    """

    draft = three_node_hf_draft
    for node_order in (0, 1, 2):
        draft = _dismiss_hf(draft, node_order)

    assert uncovered_clause_fact_statements(draft, HF_ROUTE) == ()
    assert HF_ROUTE in _blocked(draft)
    with pytest.raises(ApprovalError, match="no authored facts"):
        record_fact_completion(
            draft,
            rule_route=HF_ROUTE,
            fragment_id=HF_FRAGMENT_ID,
            actor="tester",
            notes="nothing here at all",
        )
