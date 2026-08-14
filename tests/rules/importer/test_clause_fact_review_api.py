"""Authoring facts, asserting completion, and the gate that requires both."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ClauseFactReview,
    HfAttenuationFact,
    SpdReductionFact,
    SupplyFact,
    evidence_sha256,
)
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
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    record_fact_completion,
    retract_clause_fact,
)

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
) -> HfAttenuationFact:
    """One authored statement citing the synthetic HF fragment's own first node."""

    return HfAttenuationFact(
        statement_index=statement_index,
        node_references=(_cited(draft, fragment_id),),
        obligation="requirement",
        dvc_gate="dvc_as",
        evidence_kind="test",
        threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        comparison_required=True,
    )


def _reduction_fact(draft: ImportedRuleDraft, *, fragment_id: str) -> SpdReductionFact:
    """One reduction statement, citing whichever fragment the caller names."""

    return SpdReductionFact(
        statement_index=0,
        node_references=(_cited(draft, fragment_id),),
        obligation="permission",
        supply_kind="non_mains",
        source_ovc="ovc_iii",
        target_ovc="ovc_ii",
        insulation_class="basic",
        degradable=True,
        monitoring_obligation="required",
        monitoring_reference=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
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
    injected = record_correction(
        draft,
        # Appended rather than replacing, so two calls build the two-review draft a
        # duplicate-reading test needs; every existing caller starts from no reviews.
        draft.model_copy(update={"clause_fact_reviews": (*draft.clause_fact_reviews, review)}),
        actor="tester",
        notes="inject a review the authoring API refuses",
    )
    return record_fact_completion(
        injected,
        rule_route=rule_route,
        fragment_id=f"raw-{rule_route}",
        actor="tester",
        notes="complete",
    )


def _blocked(draft: ImportedRuleDraft) -> set[str]:
    return {
        item.semantic_id
        for item in approval_blockers(draft)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }


@pytest.fixture
def hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=0)


@pytest.fixture
def second_hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationFact:
    """A genuinely second statement: another index *and* another reading.

    One dimension differs, because a statement that repeats a reading under a new index is now
    refused as a duplicate -- so a fixture that only bumped the index would be testing that
    refusal instead of the staleness it is here for.
    """

    return _hf_fact(draft_with_supply_fragments, statement_index=1).model_copy(
        update={"dvc_gate": "dvc_b"}
    )


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
