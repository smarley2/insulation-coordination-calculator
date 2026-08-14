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
    DimensionScope,
    SpdMonitoringFact,
    SpdReductionFact,
    SystemVoltageApplicabilityFact,
    SystemVoltageMeasureFact,
    evidence_sha256,
    same_clause_fact_reading,
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


def _measure_fact() -> SystemVoltageMeasureFact:
    return SystemVoltageMeasureFact(
        statement_index=1,
        node_references=(CitedNode(fragment_id="raw-b", node_order=2, node_sha256="b" * 64),),
        obligation="requirement",
        supply_kind="mains",
        phase_system="three_phase_it",
        earthing="it",
        input_topology="any_input_topology",
        purpose="impulse",
        measure="phase_to_artificial_neutral_rms",
    )


def _applicability_fact() -> SystemVoltageApplicabilityFact:
    return SystemVoltageApplicabilityFact(
        statement_index=2,
        node_references=(CitedNode(fragment_id="raw-b", node_order=3, node_sha256="c" * 64),),
        obligation="requirement",
        supply_kind="mains",
        input_topology="isolated_secondary",
        purpose="impulse",
        counts_as_system_voltage=True,
    )


def test_each_family_is_its_own_type_under_one_discriminator() -> None:
    fact = _spd_fact()
    system = _measure_fact()

    assert fact.fact_kind == "spd_reduction"
    assert system.fact_kind == "system_voltage"


def test_a_familys_variants_share_its_kind_and_differ_on_the_statement_kind() -> None:
    """The route-to-family contract is unchanged: one clause, one family, two kinds of reading."""

    measure = _measure_fact()
    applicability = _applicability_fact()

    assert measure.fact_kind == applicability.fact_kind == "system_voltage"
    assert (measure.statement_kind, applicability.statement_kind) == ("measure", "applicability")


def test_a_variant_carries_only_the_dimensions_its_own_statements_state() -> None:
    """An applicability statement selects no measure and scopes no phase system.

    Carrying them would record dimensions the reviewer never read, and a projector filling its
    output from such a field is the same defect from the other side.
    """

    applicability = set(SystemVoltageApplicabilityFact.model_fields)

    assert applicability.isdisjoint({"measure", "phase_system", "earthing"})
    assert "counts_as_system_voltage" not in SystemVoltageMeasureFact.model_fields
    # What both kinds do state stays shared rather than repeated per variant.
    assert {"supply_kind", "input_topology", "purpose", "obligation"} <= applicability


def test_a_variant_union_round_trips_through_the_family_discriminator() -> None:
    """Both kinds must survive the archive shape a review is stored and read back in."""

    for fact in (_measure_fact(), _applicability_fact()):
        review = ClauseFactReview(
            rule_route="iec62477_2022.supply.system_voltage_resolution",
            statement_index=fact.statement_index,
            fact=fact,
            fact_sha256=canonical_model_sha256(fact),
            evidence_sha256=evidence_sha256(fact.node_references),
            actor="tester",
            recorded_at=datetime(2026, 8, 14, tzinfo=UTC),
            notes="authored",
        )

        assert ClauseFactReview.model_validate(review.model_dump(mode="json")) == review


def test_two_readings_of_different_kinds_are_never_one_reading() -> None:
    """The duplicate refusal compares kind as well as dimensions.

    Comparing a measure statement's field list against an applicability statement would ask it for
    dimensions it does not carry -- and two statements of different kinds citing one node are two
    readings of it, not one recorded twice.
    """

    node = (CitedNode(fragment_id="raw-b", node_order=2, node_sha256="b" * 64),)
    measure = _measure_fact().model_copy(update={"node_references": node})
    applicability = _applicability_fact().model_copy(update={"node_references": node})

    assert same_clause_fact_reading(measure, applicability) is False
    assert same_clause_fact_reading(measure, measure) is True


def test_monitoring_is_its_own_family_and_reduction_carries_no_placement() -> None:
    """Placement is monitoring semantics. Reduction refers to monitoring, never restates it.

    Reduction and monitoring are reviewed from separate clauses, and placement is a dimension
    only the monitoring clause's readings carry. A single family holding both would give every
    reduction statement a field its own clause never scopes.
    """

    monitoring = SpdMonitoringFact(
        statement_index=0,
        node_references=(CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),),
        obligation="requirement",
        device_placement="bundled_external_to_pecs",
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


# --- DimensionScope: the three readings, and the canonical form the digest needs ---------


def test_the_three_scope_modes_carry_the_value_counts_they_name() -> None:
    assert DimensionScope[str](mode="unrestricted").values == ()
    assert DimensionScope[str](mode="exact_one", values=("alpha",)).values == ("alpha",)
    assert DimensionScope[str](mode="exact_set", values=("alpha", "beta")).values == (
        "alpha",
        "beta",
    )


@pytest.mark.parametrize(
    ("mode", "values"),
    (
        # An unrestricted reading restricts nothing, so naming a value contradicts itself.
        ("unrestricted", ("alpha",)),
        ("exact_one", ()),
        ("exact_one", ("alpha", "beta")),
        # One value is exact_one; calling it a set would give two spellings of one reading.
        ("exact_set", ("alpha",)),
        ("exact_set", ()),
    ),
)
def test_a_scope_whose_values_contradict_its_mode_is_refused(mode: str, values: tuple) -> None:
    with pytest.raises(ValidationError):
        DimensionScope[str](mode=mode, values=values)


def test_a_scope_naming_one_value_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="each value once"):
        DimensionScope[str](mode="exact_set", values=("alpha", "alpha"))


def test_a_scope_out_of_canonical_order_is_refused() -> None:
    """Two statements naming one set must hash identically, or the duplicate refusal is defeated."""

    with pytest.raises(ValidationError, match="canonical order"):
        DimensionScope[str](mode="exact_set", values=("beta", "alpha"))


def test_the_constructor_canonicalises_whatever_order_it_is_given() -> None:
    """Order a source happens to state values in must not reach the digest."""

    first = DimensionScope[str].of("beta", "alpha")
    second = DimensionScope[str].of("alpha", "beta")

    assert first == second
    assert first.mode == "exact_set"
    assert DimensionScope[str].of("alpha").mode == "exact_one"
    assert DimensionScope[str].unrestricted().mode == "unrestricted"
