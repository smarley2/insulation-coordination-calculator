"""Resolution refuses anything not current, and refuses nothing that is."""

from __future__ import annotations

import pytest

from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    DimensionScope,
    HfAttenuationFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import ClauseAuditSpec
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_CLAUSES,
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
)
from insulation_coordination.rules.importer.review import (
    ClauseFactResolutionError,
    author_clause_fact,
    live_evidence_sha256,
    record_fact_completion,
    resolve_confirmed_clause_facts,
)
from tests.conftest import _logged
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import _fragment

# draft_with_supply_fragments is a shared fixture; see tests/conftest.py.

HF_ROUTE = ids.SUPPLY_HF_TRANSFORMER_ATTENUATION
HF_FRAGMENT_ID = f"raw-{HF_ROUTE}"
SV_ROUTE = ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
SV_FRAGMENT_ID = f"raw-{SV_ROUTE}"
SV_EVIDENCE_FRAGMENT_ID = f"raw-{SUPPLY_SYSTEM_VOLTAGE_NON_MAINS}"
PROPAGATION_ROUTE = ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION


def _spec(semantic_id: str) -> ClauseAuditSpec:
    return next(spec for spec in SUPPLY_CLAUSES if spec.semantic_id == semantic_id)


def _fragment_of(draft: ImportedRuleDraft, fragment_id: str) -> RawClauseFragment:
    return next(item for item in draft.raw_clause_fragments if item.id == fragment_id)


def _cited(draft: ImportedRuleDraft, fragment_id: str, node_order: int = 0) -> CitedNode:
    """A citation of one fragment node, matching its current content."""

    fragment = _fragment_of(draft, fragment_id)
    node = next(item for item in fragment.nodes if item.order == node_order)
    return CitedNode(
        fragment_id=fragment.id,
        node_order=node.order,
        node_sha256=canonical_model_sha256(node),
    )


def _hf_fact(draft: ImportedRuleDraft, *, statement_index: int) -> HfAttenuationFact:
    return HfAttenuationFact(
        statement_index=statement_index,
        node_references=(_cited(draft, HF_FRAGMENT_ID),),
        obligation="requirement",
        dvc_gate=DimensionScope.of("dvc_as"),
        evidence_kind="test",
        threshold_reference=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        comparison_required=True,
    )


def _system_voltage_fact(
    draft: ImportedRuleDraft,
    *,
    statement_index: int,
    node_order: int,
    fragment_id: str = SV_FRAGMENT_ID,
    supply_kind: str = "mains",
) -> SystemVoltageFact:
    return SystemVoltageFact(
        statement_index=statement_index,
        node_references=(_cited(draft, fragment_id, node_order),),
        obligation="requirement",
        supply_kind=supply_kind,  # type: ignore[arg-type]
        phase_system="three_phase_it",
        earthing="it",
        input_topology="any_input_topology",
        purpose="impulse",
        measure="phase_to_artificial_neutral_rms",
    )


@pytest.fixture
def hf_spec() -> ClauseAuditSpec:
    return _spec(HF_ROUTE)


@pytest.fixture
def authored_draft(draft_with_supply_fragments: ImportedRuleDraft) -> ImportedRuleDraft:
    return author_clause_fact(
        draft_with_supply_fragments,
        rule_route=HF_ROUTE,
        fact=_hf_fact(draft_with_supply_fragments, statement_index=0),
        actor="tester",
        notes="authored",
    )


@pytest.fixture
def completed_draft(authored_draft: ImportedRuleDraft) -> ImportedRuleDraft:
    return record_fact_completion(
        authored_draft,
        rule_route=HF_ROUTE,
        fragment_id=HF_FRAGMENT_ID,
        actor="tester",
        notes="complete",
    )


@pytest.fixture
def system_voltage_draft(draft_with_supply_fragments: ImportedRuleDraft) -> ImportedRuleDraft:
    """The same draft with the system voltage clause carrying three reviewed bullet nodes.

    The one route whose fragment really has siblings once propagation is set aside, so the one
    route that can show a change to a sibling node leaving a fact's own review current.
    """

    fragments = tuple(
        _fragment(SV_ROUTE, kind="bullet", count=3) if item.id == SV_FRAGMENT_ID else item
        for item in draft_with_supply_fragments.raw_clause_fragments
    )
    return _logged(
        draft_with_supply_fragments.model_copy(update={"raw_clause_fragments": fragments})
    )


