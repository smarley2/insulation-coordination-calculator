"""Synthetic supply-clause projections. Invented values only; no IEC content."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import pytest

from insulation_coordination.domain.rules import (
    DecisionRule,
    GuidanceRule,
    SourceReference,
)
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer import review
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    CitedNode,
    ConfirmedFacts,
    DimensionScope,
    HfAttenuationFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.clauses import (
    ClauseNode,
    ClauseToken,
    RawClauseFragment,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    ImportReviewItem,
    aggregate_artifact_sha256,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import StandardIdentity, StandardRecipe
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_CLAUSES,
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
    project_hf_transformer_attenuation,
    project_multiple_source_propagation,
    project_spd_reduction_requirements,
    project_system_voltage_resolution,
    project_verified_barrier_transfer,
)
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft as _empty_draft
from tests.rules.importer.test_clause_fact_proposals import fragment_with_sentences

SOURCE = SourceReference(
    document_id="synthetic-supply",
    standard="SYNTHETIC",
    edition="1",
    page=9,
    clause="9.9.9",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="6" * 64,
    page_count=44,
    recipe_id="synthetic-supply",
)


def _mixed_fragment(
    semantic_id: str,
    kinds: tuple[str, ...],
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    """A synthetic fragment whose nodes carry the given kinds, in order.

    Several kinds because one clause may span regions that read differently -- the system
    voltage subclause is bullets and then running prose.
    """

    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,  # type: ignore[arg-type]
            raw_text=f"synthetic neutral {kind} node {order}",
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order, kind in enumerate(kinds)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=tokens,
        source=SOURCE,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _fragment(
    semantic_id: str,
    *,
    kind: str = "bullet",
    count: int = 1,
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    return _mixed_fragment(semantic_id, (kind,) * count, tokens)


#: The reviewed shape of the mains system voltage subclause: the bullet list's lead-in, five
#: bullets across two regions, and one paragraph region after them.
_SYSTEM_VOLTAGE_KINDS = (
    "paragraph",
    "bullet",
    "bullet",
    "bullet",
    "bullet",
    "bullet",
    "paragraph",
)


def _bullet_fragment() -> RawClauseFragment:
    return _mixed_fragment(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, _SYSTEM_VOLTAGE_KINDS)


def _non_mains_evidence_fragment() -> RawClauseFragment:
    """The sibling subclause's fragment, on a page of its own so provenance is visible."""

    source = SOURCE.model_copy(update={"page": 10})
    fragment = _fragment(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, kind="paragraph", count=1)
    nodes = tuple(
        node.model_copy(update={"source": source.model_copy(update={"row": f"node {node.order}"})})
        for node in fragment.nodes
    )
    rebuilt = fragment.model_copy(update={"nodes": nodes, "source": source, "raw_sha256": "0" * 64})
    return rebuilt.model_copy(update={"raw_sha256": canonical_model_sha256(rebuilt)})


class _StubDraft(NamedTuple):
    """The one attribute a clause projection reads off the reviewed draft.

    Building an ``ImportedRuleDraft`` here would add a manifest, identities and an audit chain
    to a test about which fragments a projection reads.
    """

    raw_clause_fragments: tuple[RawClauseFragment, ...]


def _clause_review_item(semantic_id: str) -> ImportReviewItem:
    """A synthetic ``MANUAL_CLAUSE_DEFINITION_REQUIRED`` item for one clause spec.

    The real importer emits exactly one of these per declared clause spec, rule-producing or
    evidence-only alike (``extract.py``'s ``clause_items``); this stands in for that without
    building a full extraction.
    """

    return ImportReviewItem(
        code="MANUAL_CLAUSE_DEFINITION_REQUIRED",
        semantic_id=semantic_id,
        kind="clause",
        source=SOURCE,
        expected_contract=f"clause:{semantic_id}:test",
    )


def _grounded_draft(
    rule: DecisionRule, fragments: tuple[RawClauseFragment, ...]
) -> ImportedRuleDraft:
    """A real ``ImportedRuleDraft`` carrying one projected rule and its fragments' review items.

    Unlike ``_StubDraft``, this is enough for the approval gate's own lookups
    (``review._required_review_items``, ``review._current_source_artifact_sha256``) to run: they
    read ``draft.decisions`` and ``draft.review_items``, neither of which the projector itself
    needs.
    """

    return _empty_draft(fragments=fragments).model_copy(
        update={
            "decisions": (rule,),
            "review_items": tuple(
                _clause_review_item(fragment.id.removeprefix("raw-")) for fragment in fragments
            ),
        }
    )


def _lettered_fragment(*, count: int = 4) -> RawClauseFragment:
    return _fragment(ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION, kind="bullet", count=count)


