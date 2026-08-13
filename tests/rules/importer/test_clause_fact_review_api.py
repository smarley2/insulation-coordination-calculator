"""Authoring facts, asserting completion, and the gate that requires both."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.approval import ApprovalError, approval_blockers
from insulation_coordination.rules.importer.clause_facts import CitedNode, HfAttenuationFact
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    LEGACY_BRANCH_AUTHORITY_RULE_IDS,
)
from insulation_coordination.rules.importer.review import (
    author_clause_fact,
    record_fact_completion,
)

# draft_with_supply_fragments is a shared fixture; see tests/conftest.py.

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
HF_FRAGMENT_ID = f"raw-{HF_ROUTE}"


def _hf_fact(draft: ImportedRuleDraft, *, statement_index: int) -> HfAttenuationFact:
    """One authored statement citing the synthetic HF fragment's own first node."""

    fragment = next(item for item in draft.raw_clause_fragments if item.id == HF_FRAGMENT_ID)
    node = fragment.nodes[0]
    return HfAttenuationFact(
        statement_index=statement_index,
        node_references=(
            CitedNode(
                fragment_id=fragment.id,
                node_order=node.order,
                node_sha256=canonical_model_sha256(node),
            ),
        ),
        obligation="requirement",
        dvc_gate="dvc_as",
        evidence_kind="test",
        threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        comparison_required=True,
    )


@pytest.fixture
def hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=0)


@pytest.fixture
def second_hf_fact(draft_with_supply_fragments: ImportedRuleDraft) -> HfAttenuationFact:
    return _hf_fact(draft_with_supply_fragments, statement_index=1)


def test_a_route_without_facts_blocks_approval(draft_with_supply_fragments) -> None:
    codes = {item.code for item in approval_blockers(draft_with_supply_fragments)}

    assert "CLAUSE_FACT_REVIEW_REQUIRED" in codes


def test_facts_without_a_completion_record_still_block(
    draft_with_supply_fragments, hf_fact
) -> None:
    """Authoring three statements where the source states four would silently narrow the rule."""

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

    blocked = {
        item.semantic_id
        for item in approval_blockers(draft)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }

    assert HF_ROUTE not in blocked


def test_the_legacy_branch_authority_route_is_never_gated(draft_with_supply_fragments) -> None:
    """Its contract is an ordinal category comparison no honest reviewed fact can express."""

    blocked = {
        item.semantic_id
        for item in approval_blockers(draft_with_supply_fragments)
        if item.code == "CLAUSE_FACT_REVIEW_REQUIRED"
    }

    assert LEGACY_BRANCH_AUTHORITY_RULE_IDS
    assert not blocked & LEGACY_BRANCH_AUTHORITY_RULE_IDS


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
