"""Synthetic supply-clause projections. Invented values only; no IEC content."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    DecisionRule,
    GuidanceRule,
    SourceReference,
)
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    CitedNode,
    ConfirmedFacts,
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
from insulation_coordination.rules.importer.extract import canonical_model_sha256
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    SUPPLY_CLAUSES,
    project_hf_transformer_attenuation,
    project_multiple_source_propagation,
    project_spd_reduction_requirements,
    project_system_voltage_resolution,
    project_verified_barrier_transfer,
)

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


def _fragment(
    semantic_id: str,
    *,
    kind: str = "bullet",
    count: int = 1,
    tokens: tuple[ClauseToken, ...] = (),
) -> RawClauseFragment:
    nodes = tuple(
        ClauseNode(
            order=order,
            kind=kind,
            raw_text=f"synthetic neutral {kind} node {order}",
            source=SOURCE.model_copy(update={"row": f"node {order}"}),
        )
        for order in range(count)
    )
    fragment = RawClauseFragment(
        id=f"raw-{semantic_id}",
        raw_sha256="0" * 64,
        nodes=nodes,
        tokens=tokens,
        source=SOURCE,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def _bullet_fragment(*, count: int = 3) -> RawClauseFragment:
    return _fragment(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, kind="bullet", count=count)


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
    phase_system: str = "three_phase_it",
    earthing: str = "it",
    purpose: str = "impulse",
    measure: str,
) -> SystemVoltageFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return SystemVoltageFact(
        statement_index=index,
        node_references=(_cited_node(fragment, node_order=index % len(fragment.nodes)),),
        obligation="requirement",
        phase_system=phase_system,  # type: ignore[arg-type]
        earthing=earthing,  # type: ignore[arg-type]
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
    dvc_gate: str = "dvc_b",
    evidence_kind: str,
) -> HfAttenuationFact:
    """Invented values only: a synthetic reviewed statement, never real clause content."""

    return HfAttenuationFact(
        statement_index=index,
        node_references=(_cited_node(fragment),),
        obligation="requirement",
        dvc_gate=dvc_gate,  # type: ignore[arg-type]
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
        threshold_reference=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        comparison_required=True,
    )


def _confirmed_hf_facts(
    *,
    evidence_kinds: tuple[str, ...],
    dvc_gate: str = "dvc_b",
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

    The coordinator's clarification for #53B Task 5: the source states this branch as one
    bullet, not two, so authoring it as two facts differing only in purpose would record two
    statements where the source makes one. The two purpose-specific facts still yield their
    own, separate rows alongside it.
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


def test_a_fragment_whose_bullet_count_differs_blocks() -> None:
    with pytest.raises(ClauseStructureError, match="AMBIGUOUS_CLAUSE_STRUCTURE"):
        project_system_voltage_resolution(_bullet_fragment(count=7), IDENTITY)


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

    with pytest.raises(ClauseStructureError, match="same branch"):
        _project_system_voltage(fragment, facts)


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
    """The source states the reduction twice, so one route cannot answer for both."""

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


def test_one_exemption_statement_covers_every_placement_it_is_stated_for() -> None:
    """The source states the exemption once, for both monitoring obligations together.

    A required single placement matched with ``equals`` could not express that: authoring the one
    statement left whichever placement the maintainer did not pick reaching no row, so the same
    query answered for one placement and fell through for the other.
    """

    fragment = _spd_fragment("monitoring")
    facts = _confirmed_spd_monitoring_facts(
        fragment=fragment,
        device_placement="any_placement",
        participates_in_reduction=False,
        monitoring_required=False,
    )
    rule = _project_spd(fragment, facts)

    for placement in ("internal_to_pecs", "external_to_pecs", "bundled_external_to_pecs"):
        row = _lookup(
            rule,
            **_spd_inputs(device_placement=placement, part_of_category_reduction=False),
        )
        assert row is not None, placement
        assert _value(row, "monitoring_required") is False


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

    with pytest.raises(ClauseStructureError, match="same branch"):
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
    """The source states its evidence routes as one disjunction inside one statement.

    Authoring it as one fact per route would record several statements where the source makes
    one, and picking a single route would leave the others reaching no row at all.
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


def test_a_dvc_gate_no_fact_states_is_not_covered() -> None:
    """No fallback: a DVC designation no reviewed fact gates through is left uncovered.

    ``circuit_dvc`` keeps its full declared vocabulary (``_DVC_DESIGNATIONS``) independent of
    the reviewed facts, so a designation the rule does declare but no fact's ``dvc_gate``
    names -- ``dvc_as`` here, against a fact stating ``dvc_b`` -- still needs to fall through
    to no match rather than a guessed one.
    """

    fragment = _hf_fragment(("42", "kHz"))
    facts = _confirmed_hf_facts(evidence_kinds=("test",), dvc_gate="dvc_b", fragment=fragment)
    rule = _project_hf_transformer(fragment, facts)
    assert _lookup(rule, **_hf_inputs(circuit_dvc="dvc_as")) is None


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
    assert declared <= {spec.semantic_id for spec in IEC_RECIPE.clauses}
    assert declared <= set(IEC_RECIPE.clause_projectors)
    assert {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        _SPD_MAINS_ID,
        _SPD_NON_MAINS_ID,
        _SPD_MONITORING_ID,
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
    } <= declared
    assert all(spec.output_kind == "decision" for spec in SUPPLY_CLAUSES)
    assert all(65.0 <= spec.expected_bbox[0] for spec in SUPPLY_CLAUSES)


def test_the_reduction_rule_is_read_from_the_clauses_that_state_it() -> None:
    """The identifier previously pointed at the monitoring clause, which does not state the rule.

    The reduction is stated once for mains supply and once for non-mains supply, with different
    permitted category steps, so it is two routes of one family rather than one rule.
    """
    by_id = {spec.semantic_id: spec for spec in SUPPLY_CLAUSES}
    mains = by_id[_SPD_MAINS_ID]
    non_mains = by_id[_SPD_NON_MAINS_ID]
    monitoring = by_id[_SPD_MONITORING_ID]

    assert (mains.clause, mains.page_number) == ("4.4.7.2.3", 65)
    assert (non_mains.clause, non_mains.page_number) == ("4.4.7.2.4", 66)
    assert (monitoring.clause, monitoring.page_number) == ("4.4.7.2.2", 65)


def test_no_supply_route_reads_a_clause_that_does_not_state_its_rule() -> None:
    """Guard against the defect returning: the bare reduction id must declare no fragment."""

    declared = {spec.semantic_id for spec in SUPPLY_CLAUSES}

    assert ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS not in declared