def _paragraph_fragment(
    semantic_id: str,
    *,
    count: int = 1,
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    return _fragment(semantic_id, kind="paragraph", count=count, tokens=tokens)


def _barrier_fragment(*, count: int = 1) -> RawClauseFragment:
    return _paragraph_fragment(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, count=count)


def _cited_node(fragment: RawClauseFragment, *, node_order: int = 0) -> CitedNode:
    """A citation of one real node of ``fragment``, matching its current content."""

    node = next(item for item in fragment.nodes if item.order == node_order)
    return CitedNode(
        fragment_id=fragment.id, node_order=node.order, node_sha256=canonical_model_sha256(node)
    )


def _system_voltage_fact(
    fragment: RawClauseFragment,
    *,
    index: int = 0,
    supply_kind: str = "mains",
    phase_system: str = "three_phase_it",
    earthing: str = "it",
    input_topology: str = "any_input_topology",
    purpose: str = "impulse",
    measure: str,
) -> SystemVoltageFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return SystemVoltageFact(
        statement_index=index,
        node_references=(_cited_node(fragment, node_order=index % len(fragment.nodes)),),
        obligation="requirement",
        supply_kind=supply_kind,  # type: ignore[arg-type]
        phase_system=phase_system,  # type: ignore[arg-type]
        earthing=earthing,  # type: ignore[arg-type]
        input_topology=input_topology,  # type: ignore[arg-type]
        purpose=purpose,  # type: ignore[arg-type]
        measure=measure,  # type: ignore[arg-type]
    )


def _confirmed_system_voltage_facts(
    *,
    measures: tuple[str, ...],
    fragment: RawClauseFragment | None = None,
) -> ConfirmedFacts:
    """One fact per measure, each under its own phase system so rows stay distinguishable."""

    frag = fragment if fragment is not None else _bullet_fragment()
    phase_systems = ("three_phase_it", "single_phase_it")
    facts = tuple(
        _system_voltage_fact(
            frag,
            index=index,
            phase_system=phase_systems[index % len(phase_systems)],
            measure=measure,
        )
        for index, measure in enumerate(measures)
    )
    return ConfirmedFacts(by_route={ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: facts})


def _barrier_fact(
    fragment: RawClauseFragment,
    *,
    index: int = 0,
    isolation_present: bool,
    connection: str | None = None,
    combined_rule: str,
) -> BarrierTransferFact:
    """Invented values only: a synthetic reviewed statement, never real clause content.

    ``connection`` defaults to the kind that pairs with the barrier: a statement about an absent
    barrier is scoped to a connection without isolation, and one about a present barrier to a
    connection through it.
    """

    downstream = connection or (
        "verified_galvanic_isolation" if isolation_present else "no_isolation"
    )
    return BarrierTransferFact(
        statement_index=index,
        node_references=(_cited_node(fragment),),
        obligation="requirement",
        isolation_present=isolation_present,
        downstream_connection_kind=downstream,  # type: ignore[arg-type]
        combined_circuit_rule=combined_rule,  # type: ignore[arg-type]
    )


def _confirmed_barrier_facts(
    *,
    combined_rule: str,
    isolation_present: bool = False,
    connection: str | None = None,
    fragment: RawClauseFragment | None = None,
) -> ConfirmedFacts:
    frag = fragment if fragment is not None else _barrier_fragment()
    fact = _barrier_fact(
        frag,
        isolation_present=isolation_present,
        connection=connection,
        combined_rule=combined_rule,
    )
    return ConfirmedFacts(by_route={ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: (fact,)})


def _spd_fragment(route: str) -> RawClauseFragment:
    return _paragraph_fragment(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.{route}")


def _spd_reduction_fact(
    fragment: RawClauseFragment,
    *,
    index: int = 0,
    supply_kind: str,
    source_ovc: str,
    target_ovc: str,
    insulation_class: str = "basic",
    degradable: bool = False,
    monitoring_obligation: str = "not_required",
) -> SpdReductionFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return SpdReductionFact(
        statement_index=index,
        node_references=(_cited_node(fragment),),
        obligation="requirement",
        supply_kind=supply_kind,  # type: ignore[arg-type]
        source_ovc=source_ovc,  # type: ignore[arg-type]
        target_ovc=target_ovc,  # type: ignore[arg-type]
        insulation_class=insulation_class,  # type: ignore[arg-type]
        degradable=degradable,
        monitoring_obligation=monitoring_obligation,  # type: ignore[arg-type]
        monitoring_reference=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
    )


def _confirmed_spd_facts(
    route: str,
    *,
    source_ovc: str,
    target_ovc: str,
    insulation_class: str = "basic",
    degradable: bool = False,
    monitoring_obligation: str = "not_required",
    fragment: RawClauseFragment | None = None,
) -> ConfirmedFacts:
    frag = fragment if fragment is not None else _spd_fragment(route)
    fact = _spd_reduction_fact(
        frag,
        supply_kind=route,
        source_ovc=source_ovc,
        target_ovc=target_ovc,
        insulation_class=insulation_class,
        degradable=degradable,
        monitoring_obligation=monitoring_obligation,
    )
    route_id = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.{route}"
    return ConfirmedFacts(by_route={route_id: (fact,)})


def _spd_monitoring_fact(
    fragment: RawClauseFragment,
    *,
    index: int = 0,
    device_placement: str = "internal_to_pecs",
    participates_in_reduction: bool = True,
    monitoring_required: bool = True,
    compliance_evidence: str = "monitoring_test",
) -> SpdMonitoringFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return SpdMonitoringFact(
        statement_index=index,
        node_references=(_cited_node(fragment),),
        obligation="requirement",
        device_placement=device_placement,  # type: ignore[arg-type]
        participates_in_reduction=participates_in_reduction,
        monitoring_required=monitoring_required,
        compliance_evidence=compliance_evidence,  # type: ignore[arg-type]
    )


def _confirmed_spd_monitoring_facts(
    *,
    monitoring_required: bool,
    participates_in_reduction: bool = True,
    device_placement: str = "internal_to_pecs",
    fragment: RawClauseFragment | None = None,
) -> ConfirmedFacts:
    frag = fragment if fragment is not None else _spd_fragment("monitoring")
    fact = _spd_monitoring_fact(
        frag,
        device_placement=device_placement,
        participates_in_reduction=participates_in_reduction,
        monitoring_required=monitoring_required,
    )
    route_id = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"
    return ConfirmedFacts(by_route={route_id: (fact,)})


def _hf_attenuation_fact(
    fragment: RawClauseFragment,
    *,
    index: int = 0,
    dvc_gate: DimensionScope[str] | None = None,
    evidence_kind: str,
) -> HfAttenuationFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return HfAttenuationFact(
        statement_index=index,
        node_references=(_cited_node(fragment),),
        obligation="requirement",
        dvc_gate=dvc_gate if dvc_gate is not None else DimensionScope.of("dvc_b"),  # type: ignore[arg-type]
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
        threshold_reference=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        comparison_required=True,
    )


def _confirmed_hf_facts(
    *,
    evidence_kinds: tuple[str, ...],
    dvc_gate: DimensionScope[str] | None = None,
    fragment: RawClauseFragment,
) -> ConfirmedFacts:
    facts = tuple(
        _hf_attenuation_fact(fragment, index=index, dvc_gate=dvc_gate, evidence_kind=kind)
        for index, kind in enumerate(evidence_kinds)
    )
    return ConfirmedFacts(by_route={ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: facts})


_EMPTY_FACTS = ConfirmedFacts()


def _decision(rules: tuple[object, ...], semantic_id: str) -> DecisionRule:
    return next(rule for rule in rules if isinstance(rule, DecisionRule) and rule.id == semantic_id)


def _project_system_voltage(
    fragment: RawClauseFragment, facts: ConfirmedFacts = _EMPTY_FACTS
) -> DecisionRule:
    rules, _proposals = project_system_voltage_resolution(fragment, IDENTITY, confirmed_facts=facts)
    return _decision(rules, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)


def _project_propagation(fragment: RawClauseFragment) -> DecisionRule:
    rules, _proposals = project_multiple_source_propagation(fragment, IDENTITY)
    return _decision(rules, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION)


def _project_barrier(
    fragment: RawClauseFragment, facts: ConfirmedFacts = _EMPTY_FACTS
) -> DecisionRule:
    rules, _proposals = project_verified_barrier_transfer(fragment, IDENTITY, confirmed_facts=facts)
    return _decision(rules, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)


def _lookup(rule: DecisionRule, **inputs: Decimal | str | bool) -> object | None:
    result = evaluate_decision(rule, inputs)
    return result if result.status == "matched" else None


def _value(result: object, name: str) -> object:
    value = next(item for item in result.values if item.name == name)  # type: ignore[attr-defined]
    for field in (value.categorical, value.numeric, value.boolean, value.reference):
        if field is not None:
            return field
    raise AssertionError(f"decision value {name} carries nothing")


def _declared_vocabularies(rule: DecisionRule) -> dict[str, tuple[str, ...]]:
    """Every categorical input's declared question space, by name.

    Asserted alongside the input names, because a contract test that pins only the names cannot
    see the defect that actually happens: switching an input from a declared vocabulary to one
    derived from the reviewed facts keeps its name and silently shrinks what a consumer may ask,
    turning a question the rule used to answer into an ``EvaluationError``. Rows come from facts;
    input vocabularies do not.
    """

    return {item.name: item.allowed_values for item in rule.inputs if item.kind == "categorical"}


def _system_voltage_inputs(**overrides: str) -> dict[str, str]:
    inputs = {
        "supply_kind": "mains",
        "phase_system": "three_phase_star",
        "earthing_arrangement": "tn",
        "input_topology": "direct",
        "calculation_purpose": "impulse",
    }
    inputs.update(overrides)
    return inputs


# --- Task 5: system voltage and barrier transfer follow reviewed facts ------------
# (propagation stays legacy branch authority; see LEGACY_BRANCH_AUTHORITY_RULE_IDS)


def test_exactly_one_supply_rule_still_carries_legacy_branch_authority() -> None:
    """Propagation is the sole exception, because porting it faithfully changes behaviour.

    Its contract *is* an ordinal overvoltage-category comparison, which no reviewed fact can
    honestly express -- only the branches it enumerates. #53C item 3 replaces the contract,
    and removing this exception is #53C's first acceptance criterion; this test is what
    records that it is still outstanding. Every other supply route's refusal to project
    without facts has its own test beside its projector.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        LEGACY_BRANCH_AUTHORITY_RULE_IDS,
    )

    assert LEGACY_BRANCH_AUTHORITY_RULE_IDS == frozenset({ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION})


def test_every_non_legacy_route_declares_a_proposal_grammar_of_its_own_family() -> None:
    """A route without one loses every prefill while still looking authorable.

    The recipe refuses the disagreement at import, so this asserts the property that refusal
    protects rather than re-deriving it: exactly the non-legacy routes, each stating the fact
    family its own clause declares. The legacy route keeps its branch authority in the recipe
    and so has nothing to propose.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        LEGACY_BRANCH_AUTHORITY_RULE_IDS,
        SUPPLY_FACT_FAMILY_BY_ROUTE,
        SUPPLY_FACT_PROPOSAL_GRAMMARS,
    )

    assert set(SUPPLY_FACT_PROPOSAL_GRAMMARS) == (
        set(SUPPLY_FACT_FAMILY_BY_ROUTE) - LEGACY_BRANCH_AUTHORITY_RULE_IDS
    )
    assert all(
        grammar.fact_kind == SUPPLY_FACT_FAMILY_BY_ROUTE[route]
        for route, grammar in SUPPLY_FACT_PROPOSAL_GRAMMARS.items()
    )


def test_a_floor_sentence_proposes_no_insulation_class() -> None:
    """A reading the sentence does not make is worse than a blank field.

    A blank field cannot be confirmed by accident; a wrong value can. Both sentences below are
    invented for this test out of the reduction family's own declared vocabulary: one shapes a
    permission over two classes, the other names the two classes a floor is stated over. Only
    the first may propose a class.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        propose_supply_facts,
    )

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

    assert {item.chosen["insulation_class"] for item in permission} == {"basic", "supplementary"}
    assert floor
    assert all("insulation_class" in item.unchosen for item in floor)


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

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        propose_supply_facts,
    )

    route = ids.SUPPLY_VERIFIED_BARRIER_TRANSFER
    (proposal,) = propose_supply_facts(fragment_with_sentences(route, (sentence,)), route)

    assert proposal.chosen.get("obligation") == expected
    assert ("obligation" in proposal.unchosen) is (expected is None)


def test_a_route_with_no_declared_grammar_proposes_nothing() -> None:
    """The legacy route's fragment is still extracted; nothing may be proposed from it."""

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        propose_supply_facts,
    )

    fragment = _fragment(ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION)

    assert propose_supply_facts(fragment, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION) == ()


