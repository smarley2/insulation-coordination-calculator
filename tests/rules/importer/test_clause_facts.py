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
    OvercategoryStep,
    SpdMonitoringComplianceFact,
    SpdMonitoringExemptionFact,
    SpdMonitoringRequirementFact,
    SpdReductionFloorFact,
    SpdReductionMonitoringFact,
    SpdReductionPermissionFact,
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


def _spd_fact() -> SpdReductionPermissionFact:
    return SpdReductionPermissionFact(
        statement_index=0,
        node_references=(CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),),
        obligation="permission",
        supply_kind="mains",
        permitted_steps=(
            OvercategoryStep(source_ovc="ovc_iii", target_ovc="ovc_ii"),
            OvercategoryStep(source_ovc="ovc_iv", target_ovc="ovc_iii"),
        ),
        insulation_classes=DimensionScope.of("basic", "supplementary"),
    )


def _spd_monitoring_statement() -> SpdReductionMonitoringFact:
    return SpdReductionMonitoringFact(
        statement_index=1,
        node_references=(CitedNode(fragment_id="raw-a", node_order=1, node_sha256="b" * 64),),
        obligation="requirement",
        supply_kind="mains",
        device_degradable=True,
        monitoring_obligation="required",
        status_indication="required",
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


def _monitoring_node() -> tuple[CitedNode, ...]:
    return (CitedNode(fragment_id="raw-a", node_order=0, node_sha256="a" * 64),)


def test_monitoring_is_its_own_family_and_reduction_carries_no_placement() -> None:
    """Placement is monitoring semantics. Reduction refers to monitoring, never restates it.

    Reduction and monitoring are reviewed from separate clauses, and placement is a dimension
    only the monitoring clause's readings carry. A single family holding both would give every
    reduction statement a field its own clause never scopes.
    """

    monitoring = SpdMonitoringRequirementFact(
        statement_index=0,
        node_references=_monitoring_node(),
        obligation="requirement",
        device_placement=DimensionScope.of("bundled_external_to_pecs"),
        participates_in_reduction=True,
    )

    assert monitoring.fact_kind == "spd_monitoring"
    for model in (
        SpdReductionPermissionFact,
        SpdReductionFloorFact,
        SpdReductionMonitoringFact,
    ):
        assert "device_placement" not in model.model_fields
        assert "participates_in_reduction" not in model.model_fields
    assert _spd_monitoring_statement().monitoring_reference.endswith(".monitoring")


def test_the_monitoring_obligation_is_the_variant_rather_than_a_field() -> None:
    """A boolean beside the variant could contradict it, and one of the two would have to win."""

    for model in (SpdMonitoringRequirementFact, SpdMonitoringExemptionFact):
        assert "monitoring_required" not in model.model_fields
    assert {"requirement", "exemption"} <= {
        SpdMonitoringRequirementFact.model_fields["statement_kind"].default,
        SpdMonitoringExemptionFact.model_fields["statement_kind"].default,
    }


def test_an_exemption_states_no_placement_and_compliance_states_no_monitoring_state() -> None:
    """Neither variant may be forced to carry a dimension its own kind of statement never states.

    An exemption is stated over the monitoring obligations collectively, so a placement on it would
    be invented -- and an unrestricted placement token is that same invented dimension spelled as a
    scope. A compliance statement states which showings are accepted and nothing about whether
    monitoring is owed or where the device sits.
    """

    assert "device_placement" not in SpdMonitoringExemptionFact.model_fields
    assert "device_placement" not in SpdMonitoringComplianceFact.model_fields
    assert "participates_in_reduction" not in SpdMonitoringComplianceFact.model_fields
    assert "compliance_evidence" not in SpdMonitoringRequirementFact.model_fields


def test_one_compliance_statement_accepts_both_showings_as_one_reading() -> None:
    """Two accepted showings are one statement: splitting them would claim twice the review."""

    compliance = SpdMonitoringComplianceFact(
        statement_index=0,
        node_references=_monitoring_node(),
        obligation="requirement",
        compliance_evidence=DimensionScope.of("monitoring_test", "visual_inspection"),
    )

    assert compliance.compliance_evidence.mode == "exact_set"
    assert compliance.compliance_evidence.values == ("monitoring_test", "visual_inspection")


def test_a_requirement_and_an_exemption_are_never_one_reading() -> None:
    """The duplicate refusal compares the kind, so an obligation never covers its own exemption."""

    requirement = SpdMonitoringRequirementFact(
        statement_index=0,
        node_references=_monitoring_node(),
        obligation="requirement",
        device_placement=DimensionScope.of("internal_to_pecs"),
        participates_in_reduction=True,
    )
    exemption = SpdMonitoringExemptionFact(
        statement_index=1,
        node_references=_monitoring_node(),
        obligation="requirement",
        participates_in_reduction=True,
    )

    assert same_clause_fact_reading(requirement, exemption) is False


def test_a_fact_must_cite_at_least_one_node() -> None:
    """A statement with no evidence could not go stale, which defeats the whole mechanism."""

    with pytest.raises(ValidationError):
        SpdReductionPermissionFact.model_validate(
            {**_spd_fact().model_dump(), "node_references": ()}
        )


# --- the reduction family's three readings, and its collections --------------------------


def test_each_reduction_variant_carries_only_its_own_dimensions() -> None:
    """Merged into one shape, one statement had to name four readings at once.

    A permission states no degradability, no monitoring obligation and no monitoring reference; a
    floor states no transition; a monitoring statement states no transition and no insulation class.
    """

    permission = set(SpdReductionPermissionFact.model_fields)
    floor = set(SpdReductionFloorFact.model_fields)
    monitoring = set(SpdReductionMonitoringFact.model_fields)

    assert permission.isdisjoint(
        {"device_degradable", "monitoring_obligation", "status_indication", "monitoring_reference"}
    )
    assert floor.isdisjoint({"permitted_steps", "device_degradable", "monitoring_reference"})
    assert monitoring.isdisjoint({"permitted_steps", "insulation_classes"})
    # The reference lives on the statement that actually defers, so the runtime chain composes
    # from separately reviewed authorities rather than from a copy on the permission.
    assert "monitoring_reference" in monitoring
    # What all three state stays shared rather than repeated per variant.
    assert {"supply_kind", "obligation"} <= permission & floor & monitoring


def test_a_permission_carries_its_transitions_as_pairs_not_two_value_sets() -> None:
    """Two sets would fabricate a cartesian product of the endpoints the reviewer never stated."""

    steps = _spd_fact().permitted_steps

    assert [(step.source_ovc, step.target_ovc) for step in steps] == [
        ("ovc_iii", "ovc_ii"),
        ("ovc_iv", "ovc_iii"),
    ]
    assert "source_ovc" not in SpdReductionPermissionFact.model_fields
    assert "target_ovc" not in SpdReductionPermissionFact.model_fields


def test_a_step_that_does_not_move_is_refused() -> None:
    """A transition to its own category is how the merged shape used to spell the floor."""

    with pytest.raises(ValidationError, match="different category"):
        OvercategoryStep(source_ovc="ovc_iii", target_ovc="ovc_iii")


def test_a_step_collection_out_of_declared_order_is_refused() -> None:
    """Order-dependent digests are how a reordered copy defeats the duplicate refusal.

    Sorted by the declared scale order rather than lexicographically, because a step's endpoints
    mean positions on that scale.
    """

    with pytest.raises(ValidationError, match="declared vocabulary order"):
        SpdReductionPermissionFact.model_validate(
            {
                **_spd_fact().model_dump(),
                "permitted_steps": (
                    {"source_ovc": "ovc_iv", "target_ovc": "ovc_iii"},
                    {"source_ovc": "ovc_iii", "target_ovc": "ovc_ii"},
                ),
            }
        )


def test_a_step_collection_naming_one_transition_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="each transition once"):
        SpdReductionPermissionFact.model_validate(
            {
                **_spd_fact().model_dump(),
                "permitted_steps": (
                    {"source_ovc": "ovc_iii", "target_ovc": "ovc_ii"},
                    {"source_ovc": "ovc_iii", "target_ovc": "ovc_ii"},
                ),
            }
        )