def _complete_mains_scope(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Two authored statements on the mains route: one citing node 0, one citing node 2.

    Authored out of statement order on purpose, so resolution has something to sort.
    """

    draft = author_clause_fact(
        draft,
        rule_route=SV_ROUTE,
        fact=_system_voltage_fact(draft, statement_index=1, node_order=2),
        actor="tester",
        notes="the third bullet",
    )
    draft = author_clause_fact(
        draft,
        rule_route=SV_ROUTE,
        fact=_system_voltage_fact(draft, statement_index=0, node_order=0),
        actor="tester",
        notes="the first bullet",
    )
    return record_fact_completion(
        draft,
        rule_route=SV_ROUTE,
        fragment_id=SV_FRAGMENT_ID,
        actor="tester",
        notes="complete",
    )


def _complete_non_mains_scope(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """The sibling subclause's own scope: its own statement, citing its own fragment."""

    draft = author_clause_fact(
        draft,
        rule_route=SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        fact=_system_voltage_fact(
            draft,
            statement_index=0,
            node_order=0,
            fragment_id=SV_EVIDENCE_FRAGMENT_ID,
            supply_kind="non_mains",
        ),
        actor="tester",
        notes="the non-mains statement",
    )
    return record_fact_completion(
        draft,
        rule_route=SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        fragment_id=SV_EVIDENCE_FRAGMENT_ID,
        actor="tester",
        notes="complete",
    )


@pytest.fixture
def completed_system_voltage_draft(system_voltage_draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Both of the rule's evidence scopes authored and complete."""

    return _complete_non_mains_scope(_complete_mains_scope(system_voltage_draft))


@pytest.fixture
def system_voltage_fragment_with_changed_third_node(
    system_voltage_draft: ImportedRuleDraft,
) -> RawClauseFragment:
    """That fragment with node 2's text corrected and its own hash recomputed."""

    fragment = _fragment_of(system_voltage_draft, SV_FRAGMENT_ID)
    nodes = tuple(
        node.model_copy(update={"raw_text": f"{node.raw_text} corrected"})
        if node.order == 2
        else node
        for node in fragment.nodes
    )
    changed = fragment.model_copy(update={"nodes": nodes, "raw_sha256": "0" * 64})
    return changed.model_copy(update={"raw_sha256": canonical_model_sha256(changed)})


def test_a_completed_route_resolves(completed_draft, hf_spec) -> None:
    facts = resolve_confirmed_clause_facts(hf_spec, completed_draft)

    assert len(facts.for_route(HF_ROUTE)) == 1


def test_a_route_without_authored_facts_refuses(draft_with_supply_fragments, hf_spec) -> None:
    """Projecting a branch nobody reviewed is what this slice exists to stop."""

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, draft_with_supply_fragments)


def test_a_route_without_completion_refuses(authored_draft, hf_spec) -> None:
    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, authored_draft)