def test_every_reviewed_fact_is_reachable_and_unsupported_combinations_are_not() -> None:
    """Reachability now rests on the reviewed facts, not on a fixed nine-branch inventory."""

    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    fragment,
                    index=0,
                    phase_system="three_phase_it",
                    earthing="it",
                    purpose="impulse",
                    measure="phase_to_artificial_neutral_rms",
                ),
                _system_voltage_fact(
                    fragment,
                    index=1,
                    phase_system="single_phase_it",
                    earthing="it",
                    purpose="temporary_overvoltage",
                    measure="phase_to_phase_rms",
                ),
            )
        }
    )
    rule = _project_system_voltage(fragment, facts)
    assert len(rule.rows) == 2
    assert rule.exhaustive is False

    matched = {
        evaluate_decision(
            rule,
            _system_voltage_inputs(
                phase_system="three_phase_it",
                earthing_arrangement="it",
                calculation_purpose="impulse",
            ),
        ).matched_row,
        evaluate_decision(
            rule,
            _system_voltage_inputs(
                phase_system="single_phase_it",
                earthing_arrangement="it",
                calculation_purpose="temporary_overvoltage",
            ),
        ).matched_row,
    }
    assert matched == {0, 1}
    # Same phase system as a fact, but the purpose no fact states for it: not covered.
    assert (
        _lookup(
            rule,
            **_system_voltage_inputs(
                phase_system="single_phase_it",
                earthing_arrangement="it",
                calculation_purpose="impulse",
            ),
        )
        is None
    )
    # An earthing arrangement no fact states at all: not covered.
    assert (
        _lookup(
            rule,
            **_system_voltage_inputs(
                phase_system="three_phase_it",
                earthing_arrangement="tt",
                calculation_purpose="impulse",
            ),
        )
        is None
    )


def test_impulse_and_temporary_overvoltage_branches_stay_separate() -> None:
    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    fragment,
                    index=0,
                    purpose="impulse",
                    measure="phase_to_artificial_neutral_rms",
                ),
                _system_voltage_fact(
                    fragment,
                    index=1,
                    purpose="temporary_overvoltage",
                    measure="phase_to_phase_rms",
                ),
            )
        }
    )
    rule = _project_system_voltage(fragment, facts)
    impulse = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="impulse",
        ),
    )
    tov = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="temporary_overvoltage",
        ),
    )
    assert impulse is not None and tov is not None
    assert _value(impulse, "system_voltage_measure") != _value(tov, "system_voltage_measure")


def test_a_fact_stated_without_a_purpose_covers_both_purposes() -> None:
    """One reviewed statement that fixes its measure without restricting the purpose.

    Authoring it as two facts differing only in purpose would record two readings where the
    reviewer recorded one. The two purpose-specific facts still yield their own, separate rows
    alongside it.
    """

    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    fragment,
                    index=0,
                    phase_system="three_phase_it",
                    purpose="impulse",
                    measure="phase_to_artificial_neutral_rms",
                ),
                _system_voltage_fact(
                    fragment,
                    index=1,
                    phase_system="three_phase_it",
                    purpose="temporary_overvoltage",
                    measure="phase_to_phase_rms",
                ),
                _system_voltage_fact(
                    fragment,
                    index=2,
                    phase_system="single_phase_it",
                    purpose="any_purpose",
                    measure="between_supply_conductors_rms",
                ),
            )
        }
    )
    rule = _project_system_voltage(fragment, facts)
    assert len(rule.rows) == 3

    any_purpose_impulse = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="single_phase_it",
            earthing_arrangement="it",
            calculation_purpose="impulse",
        ),
    )
    any_purpose_tov = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="single_phase_it",
            earthing_arrangement="it",
            calculation_purpose="temporary_overvoltage",
        ),
    )
    assert any_purpose_impulse is not None and any_purpose_tov is not None
    assert _value(any_purpose_impulse, "system_voltage_measure") == "between_supply_conductors_rms"
    assert _value(any_purpose_tov, "system_voltage_measure") == "between_supply_conductors_rms"

    specific_impulse = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="impulse",
        ),
    )
    specific_tov = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            calculation_purpose="temporary_overvoltage",
        ),
    )
    assert specific_impulse is not None and specific_tov is not None
    assert _value(specific_impulse, "system_voltage_measure") == "phase_to_artificial_neutral_rms"
    assert _value(specific_tov, "system_voltage_measure") == "phase_to_phase_rms"


def test_the_note_becomes_guidance_and_never_a_formula() -> None:
    fragment = _bullet_fragment()
    facts = _confirmed_system_voltage_facts(fragment=fragment, measures=("phase_to_phase_rms",))
    rules, proposals = project_system_voltage_resolution(fragment, IDENTITY, confirmed_facts=facts)
    assert any(isinstance(rule, GuidanceRule) for rule in rules)
    assert not any(getattr(rule, "expression", None) for rule in rules)
    assert not any(getattr(rule, "expression_shape", None) for rule in rules)
    assert {proposal.rule_kind for proposal in proposals} == {"decision", "guidance"}


def test_system_voltage_rows_follow_the_reviewed_facts_not_the_old_constants() -> None:
    """Authority moved: facts the constants never contained must reach the rule."""

    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms", "highest_pre_rectifier_ac_rms_at_bridge")
    )
    rule = _project_system_voltage(_bullet_fragment(), facts)

    emitted = {
        value.categorical
        for row in rule.rows
        for value in row.values
        if value.name == "system_voltage_measure"
    }

    assert emitted == {"phase_to_phase_rms", "highest_pre_rectifier_ac_rms_at_bridge"}


def test_system_voltage_refuses_to_project_without_facts() -> None:
    """No fallback: a factless projection would silently restore the deleted inventory."""

    with pytest.raises(ClauseStructureError):
        project_system_voltage_resolution(
            _bullet_fragment(), IDENTITY, confirmed_facts=ConfirmedFacts()
        )


def test_system_voltage_keeps_its_declared_contract() -> None:
    facts = _confirmed_system_voltage_facts(measures=("phase_to_phase_rms",))
    rule = _project_system_voltage(_bullet_fragment(), facts)

    assert {item.name for item in rule.inputs} == {
        "supply_kind",
        "phase_system",
        "earthing_arrangement",
        "input_topology",
        "calculation_purpose",
    }
    assert {item.name for item in rule.outputs} == {"system_voltage_measure"}
    assert _declared_vocabularies(rule) == {
        "supply_kind": ("mains", "non_mains"),
        "phase_system": (
            "three_phase_star",
            "three_phase_delta",
            "three_phase_it",
            "single_phase_it",
            "single_phase",
            "unspecified",
        ),
        "earthing_arrangement": ("tn", "tt", "it", "unspecified"),
        "input_topology": (
            "direct",
            "rectified_dc",
            "series_rectifier_bridges",
            "isolated_secondary",
        ),
        "calculation_purpose": ("impulse", "temporary_overvoltage"),
    }


def test_a_fragment_whose_node_kinds_differ_blocks() -> None:
    """The shape contract is the ordered node kinds, so a reflow of either kind stops here."""

    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_system_voltage_resolution(
            _fragment(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, kind="bullet", count=7), IDENTITY
        )


def test_a_fragment_whose_later_region_reflowed_into_a_bullet_blocks() -> None:
    """Same node count, wrong kind at the last position: the ordered sequence catches it."""

    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_system_voltage_resolution(
            _fragment(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, kind="bullet", count=6), IDENTITY
        )


def test_a_foreign_fragment_cannot_be_projected() -> None:
    foreign = _bullet_fragment().model_copy(update={"id": "raw-other-clause"})
    with pytest.raises(ValueError, match="system voltage"):
        project_system_voltage_resolution(foreign, IDENTITY)


def test_a_fragment_from_another_standard_cannot_be_projected() -> None:
    other = _bullet_fragment()
    other = other.model_copy(update={"source": other.source.model_copy(update={"edition": "2"})})
    with pytest.raises(ValueError, match="identified source"):
        project_system_voltage_resolution(other, IDENTITY)


def test_propagation_is_evaluated_in_both_directions() -> None:
    rule = _project_propagation(_lettered_fragment())
    common = {
        "mains_overvoltage_category": "ovc_ii",
        "non_mains_overvoltage_category": "ovc_iv",
        "galvanic_isolation_present": True,
    }
    mains_side = _lookup(rule, evaluated_side="mains", **common)
    non_mains_side = _lookup(rule, evaluated_side="non_mains", **common)
    assert mains_side is not None and non_mains_side is not None
    assert _value(mains_side, "transferred_requirement") != _value(mains_side, "source_requirement")
    assert _value(mains_side, "source_requirement") == "ovc_ii"
    assert _value(non_mains_side, "source_requirement") == "ovc_iv"
    assert _value(mains_side, "governing_requirement") == "ovc_iii"
    assert _value(non_mains_side, "governing_requirement") == "ovc_iv"


def test_propagation_without_verified_isolation_is_not_covered_here() -> None:
    rule = _project_propagation(_lettered_fragment())
    assert (
        _lookup(
            rule,
            evaluated_side="mains",
            mains_overvoltage_category="ovc_ii",
            non_mains_overvoltage_category="ovc_iv",
            galvanic_isolation_present=False,
        )
        is None
    )


def test_a_propagation_fragment_with_the_wrong_alternative_count_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_multiple_source_propagation(_lettered_fragment(count=3), IDENTITY)