def test_a_permission_naming_one_step_collection_in_two_orders_is_one_reading() -> None:
    """The point of the ordering rule: one reading hashes once, however it was typed.

    Both properties together are what keep ``same_clause_fact_reading`` able to see a second copy:
    without canonical order the reordered copy hashes differently and reads as a distinct reading,
    and without the duplicate refusal the same transition counts twice inside one statement.
    """

    ordered = [
        {"source_ovc": "ovc_iii", "target_ovc": "ovc_ii"},
        {"source_ovc": "ovc_iv", "target_ovc": "ovc_iii"},
    ]
    first = SpdReductionPermissionFact.model_validate(
        {**_spd_fact().model_dump(), "permitted_steps": ordered}
    )

    assert canonical_model_sha256(first) == canonical_model_sha256(_spd_fact())
    assert same_clause_fact_reading(first, _spd_fact()) is True


def test_a_class_set_is_canonical_and_names_each_class_once() -> None:
    """The permission's insulation classes are a scope, which owns both properties already."""

    assert DimensionScope[str].of("supplementary", "basic") == DimensionScope[str].of(
        "basic", "supplementary"
    )
    with pytest.raises(ValidationError, match="each value once"):
        DimensionScope[str](mode="exact_set", values=("basic", "basic"))


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


def _review_of(fact: SpdReductionPermissionFact) -> ClauseFactReview:
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