def test_a_stale_fragment_hash_refuses(completed_draft, hf_spec) -> None:
    stale = tuple(
        item.model_copy(update={"fragment_sha256": "0" * 64})
        for item in completed_draft.clause_fact_completions
    )
    draft = completed_draft.model_copy(update={"clause_fact_completions": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_a_stale_fact_set_digest_refuses(completed_draft, hf_spec) -> None:
    stale = tuple(
        item.model_copy(update={"fact_set_sha256": "0" * 64})
        for item in completed_draft.clause_fact_completions
    )
    draft = completed_draft.model_copy(update={"clause_fact_completions": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_a_review_whose_hash_is_not_its_fact_refuses(completed_draft, hf_spec) -> None:
    """Projection runs before approval, so resolution must catch this rather than the gate.

    Every other digest here would still be current: the fact set is what it always was and the
    cited nodes have not moved. Only the review's own record of which fact it approved is wrong.
    """

    tampered = tuple(
        item.model_copy(update={"fact_sha256": "0" * 64})
        for item in completed_draft.clause_fact_reviews
    )
    draft = completed_draft.model_copy(update={"clause_fact_reviews": tampered})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_a_changed_cited_node_refuses(completed_draft, hf_spec) -> None:
    """Changing evidence a fact rests on must re-open that fact."""

    stale = tuple(
        item.model_copy(update={"evidence_sha256": "0" * 64})
        for item in completed_draft.clause_fact_reviews
    )
    draft = completed_draft.model_copy(update={"clause_fact_reviews": stale})

    with pytest.raises(ClauseFactResolutionError):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_a_fragment_that_gained_a_node_reopens_the_routes_completion(
    completed_draft, hf_spec
) -> None:
    """Route resolution is fragment-granular on purpose, and this is why.

    The gained node is uncited, and node 0 is untouched, so every fact's evidence is still
    current -- resolution refuses at the completion check anyway. A fragment that gained a node
    may have gained a normative statement, so "this route's fact set is complete" is a claim
    about a document region that changed and has to be asserted again.
    """

    grown = _fragment(HF_ROUTE, kind="bullet", count=2)
    draft = completed_draft.model_copy(
        update={
            "raw_clause_fragments": tuple(
                grown if item.id == HF_FRAGMENT_ID else item
                for item in completed_draft.raw_clause_fragments
            )
        }
    )

    with pytest.raises(ClauseFactResolutionError, match="older fragment"):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_a_route_whose_fragment_the_draft_does_not_carry_refuses(completed_draft, hf_spec) -> None:
    """Resolution reads each route's own fragment, so a draft missing one cannot resolve it."""

    draft = completed_draft.model_copy(
        update={
            "raw_clause_fragments": tuple(
                item for item in completed_draft.raw_clause_fragments if item.id != HF_FRAGMENT_ID
            )
        }
    )

    with pytest.raises(ClauseFactResolutionError, match="no extracted fragment"):
        resolve_confirmed_clause_facts(hf_spec, draft)


def test_an_uncited_sibling_node_changing_keeps_its_siblings_reviews_current(
    completed_system_voltage_draft, system_voltage_fragment_with_changed_third_node
) -> None:
    """Selective invalidation, on a route whose fragment really has several nodes.

    System voltage extracts as several nodes across its regions, so a fact citing the first can
    be shown to survive a change to the third. Propagation is the only other multi-node route
    and the resolver skips it as the legacy exception, so this is the one route that can carry
    this.

    Both directions are asserted against the *changed* draft, and through
    ``live_evidence_sha256``. Comparing a review's stored digest with
    ``evidence_sha256(review.fact.node_references)`` proves nothing: both sides read the citation
    records stored inside the fact, so every review ``author_clause_fact`` ever produced satisfies
    it whatever happened to the document -- the exact tautology ``live_evidence_sha256`` exists to
    break. And only the ``!=`` half catches an implementation that recomputed at fragment
    granularity by mistake, which is the way this property is actually lost.
    """

    changed_draft = completed_system_voltage_draft.model_copy(
        update={"raw_clause_fragments": (system_voltage_fragment_with_changed_third_node,)}
    )
    by_cited_node = {
        review.fact.node_references[0].node_order: review
        for review in changed_draft.clause_fact_reviews
        if review.rule_route == SV_ROUTE
    }
    unchanged, moved = by_cited_node[0], by_cited_node[2]

    assert unchanged.evidence_sha256 == live_evidence_sha256(
        changed_draft, unchanged.fact.node_references
    ), "a fact citing an unchanged node keeps its own review current"
    assert moved.evidence_sha256 != live_evidence_sha256(
        changed_draft, moved.fact.node_references
    ), "a fact citing the changed node goes stale"


def test_facts_come_back_ordered_by_statement_index(completed_system_voltage_draft) -> None:
    """Authored second-statement-first, so source order is the resolver's doing, not the draft's."""

    facts = resolve_confirmed_clause_facts(_spec(SV_ROUTE), completed_system_voltage_draft)
    indexes = [fact.statement_index for fact in facts.for_route(SV_ROUTE)]

    assert indexes == [0, 1]


def test_a_route_a_clause_projects_without_facts_resolves_to_nothing(
    completed_system_voltage_draft,
) -> None:
    """The guidance a NOTE becomes is a declared route of this clause and states no branch.

    So resolution must not demand facts for it, or a clause that projects guidance could never
    be projected at all.
    """

    facts = resolve_confirmed_clause_facts(_spec(SV_ROUTE), completed_system_voltage_draft)

    assert facts.for_route(SV_ROUTE)
    assert facts.for_route(f"{SV_ROUTE}.guidance") == ()


def test_the_legacy_branch_authority_route_resolves_to_nothing(
    draft_with_supply_fragments,
) -> None:
    """Its rule is an ordinal comparison no reviewed fact can state, so its recipe keeps it."""

    facts = resolve_confirmed_clause_facts(_spec(PROPAGATION_ROUTE), draft_with_supply_fragments)

    assert facts.by_route == {}


# --- one rule, two evidence scopes ---------------------------------------------------


def test_both_scopes_resolve_for_the_rule_that_rests_on_both(
    completed_system_voltage_draft,
) -> None:
    """The evidence clause's facts reach the rule's projection, under their own route."""

    facts = resolve_confirmed_clause_facts(_spec(SV_ROUTE), completed_system_voltage_draft)

    assert len(facts.for_route(SV_ROUTE)) == 2
    assert len(facts.for_route(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS)) == 1


def test_an_incomplete_mains_scope_refuses_the_whole_rule(system_voltage_draft) -> None:
    draft = _complete_non_mains_scope(system_voltage_draft)

    with pytest.raises(ClauseFactResolutionError, match=SV_ROUTE):
        resolve_confirmed_clause_facts(_spec(SV_ROUTE), draft)


def test_an_incomplete_non_mains_scope_refuses_the_whole_rule(system_voltage_draft) -> None:
    """The second subclause is not optional: the rule needs every scope it declares."""

    draft = _complete_mains_scope(system_voltage_draft)

    with pytest.raises(ClauseFactResolutionError, match=SUPPLY_SYSTEM_VOLTAGE_NON_MAINS):
        resolve_confirmed_clause_facts(_spec(SV_ROUTE), draft)


def test_the_evidence_clauses_own_spec_resolves_only_its_own_scope(
    completed_system_voltage_draft,
) -> None:
    """It projects nothing, and resolving it must not drag the rule's other scope in."""

    facts = resolve_confirmed_clause_facts(
        _spec(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS), completed_system_voltage_draft
    )

    assert set(facts.by_route) == {SUPPLY_SYSTEM_VOLTAGE_NON_MAINS}