def test_without_verified_isolation_the_combined_requirement_propagates() -> None:
    fragment = _barrier_fragment()
    facts = _confirmed_barrier_facts(
        fragment=fragment, isolation_present=False, combined_rule="more_severe_of_both_sides"
    )
    rule = _project_barrier(fragment, facts)
    row = _lookup(
        rule,
        galvanic_isolation_verified=False,
        isolation_evidence_kind="none",
        downstream_connection_kind="no_isolation",
    )
    assert row is not None
    assert _value(row, "propagates_to_connected_circuits") is True
    assert _value(row, "transfer_permitted") is False
    assert _value(row, "combined_circuit_requirement") == "more_severe_of_both_sides"


def test_verified_isolation_keeps_the_transfer_side_specific() -> None:
    fragment = _barrier_fragment()
    facts = _confirmed_barrier_facts(
        fragment=fragment, isolation_present=True, combined_rule="side_specific_from_transfer"
    )
    rule = _project_barrier(fragment, facts)
    row = _lookup(
        rule,
        galvanic_isolation_verified=True,
        isolation_evidence_kind="test",
        downstream_connection_kind="verified_galvanic_isolation",
    )
    assert row is not None
    assert _value(row, "transfer_permitted") is True
    assert _value(row, "propagates_to_connected_circuits") is False


def test_barrier_transfer_follows_the_reviewed_facts() -> None:
    facts = _confirmed_barrier_facts(combined_rule="side_specific_from_transfer")
    rule = _project_barrier(_barrier_fragment(), facts)

    emitted = {
        value.categorical
        for row in rule.rows
        for value in row.values
        if value.name == "combined_circuit_requirement"
    }

    assert emitted == {"side_specific_from_transfer"}


def test_a_connection_kind_the_statement_excludes_is_not_answered_for() -> None:
    """The propagation statement is scoped to a connection made without galvanic isolation.

    Matching every connection kind did not merely lose a refusal, it answered a different
    question: it reported the combined circuit's rating as propagating into a circuit connected
    through a verified barrier, which is the case the clause excludes.
    """

    fragment = _barrier_fragment()
    facts = _confirmed_barrier_facts(
        fragment=fragment,
        isolation_present=False,
        connection="no_isolation",
        combined_rule="more_severe_of_both_sides",
    )
    rule = _project_barrier(fragment, facts)

    assert (
        _lookup(
            rule,
            galvanic_isolation_verified=False,
            isolation_evidence_kind="test",
            downstream_connection_kind="verified_galvanic_isolation",
        )
        is None
    )


def test_isolation_claimed_without_any_evidence_stays_uncovered() -> None:
    """A deliberate refusal: the consumer blocks rather than inheriting a guessed outcome."""

    fragment = _barrier_fragment()
    facts = _confirmed_barrier_facts(
        fragment=fragment,
        isolation_present=True,
        combined_rule="side_specific_from_transfer",
    )
    rule = _project_barrier(fragment, facts)

    assert (
        _lookup(
            rule,
            galvanic_isolation_verified=True,
            isolation_evidence_kind="none",
            downstream_connection_kind="verified_galvanic_isolation",
        )
        is None
    )


def test_barrier_transfer_refuses_to_project_without_facts() -> None:
    with pytest.raises(ClauseStructureError):
        project_verified_barrier_transfer(
            _barrier_fragment(), IDENTITY, confirmed_facts=ConfirmedFacts()
        )


def test_barrier_transfer_keeps_its_declared_contract() -> None:
    facts = _confirmed_barrier_facts(combined_rule="more_severe_of_both_sides")
    rule = _project_barrier(_barrier_fragment(), facts)

    assert {item.name for item in rule.inputs} == {
        "galvanic_isolation_verified",
        "isolation_evidence_kind",
        "downstream_connection_kind",
    }
    assert {item.name for item in rule.outputs} == {
        "transfer_permitted",
        "combined_circuit_requirement",
        "propagates_to_connected_circuits",
    }
    assert _declared_vocabularies(rule) == {
        "isolation_evidence_kind": ("none", "test", "calculation", "construction"),
        "downstream_connection_kind": ("no_isolation", "verified_galvanic_isolation"),
    }


def test_a_barrier_fragment_with_extra_nodes_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_verified_barrier_transfer(
            _paragraph_fragment(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, count=2),
            IDENTITY,
        )


def test_two_statements_stating_the_same_branch_are_refused() -> None:
    """A second statement with identical branch dimensions is unreachable, and contradicts.

    ``evaluate_decision`` serves the first row whose matchers fit, so nothing would report that
    the later statement's values are never served -- the hazard ``_require_distinct_selectors``
    already refuses for two axis positions confirmed as the same selector.
    """

    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(fragment, index=0, measure="phase_to_artificial_neutral_rms"),
                _system_voltage_fact(fragment, index=1, measure="phase_to_phase_rms"),
            )
        }
    )

    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project_system_voltage(fragment, facts)


def test_an_unrestricted_statement_overlapping_a_specific_one_is_refused() -> None:
    """Not identical, and still ambiguous: row order alone would pick the winner.

    The unrestricted statement covers every value of the dimension the other one narrows, so a
    consumer inside the narrower branch matches both rows and receives whichever the authoring
    order happened to put first. Where the source really states a general rule and a special
    case, the special case's own dimension separates them; a pair this refuses is one whose
    separating dimension nobody authored.
    """

    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    fragment, index=0, purpose="any_purpose", measure="phase_to_phase_rms"
                ),
                _system_voltage_fact(
                    fragment,
                    index=1,
                    purpose="impulse",
                    measure="phase_to_artificial_neutral_rms",
                ),
            )
        }
    )

    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project_system_voltage(fragment, facts)


def test_a_narrower_statement_on_its_own_dimension_is_not_refused() -> None:
    """The general statement and the special case differ on the dimension that separates them."""

    fragment = _bullet_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    fragment,
                    index=0,
                    input_topology="direct",
                    purpose="any_purpose",
                    measure="phase_to_phase_rms",
                ),
                _system_voltage_fact(
                    fragment,
                    index=1,
                    phase_system="any_phase_system",
                    input_topology="rectified_dc",
                    purpose="any_purpose",
                    measure="pre_rectifier_ac_rms",
                ),
            )
        }
    )

    rule = _project_system_voltage(fragment, facts)

    direct = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it", earthing_arrangement="it", input_topology="direct"
        ),
    )
    rectified = _lookup(
        rule,
        **_system_voltage_inputs(
            phase_system="three_phase_it",
            earthing_arrangement="it",
            input_topology="rectified_dc",
        ),
    )
    assert direct is not None and rectified is not None
    assert _value(direct, "system_voltage_measure") == "phase_to_phase_rms"
    assert _value(rectified, "system_voltage_measure") == "pre_rectifier_ac_rms"


# --- Task 6: SPD reduction/monitoring routes and HF attenuation follow reviewed facts ---


def _spd_inputs(**overrides: str | bool) -> dict[str, str | bool]:
    inputs: dict[str, str | bool] = {
        "device_placement": "internal_to_pecs",
        "insulation_class": "basic",
        "device_degradable": False,
        "part_of_category_reduction": True,
    }
    inputs.update(overrides)
    return inputs


_SPD_MAINS_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
_SPD_NON_MAINS_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"
_SPD_MONITORING_ID = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"


def _project_spd(fragment: RawClauseFragment, facts: ConfirmedFacts = _EMPTY_FACTS) -> DecisionRule:
    rules, _proposals = project_spd_reduction_requirements(
        fragment, IDENTITY, confirmed_facts=facts
    )
    # The produced rule's id is whichever route the fragment names -- there is no
    # longer one bare id to look up.
    return _decision(rules, fragment.id.removeprefix("raw-"))


def _frequency_tokens(
    *pairs: tuple[str, str],
) -> tuple[ClauseToken, ...]:
    """Invented quantity/unit token pairs; the real threshold is never in this repo."""

    tokens: list[ClauseToken] = []
    for quantity, unit in pairs:
        tokens.append(
            ClauseToken(
                kind="quantity",
                raw_text=quantity,
                normalized=Decimal(quantity),
                source=SOURCE,
            )
        )
        tokens.append(ClauseToken(kind="unit", raw_text=unit, normalized=unit, source=SOURCE))
    return tuple(tokens)


def _hf_fragment(*pairs: tuple[str, str]) -> RawClauseFragment:
    return _paragraph_fragment(
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        tokens=_frequency_tokens(*pairs) if pairs else (),
    )


def _project_hf_transformer(
    fragment: RawClauseFragment, facts: ConfirmedFacts = _EMPTY_FACTS
) -> DecisionRule:
    rules, _proposals = project_hf_transformer_attenuation(
        fragment, IDENTITY, confirmed_facts=facts
    )
    return _decision(rules, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION)


def _hf_inputs(**overrides: Decimal | str | bool) -> dict[str, Decimal | str | bool]:
    inputs: dict[str, Decimal | str | bool] = {
        "circuit_dvc": "dvc_b",
        "transformer_frequency_hz": Decimal(500000),
        "isolation_provided": True,
        "attenuation_evidence_kind": "test",
    }
    inputs.update(overrides)
    return inputs


