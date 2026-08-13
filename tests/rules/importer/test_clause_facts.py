"""Fact models: typed per family, and bound to exactly the evidence they cite."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from insulation_coordination.rules.importer.approval import record_correction
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ClauseFactCompletion,
    ClauseFactReview,
    ConfirmedFacts,
    SpdMonitoringFact,
    SpdReductionFact,
    SystemVoltageFact,
    evidence_sha256,
)
from insulation_coordination.rules.importer.extract import (
    canonical_model_sha256,
    draft_content_digest,
)

# draft_with_axis_proposals is a shared fixture; see tests/conftest.py.


def _spd_fact() -> SpdReductionFact:
    return SpdReductionFact(
        statement_index=0,
        node_references=(CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),),
        obligation="permission",
        supply_kind="mains",
        source_ovc="ovc_iv",
        target_ovc="ovc_iii",
        insulation_class="basic",
        degradable=True,
        monitoring_obligation="required",
        monitoring_reference="iec62477_2022.supply.spd_reduction_requirements.monitoring",
    )


def test_each_family_is_its_own_type_under_one_discriminator() -> None:
    fact = _spd_fact()
    system = SystemVoltageFact(
        statement_index=1,
        node_references=(CitedNode(fragment_id="raw-b", node_order=2, node_sha256="b" * 64),),
        obligation="requirement",
        phase_system="three_phase_it",
        earthing="it",
        purpose="impulse",
        measure="phase_to_artificial_neutral_rms",
    )

    assert fact.fact_kind == "spd_reduction"
    assert system.fact_kind == "system_voltage"


def test_monitoring_is_its_own_family_and_reduction_carries_no_placement() -> None:
    """Placement is monitoring semantics. Reduction refers to monitoring, never restates it.

    The source states reduction and monitoring in separate clauses: reduction defines the
    permitted category step and its floor, monitoring gates the obligation on whether the
    device is bundled externally or internal and on whether it takes part in a reduction at
    all. A single family carrying both would give every reduction statement a placement field
    its own clause never mentions.
    """

    monitoring = SpdMonitoringFact(
        statement_index=0,
        node_references=(CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),),
        obligation="requirement",
        device_placement="external_to_pecs",
        participates_in_reduction=True,
        monitoring_required=True,
        compliance_evidence="visual_inspection",
    )

    assert monitoring.fact_kind == "spd_monitoring"
    assert "device_placement" not in SpdReductionFact.model_fields
    assert "participates_in_reduction" not in SpdReductionFact.model_fields
    assert "device_placement" in SpdMonitoringFact.model_fields
    assert _spd_fact().monitoring_reference.endswith(".monitoring")


def test_a_fact_must_cite_at_least_one_node() -> None:
    """A statement with no evidence could not go stale, which defeats the whole mechanism."""

    with pytest.raises(ValidationError):
        SpdReductionFact(
            statement_index=0,
            node_references=(),
            obligation="permission",
            supply_kind="mains",
            source_ovc="ovc_iv",
            target_ovc="ovc_iii",
            insulation_class="basic",
            degradable=True,
            monitoring_obligation="required",
            monitoring_reference="iec62477_2022.supply.spd_reduction_requirements.monitoring",
        )


def test_the_evidence_digest_covers_every_cited_node_and_ignores_order_of_citation() -> None:
    first = CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64)
    second = CitedNode(fragment_id="raw-b", node_order=3, node_sha256="b" * 64)

    assert evidence_sha256((first, second)) == evidence_sha256((second, first))


def test_a_changed_cited_node_changes_the_evidence_digest() -> None:
    original = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),)
    changed = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="c" * 64),)

    assert evidence_sha256(original) != evidence_sha256(changed)


def test_a_reordered_node_changes_the_evidence_digest() -> None:
    """A node's order is part of the identity a fact cited, so a reorder invalidates."""

    original = (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),)
    moved = (CitedNode(fragment_id="raw-a", node_order=1, node_sha256="a" * 64),)

    assert evidence_sha256(original) != evidence_sha256(moved)


def test_a_review_carries_the_authored_fact_and_both_digests() -> None:
    fact = _spd_fact()
    review = ClauseFactReview(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        statement_index=0,
        fact=fact,
        fact_sha256="d" * 64,
        evidence_sha256=evidence_sha256(fact.node_references),
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="authored",
    )

    assert review.fact == fact
    assert ClauseFactReview.model_validate(review.model_dump(mode="json")) == review


def test_completion_is_scoped_to_a_route_and_binds_both_hashes() -> None:
    completion = ClauseFactCompletion(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        fragment_id="raw-a",
        fragment_sha256="e" * 64,
        fact_set_sha256="f" * 64,
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="complete for this route",
    )

    assert completion.rule_route.endswith(".mains")


def _review_of(fact: SpdReductionFact) -> ClauseFactReview:
    return ClauseFactReview(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        statement_index=fact.statement_index,
        fact=fact,
        fact_sha256=canonical_model_sha256(fact),
        evidence_sha256=evidence_sha256(fact.node_references),
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="authored",
    )


def test_a_recorded_fact_review_is_a_content_change(draft_with_axis_proposals) -> None:
    """A collection the digest does not cover reads as no change at all, and the correction
    that recorded it is refused outright."""

    changed = draft_with_axis_proposals.model_copy(
        update={"clause_fact_reviews": (_review_of(_spd_fact()),)}
    )

    corrected = record_correction(
        draft_with_axis_proposals, changed, actor="tester", notes="author one clause fact"
    )

    assert corrected.clause_fact_reviews == changed.clause_fact_reviews


def test_the_audit_digest_covers_a_recorded_fact_review(draft_with_axis_proposals) -> None:
    """The gate re-derives this digest, so a collection missing from it is unaudited content."""

    changed = draft_with_axis_proposals.model_copy(
        update={"clause_fact_reviews": (_review_of(_spd_fact()),)}
    )

    assert draft_content_digest(changed) != draft_content_digest(draft_with_axis_proposals)


def test_the_audit_digest_covers_a_recorded_completion(draft_with_axis_proposals) -> None:
    completion = ClauseFactCompletion(
        rule_route="iec62477_2022.supply.spd_reduction_requirements.mains",
        fragment_id="raw-a",
        fragment_sha256="e" * 64,
        fact_set_sha256="f" * 64,
        actor="tester",
        recorded_at=datetime(2026, 8, 12, tzinfo=UTC),
        notes="complete for this route",
    )
    changed = draft_with_axis_proposals.model_copy(
        update={"clause_fact_completions": (completion,)}
    )

    assert draft_content_digest(changed) != draft_content_digest(draft_with_axis_proposals)


def test_confirmed_facts_reads_back_by_route() -> None:
    fact = _spd_fact()
    facts = ConfirmedFacts(
        by_route={"iec62477_2022.supply.spd_reduction_requirements.mains": (fact,)}
    )

    assert facts.for_route("iec62477_2022.supply.spd_reduction_requirements.mains") == (fact,)
    assert facts.for_route("iec62477_2022.supply.hf_transformer_attenuation") == ()