def test_double_and_reinforced_insulation_keep_the_unreduced_floor() -> None:
    """A reviewed statement whose target repeats its source is the unreduced floor."""

    fragment = _spd_fragment("mains")
    facts = _confirmed_spd_facts(
        "mains",
        source_ovc="ovc_iii",
        target_ovc="ovc_iii",
        insulation_class="reinforced",
        fragment=fragment,
    )
    rule = _project_spd(fragment, facts)
    row = _lookup(rule, **_spd_inputs(insulation_class="reinforced"))
    assert row is not None
    assert _value(row, "reinforced_floor_applies") is True
    assert _value(row, "reduction_permitted") is False
    assert _value(row, "reduced_category") == "ovc_iii"


def test_a_degradable_device_requires_monitoring_and_indication() -> None:
    fragment = _spd_fragment("mains")
    facts = _confirmed_spd_facts(
        "mains",
        source_ovc="ovc_iii",
        target_ovc="ovc_ii",
        degradable=True,
        monitoring_obligation="required",
        fragment=fragment,
    )
    rule = _project_spd(fragment, facts)
    row = _lookup(rule, **_spd_inputs(device_degradable=True))
    assert row is not None
    assert _value(row, "monitoring_required") is True
    assert _value(row, "status_indication_required") is True
    assert _value(row, "reduction_permitted") is True
    assert _value(row, "reduced_category") == "ovc_ii"


def test_a_device_outside_a_category_reduction_is_not_covered() -> None:
    """The exemption moved from an explicit false-valued row to non-exhaustive coverage.

    No reviewed statement addresses a device outside a category reduction, so the rule
    leaves the branch uncovered rather than asserting an outcome nobody reviewed for it.
    """

    fragment = _spd_fragment("mains")
    facts = _confirmed_spd_facts(
        "mains", source_ovc="ovc_iii", target_ovc="ovc_ii", degradable=True, fragment=fragment
    )
    rule = _project_spd(fragment, facts)
    row = _lookup(rule, **_spd_inputs(device_degradable=True, part_of_category_reduction=False))
    assert row is None


def test_each_supply_kind_route_projects_its_own_rule() -> None:
    """Each supply kind is reviewed from its own clause, so one route cannot answer for both."""

    mains_fragment = _spd_fragment("mains")
    mains, _ = project_spd_reduction_requirements(
        mains_fragment,
        IDENTITY,
        confirmed_facts=_confirmed_spd_facts(
            "mains", source_ovc="ovc_iv", target_ovc="ovc_iii", fragment=mains_fragment
        ),
    )
    non_mains_fragment = _spd_fragment("non_mains")
    non_mains, _ = project_spd_reduction_requirements(
        non_mains_fragment,
        IDENTITY,
        confirmed_facts=_confirmed_spd_facts(
            "non_mains", source_ovc="ovc_iii", target_ovc="ovc_ii", fragment=non_mains_fragment
        ),
    )

    assert mains[0].id == _SPD_MAINS_ID
    assert non_mains[0].id == _SPD_NON_MAINS_ID


def test_the_reduced_category_comes_from_the_reviewed_fact() -> None:
    fragment = _spd_fragment("non_mains")
    facts = _confirmed_spd_facts(
        "non_mains", source_ovc="ovc_ii", target_ovc="ovc_i", fragment=fragment
    )
    rules, _ = project_spd_reduction_requirements(fragment, IDENTITY, confirmed_facts=facts)

    emitted = {
        value.categorical
        for row in rules[0].rows
        for value in row.values
        if value.name == "reduced_category"
    }
    assert emitted == {"ovc_i"}


def test_the_monitoring_route_follows_its_own_reviewed_facts() -> None:
    fragment = _spd_fragment("monitoring")
    facts = _confirmed_spd_monitoring_facts(
        monitoring_required=True, participates_in_reduction=True, fragment=fragment
    )
    rule = _project_spd(fragment, facts)
    row = _lookup(rule, **_spd_inputs(part_of_category_reduction=True))
    assert row is not None
    assert _value(row, "monitoring_required") is True
    assert _value(row, "status_indication_required") is True

    not_participating = _confirmed_spd_monitoring_facts(
        monitoring_required=False, participates_in_reduction=False, fragment=fragment
    )
    excused = _project_spd(fragment, not_participating)
    excused_row = _lookup(excused, **_spd_inputs(part_of_category_reduction=False))
    assert excused_row is not None
    assert _value(excused_row, "monitoring_required") is False


def test_one_exemption_statement_covers_every_reviewed_placement_and_no_other() -> None:
    """An unrestricted reading covers every placement a reviewed reading can name -- and stops there.

    Two halves. A reading placement does not restrict is authored once, not once per placement: a
    required single placement matched with ``equals`` left whichever one the maintainer did not pick
    reaching no row.

    And the half that was a real defect: this rule declares a placement the reviewed vocabulary
    deliberately cannot name, because what the source states about it is nothing. The unrestricted
    reading used to project a wildcard, which answered for that placement too -- contradicting the
    note beside the declared placements, which says a consumer asking about it must reach no match.
    An unrestricted scope now projects an ``in`` over the reviewed placements, so the unreviewed one
    reaches **no row at all**.
    """

    fragment = _spd_fragment("monitoring")
    facts = _confirmed_spd_monitoring_facts(
        fragment=fragment,
        device_placement="any_placement",
        participates_in_reduction=False,
        monitoring_required=False,
    )
    rule = _project_spd(fragment, facts)

    for placement in ("internal_to_pecs", "bundled_external_to_pecs"):
        row = _lookup(
            rule,
            **_spd_inputs(device_placement=placement, part_of_category_reduction=False),
        )
        assert row is not None, placement
        assert _value(row, "monitoring_required") is False

    # The placement no reviewed statement can name reaches no row, rather than borrowing the
    # unrestricted statement's answer.
    assert (
        _lookup(
            rule,
            **_spd_inputs(device_placement="external_to_pecs", part_of_category_reduction=False),
        )
        is None
    )


#: The phase systems a reviewed statement can name. Stated here independently of the recipe, so
#: these tests prove the reviewed domain rather than agreeing with whatever it computed. The rule's
#: own input declares two further states that no reviewed reading can name.
_REVIEWED_PHASE_SYSTEMS = frozenset(
    {"three_phase_star", "three_phase_delta", "three_phase_it", "single_phase_it"}
)


def _unrestricted_phase_system_rule() -> DecisionRule:
    """One statement restricting no phase system, projected. Invented values only."""

    fragment = _bullet_fragment()
    # Unrestricted on every other dimension, so only the phase system decides whether a query
    # matches and these tests cannot pass or fail for an unrelated reason.
    fact = _system_voltage_fact(
        fragment,
        phase_system="any_phase_system",
        earthing="any_earthing",
        input_topology="any_input_topology",
        purpose="any_purpose",
        measure="phase_to_earth_rms",
    )
    facts = ConfirmedFacts(by_route={ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (fact,)})
    rules, _proposals = project_system_voltage_resolution(fragment, IDENTITY, None, facts)
    return _decision(rules, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)


def test_an_unrestricted_reading_never_widens_to_a_consumer_only_phase_system() -> None:
    """The system-voltage half of the wildcard defect, asserted as a no-match.

    This rule's phase-system input declares two states no reviewed statement can name. An
    unrestricted reading used to project a wildcard, so it answered for both -- granting a reading
    the source never made to a question it never addressed. It now projects an ``in`` over the
    reviewed phase systems, and the consumer-only states reach no row at all.
    """

    rule = _unrestricted_phase_system_rule()

    for reviewed in _REVIEWED_PHASE_SYSTEMS:
        assert _lookup(rule, **_system_voltage_inputs(phase_system=reviewed)) is not None, reviewed

    for consumer_only in ("single_phase", "unspecified"):
        assert _lookup(rule, **_system_voltage_inputs(phase_system=consumer_only)) is None, (
            consumer_only
        )


def test_an_unrestricted_reading_projects_the_declared_domain_not_the_authored_one() -> None:
    """``reviewed_domain`` is the model's declared domain, never the values authored so far.

    Derived from the authored set instead, an unrestricted matcher would shrink as a side effect of
    how far review had progressed: a reviewer mid-authoring would get a narrower rule than the one
    they read, and it would silently widen again as they authored more. The one authored statement
    here names **no** concrete phase system at all, yet its row still covers every declared reviewed
    phase system -- which is only possible if the domain came from the model.
    """

    rule = _unrestricted_phase_system_rule()
    projected = {
        value
        for row in rule.rows
        for matcher in row.matchers
        if matcher.input == "phase_system"
        for value in matcher.values
    }

    # The one authored statement names no concrete phase system, yet the row enumerates the whole
    # declared reviewed domain -- which is only possible if the domain came from the model.
    assert projected == set(_REVIEWED_PHASE_SYSTEMS)
    for value in _REVIEWED_PHASE_SYSTEMS:
        assert _lookup(rule, **_system_voltage_inputs(phase_system=value)) is not None, value


def test_an_any_placement_statement_overlapping_a_specific_one_is_refused() -> None:
    """The other route where an unrestricted dimension can shadow a specific statement.

    Both statements gate on participation, so only placement separates them, and one of them
    restricts nothing: whichever was authored first would answer for the internal placement and
    the other's obligation would never be served.
    """

    fragment = _spd_fragment("monitoring")
    facts = ConfirmedFacts(
        by_route={
            _SPD_MONITORING_ID: (
                _spd_monitoring_fact(
                    fragment,
                    index=0,
                    device_placement="any_placement",
                    participates_in_reduction=True,
                    monitoring_required=False,
                ),
                _spd_monitoring_fact(
                    fragment,
                    index=1,
                    device_placement="internal_to_pecs",
                    participates_in_reduction=True,
                    monitoring_required=True,
                ),
            )
        }
    )

    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project_spd(fragment, facts)


def test_the_external_monitoring_obligation_keeps_its_qualifier() -> None:
    """The source's external-device requirement reaches only a device the manufacturer bundles.

    Answering it for a bare external placement would make a claim wider than the clause, so the
    qualifier is its own declared placement and an unqualified external device reaches no row.
    """

    fragment = _spd_fragment("monitoring")
    facts = _confirmed_spd_monitoring_facts(
        fragment=fragment,
        device_placement="bundled_external_to_pecs",
        participates_in_reduction=True,
        monitoring_required=True,
    )
    rule = _project_spd(fragment, facts)

    qualified = _lookup(rule, **_spd_inputs(device_placement="bundled_external_to_pecs"))
    assert qualified is not None
    assert _value(qualified, "monitoring_required") is True
    assert _lookup(rule, **_spd_inputs(device_placement="external_to_pecs")) is None


def test_two_reduction_statements_stating_the_same_branch_are_refused() -> None:
    """The pair a fact-level comparison would miss: same dimensions, different answers.

    ``target_ovc`` is an answer rather than a branch dimension, so these two facts are not equal
    and only their projected matchers are. The refusal therefore has to be expressed over the
    rows, which is why it lives in the projector rather than in resolution.
    """

    fragment = _spd_fragment("mains")
    facts = ConfirmedFacts(
        by_route={
            _SPD_MAINS_ID: (
                _spd_reduction_fact(
                    fragment,
                    index=0,
                    supply_kind="mains",
                    source_ovc="ovc_iv",
                    target_ovc="ovc_iii",
                ),
                _spd_reduction_fact(
                    fragment,
                    index=1,
                    supply_kind="mains",
                    source_ovc="ovc_iv",
                    target_ovc="ovc_ii",
                ),
            )
        }
    )

    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project_spd(fragment, facts)


def test_spd_keeps_its_declared_contract() -> None:
    fragment = _spd_fragment("mains")
    facts = _confirmed_spd_facts(
        "mains", source_ovc="ovc_iii", target_ovc="ovc_ii", fragment=fragment
    )
    rule = _project_spd(fragment, facts)

    assert {item.name for item in rule.inputs} == {
        "device_placement",
        "insulation_class",
        "device_degradable",
        "part_of_category_reduction",
    }
    assert {item.name for item in rule.outputs} == {
        "reduction_permitted",
        "reduced_category",
        "monitoring_required",
        "status_indication_required",
        "verification_reference",
        "reinforced_floor_applies",
    }
    assert _declared_vocabularies(rule) == {
        "device_placement": ("internal_to_pecs", "external_to_pecs", "bundled_external_to_pecs"),
        "insulation_class": ("functional", "basic", "supplementary", "double", "reinforced"),
    }


def test_each_spd_route_is_projected_under_its_own_id() -> None:
    """The projector is registered once per route and shares one body.

    Each route's fragment must still come back out under that route's own rule id.
    """

    for route in ("mains", "non_mains"):
        fragment = _spd_fragment(route)
        facts = _confirmed_spd_facts(
            route, source_ovc="ovc_iii", target_ovc="ovc_ii", fragment=fragment
        )
        rule = _project_spd(fragment, facts)
        assert rule.id == f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.{route}"

    fragment = _spd_fragment("monitoring")
    facts = _confirmed_spd_monitoring_facts(monitoring_required=True, fragment=fragment)
    rule = _project_spd(fragment, facts)
    assert rule.id == _SPD_MONITORING_ID


def test_every_reduction_route_enforces_its_reviewed_shape() -> None:
    """All three routes' shapes are measured, so a reflowed clause blocks on any of them.

    Each route reads its own clause through its own bbox, so a reprint that splits one of
    them across a different number of nodes must stop the build rather than project a rule
    from a region nobody reviewed. The shape check fires before the facts check, so no
    facts need to be supplied here.
    """

    for route_id in (_SPD_MONITORING_ID, _SPD_MAINS_ID, _SPD_NON_MAINS_ID):
        malformed = _paragraph_fragment(route_id, count=2)
        with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
            project_spd_reduction_requirements(malformed, IDENTITY)


def test_spd_refuses_to_project_without_facts() -> None:
    for route_id in (_SPD_MAINS_ID, _SPD_NON_MAINS_ID, _SPD_MONITORING_ID):
        with pytest.raises(ClauseStructureError):
            project_spd_reduction_requirements(
                _paragraph_fragment(route_id), IDENTITY, confirmed_facts=ConfirmedFacts()
            )


def test_hf_attenuation_follows_the_reviewed_facts() -> None:
    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test", "simulation"), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)

    accepted = {
        matcher.values
        for row in rule.rows
        for matcher in row.matchers
        if matcher.input == "attenuation_evidence_kind"
    }
    # One row per reviewed statement, plus the one outstanding-showing row the gate carries.
    assert accepted == {("test",), ("simulation",), ("none",)}


def test_a_reviewed_evidence_kind_permits_the_working_voltage_basis() -> None:
    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test",), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)
    row = _lookup(rule, **_hf_inputs(attenuation_evidence_kind="test"))
    assert row is not None
    assert _value(row, "working_voltage_basis_permitted") is True
    assert _value(row, "required_evidence_kinds") == "already_provided"


def test_no_evidence_yet_is_answered_rather_than_refused() -> None:
    """The first question a consumer asks: nothing shown yet, so what must be shown?

    ``none`` is part of this input's declared question space and no reviewed statement can name
    it, so a vocabulary derived from the facts put the question outside the input's allowed
    values and raised instead of answering. The route is an engineering-input requirement until
    the attenuation is shown, never a permission.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test",), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)
    row = _lookup(rule, **_hf_inputs(attenuation_evidence_kind="none"))
    assert row is not None
    assert _value(row, "working_voltage_basis_permitted") is False
    assert _value(row, "required_evidence_kinds") == "test_or_simulation_or_calculation"


def test_one_statement_may_accept_every_evidence_route_it_names() -> None:
    """A reading not restricted to one evidence route is authored once, not once per route.

    Authoring it per route would record several readings where the reviewer recorded one, and
    picking a single route would leave the others reaching no row at all.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("any_evidence",), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)

    for kind in ("test", "simulation", "calculation"):
        row = _lookup(rule, **_hf_inputs(attenuation_evidence_kind=kind))
        assert row is not None, kind
        assert _value(row, "working_voltage_basis_permitted") is True
        assert _value(row, "required_evidence_kinds") == "already_provided"

    # The absence of evidence is not one of the routes the statement accepts.
    outstanding = _lookup(rule, **_hf_inputs(attenuation_evidence_kind="none"))
    assert outstanding is not None
    assert _value(outstanding, "working_voltage_basis_permitted") is False


def test_an_any_evidence_statement_overlapping_a_specific_one_is_refused() -> None:
    """Two statements under one gate, sharing one accepted evidence kind between them.

    Equality alone would miss this: the ``in`` row this ``any_evidence`` statement projects and
    the ``equals`` row the ``test`` statement projects are never equal and neither is ``any``, so
    a comparison by equality would call them disjoint even though both answer for ``test`` -- the
    ``in`` row would then shadow the ``equals`` row over that value permanently.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("any_evidence", "test"), fragment=fragment)

    with pytest.raises(ClauseStructureError, match="not disjoint"):
        _project_hf_transformer(fragment, facts)


def test_a_dvc_gate_no_fact_states_is_not_covered() -> None:
    """No fallback: a DVC designation no reviewed fact gates through is left uncovered.

    ``circuit_dvc`` keeps its full declared vocabulary (``_DVC_DESIGNATIONS``) independent of
    the reviewed facts, so a designation the rule does declare but no fact's ``dvc_gate``
    names -- ``dvc_as`` here, against a fact stating ``dvc_b`` -- still needs to fall through
    to no match rather than a guessed one.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(
        evidence_kinds=("test",), dvc_gate=DimensionScope.of("dvc_b"), fragment=fragment
    )
    rule = _project_hf_transformer(fragment, facts)
    assert _lookup(rule, **_hf_inputs(circuit_dvc="dvc_as")) is None


def test_one_statement_naming_both_gates_is_one_statement_and_one_row() -> None:
    """A reading naming several designations is one statement, and projects one row over them.

    Authored as a scalar it had to be authored twice: two reviews, two rows and two drafts for one
    reading, with the fact-set digest happily covering the duplicate. One row over both is what a
    single reviewed statement is.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(
        evidence_kinds=("test",),
        dvc_gate=DimensionScope.of("dvc_b", "dvc_as"),
        fragment=fragment,
    )
    rule = _project_hf_transformer(fragment, facts)

    shown = [
        row
        for row in rule.rows
        if any(
            matcher.input == "attenuation_evidence_kind" and matcher.values == ("test",)
            for matcher in row.matchers
        )
    ]
    assert len(shown) == 1
    gate = next(matcher for matcher in shown[0].matchers if matcher.input == "circuit_dvc")
    assert (gate.op, gate.values) == ("in", ("dvc_as", "dvc_b"))
    for designation in ("dvc_as", "dvc_b"):
        row = _lookup(rule, **_hf_inputs(circuit_dvc=designation))
        assert row is not None, designation
        assert _value(row, "working_voltage_basis_permitted") is True


def test_an_unrestricted_gate_reading_stops_at_the_reviewed_designations() -> None:
    """A2-C, on this route: unrestricted is unrestricted within the *reviewed* domain.

    The rule declares a third designation the reviewed vocabulary deliberately cannot name, so a
    wildcard would answer for a designation no reviewed statement mentions -- and would answer that
    the working-voltage basis is permitted for it.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(
        evidence_kinds=("test",),
        dvc_gate=DimensionScope[str].unrestricted(),
        fragment=fragment,
    )
    rule = _project_hf_transformer(fragment, facts)

    for designation in ("dvc_as", "dvc_b"):
        assert _lookup(rule, **_hf_inputs(circuit_dvc=designation)) is not None, designation
    assert _lookup(rule, **_hf_inputs(circuit_dvc="dvc_c")) is None
    assert (
        _lookup(rule, **_hf_inputs(circuit_dvc="dvc_c", attenuation_evidence_kind="none")) is None
    )


def test_hf_attenuation_refuses_to_project_without_facts() -> None:
    with pytest.raises(ClauseStructureError):
        project_hf_transformer_attenuation(
            _hf_fragment(("42", "kHz")), IDENTITY, confirmed_facts=ConfirmedFacts()
        )


def test_hf_attenuation_keeps_its_declared_contract() -> None:
    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test",), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)

    assert {item.name for item in rule.inputs} == {
        "circuit_dvc",
        "transformer_frequency_hz",
        "isolation_provided",
        "attenuation_evidence_kind",
    }
    assert {item.name for item in rule.outputs} == {
        "working_voltage_basis_permitted",
        "required_evidence_kinds",
    }
    assert _declared_vocabularies(rule) == {
        "circuit_dvc": ("dvc_as", "dvc_b", "dvc_c"),
        "attenuation_evidence_kind": ("none", "test", "simulation", "calculation"),
    }
    # What must still be shown, not an echo of what the consumer supplied.
    required = next(item for item in rule.outputs if item.name == "required_evidence_kinds")
    assert required.allowed_values == ("test_or_simulation_or_calculation", "already_provided")


def test_the_transformer_threshold_is_read_from_the_fragment_not_declared() -> None:
    bounds = {}
    for quantity, unit, expected in (("42", "kHz", "42000"), ("3", "MHz", "3000000")):
        fragment = _hf_fragment((quantity, unit))
        facts = _confirmed_hf_facts(evidence_kinds=("test",), fragment=fragment)
        rule = _project_hf_transformer(fragment, facts)
        matcher = next(
            matcher
            for row in rule.rows
            for matcher in row.matchers
            if matcher.input == "transformer_frequency_hz"
        )
        bounds[expected] = matcher.minimum
        assert matcher.minimum == Decimal(expected)
    assert len(set(bounds.values())) == 2


def test_a_frequency_below_the_extracted_threshold_is_not_covered() -> None:
    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test",), fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)
    assert _lookup(rule, **_hf_inputs(transformer_frequency_hz=Decimal(100))) is None


def test_a_transformer_fragment_without_a_frequency_pair_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_hf_transformer_attenuation(_hf_fragment(), IDENTITY)


def test_a_transformer_fragment_with_two_frequency_pairs_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_hf_transformer_attenuation(_hf_fragment(("42", "kHz"), ("7", "MHz")), IDENTITY)


def test_no_supply_recipe_file_declares_a_frequency_threshold() -> None:
    """The licensed thresholds are extracted at import time, never committed.

    Unit names may appear (the projection has to recognise them); a number written
    next to one would be a declared threshold, which is what this guard forbids.
    """

    directory = Path("src/insulation_coordination/rules/importer/recipes/iec62477_1_2022")
    paths = sorted(directory.glob("*.py"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"[0-9][^\S\n]*[\"']?[^\S\n]*(?:k|M)?Hz", text) is None, path


def test_the_recipe_declares_and_registers_every_supply_clause() -> None:
    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}
    rule_producing = {spec.semantic_id for spec in SUPPLY_CLAUSES if spec.projection_role == "rule"}
    assert declared <= {spec.semantic_id for spec in IEC_RECIPE.clauses}
    assert rule_producing <= set(IEC_RECIPE.clause_projectors)
    # The evidence-only clause contributes reviewed facts and must have no projector at all.
    assert not (declared - rule_producing) & set(IEC_RECIPE.clause_projectors)
    assert {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        _SPD_MAINS_ID,
        _SPD_NON_MAINS_ID,
        _SPD_MONITORING_ID,
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
    } <= declared
    assert all(spec.output_kind == "decision" for spec in SUPPLY_CLAUSES)
    assert all(
        65.0 <= segment.expected_bbox[0] for spec in SUPPLY_CLAUSES for segment in spec.segments
    )


def test_the_reduction_rule_is_read_from_the_clauses_that_state_it() -> None:
    """The identifier previously pointed at the monitoring clause, which does not state the rule.

    Each supply kind is reviewed from its own clause, so the identifier carries a route per
    supply kind rather than one rule answering for both.
    """
    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[_SPD_MAINS_ID]
    non_mains = by_id[_SPD_NON_MAINS_ID]
    monitoring = by_id[_SPD_MONITORING_ID]

    assert (mains.clause, mains.segments[0].page_number) == ("4.4.7.2.3", 65)
    assert (non_mains.clause, non_mains.segments[0].page_number) == ("4.4.7.2.4", 66)
    assert (monitoring.clause, monitoring.segments[0].page_number) == ("4.4.7.2.2", 65)


def test_no_supply_route_reads_a_clause_that_does_not_state_its_rule() -> None:
    """Guard against the defect returning: the bare reduction id must declare no fragment."""

    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}

    assert ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS not in declared


# --- Task 6B: one rule, two subclauses, one physical clause in several segments ------


def test_the_mains_subclause_declares_three_regions_in_reading_order() -> None:
    """Measured against the licensed document: two pages, three regions, one clause.

    A page-per-segment reading would reach only the middle region and drop the rest, while
    looking like a fix.
    """

    spec = next(
        item for item in SUPPLY_CLAUSES if item.semantic_id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )

    assert [segment.page_number for segment in spec.segments] == [63, 64, 64]
    assert [segment.expected_root_kind for segment in spec.segments] == [
        "bullets",
        "bullets",
        "paragraph",
    ]
    # Contiguous rather than overlapping on the shared page, so no line of the clause can fall
    # between two of its own regions unnoticed.
    assert spec.segments[1].expected_bbox[3] == spec.segments[2].expected_bbox[1]


def test_the_non_mains_subclause_is_its_own_fragment_and_this_rules_evidence() -> None:
    """Two subclauses, one rule: neither one fragment spanning both nor one route per page."""

    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION]
    evidence = by_id[SUPPLY_SYSTEM_VOLTAGE_NON_MAINS]

    assert mains.evidence_clause_ids == (SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,)
    assert evidence.projection_role == "evidence"
    assert evidence.projected_rule_ids == ()
    assert evidence.clause != mains.clause
    assert SUPPLY_SYSTEM_VOLTAGE_NON_MAINS not in mains.projected_rule_ids


def test_an_orphaned_evidence_only_spec_is_refused_at_import() -> None:
    """An evidence-only spec nobody references is extracted, gated, and reaches no rule.

    ``clause evidence must be a declared evidence-only clause spec`` already refuses the other
    direction (a rule naming evidence that is not declared evidence-only); this is its converse.
    """

    mains = next(
        spec
        for spec in IEC_RECIPE.clauses
        if spec.semantic_id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )
    orphaning = mains.model_copy(update={"evidence_clause_ids": ()})
    clauses = tuple(
        orphaning if spec.semantic_id == mains.semantic_id else spec for spec in IEC_RECIPE.clauses
    )

    with pytest.raises(ValueError, match="referenced by a rule-producing clause"):
        StandardRecipe.model_validate(
            {name: getattr(IEC_RECIPE, name) for name in type(IEC_RECIPE).model_fields}
            | {"clauses": clauses}
        )


def test_both_evidence_scopes_reach_the_one_projected_rule() -> None:
    """One rule and one proposal out, whichever subclause a given statement came from."""

    mains_fragment = _bullet_fragment()
    evidence_fragment = _non_mains_evidence_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(
                    mains_fragment,
                    index=0,
                    supply_kind="mains",
                    measure="phase_to_artificial_neutral_rms",
                ),
            ),
            SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: (
                _system_voltage_fact(
                    evidence_fragment,
                    index=0,
                    supply_kind="non_mains",
                    phase_system="any_phase_system",
                    earthing="any_earthing",
                    purpose="any_purpose",
                    measure="phase_to_phase_rms",
                ),
            ),
        }
    )

    rules, proposals = project_system_voltage_resolution(
        mains_fragment,
        IDENTITY,
        _StubDraft((mains_fragment, evidence_fragment)),
        facts,
    )
    rule = _decision(rules, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)

    assert len([item for item in rules if isinstance(item, DecisionRule)]) == 1
    assert [proposal.semantic_id for proposal in proposals] == [
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
    ]
    # A reviewed phase system, not the consumer-only one: an unrestricted reading covers the
    # reviewed domain and deliberately stops there -- see the dedicated regression below.
    non_mains = _lookup(
        rule,
        **_system_voltage_inputs(supply_kind="non_mains", phase_system="single_phase_it"),
    )
    mains = _lookup(
        rule,
        **_system_voltage_inputs(
            supply_kind="mains", phase_system="three_phase_it", earthing_arrangement="it"
        ),
    )
    assert non_mains is not None and mains is not None
    assert _value(non_mains, "system_voltage_measure") == "phase_to_phase_rms"
    assert _value(mains, "system_voltage_measure") == "phase_to_artificial_neutral_rms"
    # Each row cites the node its own statement rests on, so a row read from the sibling
    # subclause does not name the page the rule's own fragment starts on.
    assert [row.source.page for row in rule.rows] == [
        mains_fragment.nodes[0].source.page,
        evidence_fragment.nodes[0].source.page,
    ]


def test_a_two_scope_collision_names_which_scope_each_statement_came_from() -> None:
    """A mains statement and a non-mains statement can share one statement_index.

    ``statement_index`` is numbered per route, so a mains statement 0 and a non-mains statement
    0 that overlap would otherwise both report as "statement 0", naming no subclause.
    """

    mains_fragment = _bullet_fragment()
    evidence_fragment = _non_mains_evidence_fragment()
    facts = ConfirmedFacts(
        by_route={
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: (
                _system_voltage_fact(mains_fragment, index=0, measure="phase_to_phase_rms"),
            ),
            SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: (
                _system_voltage_fact(
                    evidence_fragment, index=0, measure="phase_to_artificial_neutral_rms"
                ),
            ),
        }
    )

    with pytest.raises(ClauseStructureError) as excinfo:
        project_system_voltage_resolution(
            mains_fragment,
            IDENTITY,
            _StubDraft((mains_fragment, evidence_fragment)),
            facts,
        )

    message = str(excinfo.value)
    assert "not disjoint" in message
    assert ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION in message
    assert SUPPLY_SYSTEM_VOLTAGE_NON_MAINS in message


def test_the_proposal_is_grounded_in_both_fragments() -> None:
    """Either fragment changing has to make the one rule's one proposal stale."""

    mains_fragment = _bullet_fragment()
    evidence_fragment = _non_mains_evidence_fragment()
    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms",), fragment=mains_fragment
    )

    def _proposal_digest(fragments: tuple[RawClauseFragment, ...]) -> str:
        _rules, proposals = project_system_voltage_resolution(
            mains_fragment, IDENTITY, _StubDraft(fragments), facts
        )
        return proposals[0].source_artifact_sha256

    corrected_node = evidence_fragment.nodes[0].model_copy(
        update={"raw_text": "synthetic neutral paragraph node 0 corrected"}
    )
    both = _proposal_digest((mains_fragment, evidence_fragment))
    changed_evidence = _proposal_digest(
        (mains_fragment, evidence_fragment.model_copy(update={"nodes": (corrected_node,)})),
    )

    assert both != canonical_model_sha256(mains_fragment)
    assert both != changed_evidence
    assert both == aggregate_artifact_sha256(
        (
            (mains_fragment.id, canonical_model_sha256(mains_fragment)),
            (evidence_fragment.id, canonical_model_sha256(evidence_fragment)),
        )
    )


def test_the_gate_grounds_a_two_scope_rule_in_both_the_digest_and_the_review_item() -> None:
    """The approval gate's own lookups, not just the projector's output.

    Deleting either the digest aggregation (``_current_source_artifact_sha256``) or the
    evidence review-item gating (``_required_review_items``) leaves the projector's own tests
    green: they only inspect what the projector returns, never what the gate recomputes from a
    draft. This calls the gate's private lookups directly.
    """

    mains_fragment = _bullet_fragment()
    evidence_fragment = _non_mains_evidence_fragment()
    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms",), fragment=mains_fragment
    )
    rules, proposals = project_system_voltage_resolution(
        mains_fragment,
        IDENTITY,
        _StubDraft((mains_fragment, evidence_fragment)),
        facts,
    )
    rule = _decision(rules, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)
    proposal = next(
        item for item in proposals if item.semantic_id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )
    draft = _grounded_draft(rule, (mains_fragment, evidence_fragment))

    required = review._required_review_items(draft, proposal)
    assert any(item.semantic_id == SUPPLY_SYSTEM_VOLTAGE_NON_MAINS for item in required)

    assert proposal.source_artifact_sha256 == review._current_source_artifact_sha256(
        draft, proposal
    )


def test_the_evidence_fragment_must_carry_its_own_reviewed_shape() -> None:
    """The second fragment is read as evidence, so its shape is checked like the first's."""

    mains_fragment = _bullet_fragment()
    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms",), fragment=mains_fragment
    )
    reflowed = _fragment(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, kind="bullet", count=2)

    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_system_voltage_resolution(
            mains_fragment, IDENTITY, _StubDraft((mains_fragment, reflowed)), facts
        )


def test_declaration_order_of_the_two_clause_specs_does_not_decide_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit role is what makes this true, rather than "the first declared spec wins".

    Reversing the two specs must leave the projected rule and its provenance identical: any
    accidental first-match dependency in resolution or grounding fails here. Varying only the
    fragment order in a stub draft (below) cannot exercise that claim: the gate's own lookups
    (``_source_semantic_id``, ``_current_source_artifact_sha256``, ``_required_review_items``)
    walk ``recipes.RECIPES``, not a draft's fragment order, so they only run under the reversed
    recipe when ``RECIPES`` itself is swapped.
    """

    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION]
    evidence = by_id[SUPPLY_SYSTEM_VOLTAGE_NON_MAINS]
    reversed_clauses = (
        evidence,
        mains,
        *(
            item
            for item in IEC_RECIPE.clauses
            if item.semantic_id not in {mains.semantic_id, evidence.semantic_id}
        ),
    )
    # The recipe validator accepts either order, which is itself part of the claim.
    reordered = StandardRecipe.model_validate(
        {name: getattr(IEC_RECIPE, name) for name in type(IEC_RECIPE).model_fields}
        | {"clauses": reversed_clauses}
    )
    assert [spec.semantic_id for spec in reordered.clauses][:2] == [
        evidence.semantic_id,
        mains.semantic_id,
    ]

    mains_fragment = _bullet_fragment()
    evidence_fragment = _non_mains_evidence_fragment()
    facts = _confirmed_system_voltage_facts(
        measures=("phase_to_phase_rms",), fragment=mains_fragment
    )
    forward, forward_proposals = project_system_voltage_resolution(
        mains_fragment, IDENTITY, _StubDraft((mains_fragment, evidence_fragment)), facts
    )
    backward, backward_proposals = project_system_voltage_resolution(
        mains_fragment, IDENTITY, _StubDraft((evidence_fragment, mains_fragment)), facts
    )

    assert forward == backward
    assert forward_proposals == backward_proposals

    rule = _decision(forward, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)
    proposal = next(
        item
        for item in forward_proposals
        if item.semantic_id == ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION
    )
    draft = _grounded_draft(rule, (mains_fragment, evidence_fragment))

    def _gate_readings() -> tuple[str, str, tuple[str, ...]]:
        return (
            review._source_semantic_id(proposal),
            review._current_source_artifact_sha256(draft, proposal),
            tuple(item.semantic_id for item in review._required_review_items(draft, proposal)),
        )

    unreversed_readings = _gate_readings()
    reversed_recipes = tuple(
        reordered if item.id == IEC_RECIPE.id else item for item in recipe_registry.RECIPES
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", reversed_recipes)
    reversed_readings = _gate_readings()

    assert unreversed_readings == reversed_readings
