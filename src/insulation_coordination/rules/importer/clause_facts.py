"""Reviewed normative statements: the licensed clause as the authority for its own branches.

A statement is authored by a maintainer from the private fragment, never proposed by public code,
and binds a digest of exactly the nodes it cites. No statement text, clause wording or numeric
source content belongs here: only the neutral vocabulary each field draws from.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, NotesText

Obligation = Literal["requirement", "permission"]

ScopeMode = Literal["unrestricted", "exact_one", "exact_set"]


class DimensionScope[T: str](FrozenModel):
    """How far one reviewed statement restricts one categorical dimension.

    Three readings a source can make of a dimension, and the three it cannot be forced into a
    single value without inventing content. ``exact_set`` is the one the old scalar-plus-wildcard
    shape could not express at all: a statement naming several values is one statement, not one per
    value, and not a statement restricting nothing.

    Projection is the caller's, because it needs the consumer input's own domain -- see
    ``_scope_matcher``. What this model owns is that the values are canonical: sorted and unique, so
    two statements naming one set hash identically. Without that the fact digest is
    order-dependent and ``same_clause_fact_reading`` would let a reordered copy through as a
    distinct reading.

    ponytail: sorted lexicographically rather than by each vocabulary's declared order. Canonical
    is all the digest needs, and a per-vocabulary order would mean handing every scope its
    vocabulary. If a display ever wants source order, sort at the display.
    """

    mode: ScopeMode
    values: tuple[T, ...] = ()

    @model_validator(mode="after")
    def _values_match_mode(self) -> DimensionScope[T]:
        if len(set(self.values)) != len(self.values):
            raise ValueError("a dimension scope names each value once")
        if tuple(sorted(self.values)) != self.values:
            raise ValueError("a dimension scope's values must be in canonical order")
        expected = {"unrestricted": 0, "exact_one": 1}.get(self.mode)
        if expected is not None and len(self.values) != expected:
            raise ValueError(f"{self.mode} names exactly {expected} value(s)")
        if self.mode == "exact_set" and len(self.values) < 2:
            raise ValueError("exact_set names two or more values; one value is exact_one")
        return self

    @classmethod
    def unrestricted(cls) -> DimensionScope[T]:
        return cls(mode="unrestricted")

    @classmethod
    def of(cls, *values: T) -> DimensionScope[T]:
        """One scope from the values a statement names, whatever order it names them in."""

        ordered = tuple(sorted(set(values)))
        return cls(mode="exact_one" if len(ordered) == 1 else "exact_set", values=ordered)


def scope_vocabulary(annotation: object) -> tuple[str, ...] | None:
    """The values one ``DimensionScope`` annotation scopes, or ``None`` for any other annotation.

    ``DimensionScope[X]`` is a concrete model *class* pydantic builds, not a typing alias, so
    ``get_origin``/``get_args`` return nothing for it and the type argument is read from pydantic's
    own generic metadata. One reader for every caller that has to know a field is a scope and what
    it may name -- the editor's vocabulary, the proposer's union, and the projected reviewed
    domain -- so none of them carries its own copy of that introspection.
    """

    if not (isinstance(annotation, type) and issubclass(annotation, DimensionScope)):
        return None
    parameters = annotation.__pydantic_generic_metadata__["args"]
    if not parameters:
        return ()
    return tuple(value for value in get_args(parameters[0]) if isinstance(value, str))


class CitedNode(FrozenModel):
    """One fragment node a statement rests on, by identity and content."""

    fragment_id: Identifier
    node_order: int = Field(ge=0)
    node_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class _Fact(FrozenModel):
    statement_index: int = Field(ge=0)
    node_references: tuple[CitedNode, ...] = Field(min_length=1)
    #: Known gap, disclosed rather than dropped: no projector reads this yet. A statement's
    #: obligation is part of what the maintainer read -- a permission and a requirement are not
    #: interchangeable, and one clause states both -- but nothing in the projected rules
    #: distinguishes them today. #53C item 4 is the first slice that acts on the distinction, when
    #: the attenuation requirement becomes an executable verification result rather than sharing
    #: one row with the permission it accompanies.
    obligation: Obligation


class SystemVoltageStatement(_Fact):
    """What every system-voltage statement states, whichever kind of reading it is.

    The family answers two normatively different questions from one clause -- which measure *is*
    the system voltage, and which voltages *count as* system voltages at all -- so it discriminates
    on ``statement_kind`` inside one ``fact_kind`` rather than forcing both onto one shape. This
    base carries only what both kinds state; each variant adds its own dimensions and nothing more.
    A variant that carried a dimension its own kind of statement does not state would be a reading
    the reviewer never made, and a projector manufacturing one to fill its output is the same
    defect from the other side.

    ``supply_kind`` sits here rather than on a variant because the route determines it structurally
    for every statement it carries -- see ``SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE`` and
    ``clause_fact_defect``, which is what refuses a statement contradicting its own route.

    ``any_*`` on a dimension records a reading that dimension does not restrict -- authored once
    rather than once per value. Where a general reading and a narrower one cover the same values,
    the narrower one's own dimension is what separates them, and the projector refuses an
    overlapping pair rather than serving whichever row comes first.

    Known gap, disclosed rather than dropped: these tokens are the scalar-plus-``any_*`` shape
    ``DimensionScope`` replaces, and converting them is what deletes ``_dimension_matcher``. Their
    projection is already correct -- the shim maps each to a scope -- so the conversion is a
    modelling tidy-up rather than a behaviour fix, and it is not this commit's variant work.
    """

    fact_kind: Literal["system_voltage"] = "system_voltage"
    supply_kind: Literal["mains", "non_mains", "any_supply_kind"]
    input_topology: Literal[
        "direct",
        "rectified_dc",
        "series_rectifier_bridges",
        "isolated_secondary",
        "any_input_topology",
    ]
    #: ``any_purpose`` names a statement that does not restrict which calculation purpose it
    #: applies to -- one normative statement, not two, so it needs its own token rather than being
    #: authored as a separate fact per purpose.
    purpose: Literal["impulse", "temporary_overvoltage", "any_purpose"]


class SystemVoltageMeasureFact(SystemVoltageStatement):
    """One statement of which measure is the system voltage, on the dimensions it scopes.

    One field per dimension the projected rule declares as an input, each drawn from that
    input's own vocabulary. Four were once collapsed into ``phase_system``, whose token
    list mixed two phase systems with a supply kind and two input topologies: three of those
    four raised at projection because the rule's ``phase_system`` never declared them, and the
    ``supply_kind`` and ``input_topology`` inputs sat declared but unreachable behind matchers
    that accepted anything. A statement's dimensions are separate readings and need separate
    fields.
    """

    statement_kind: Literal["measure"] = "measure"
    phase_system: Literal[
        "three_phase_star",
        "three_phase_delta",
        "three_phase_it",
        "single_phase_it",
        "any_phase_system",
    ]
    earthing: Literal["tn", "tt", "it", "unspecified", "any_earthing"]
    measure: Literal[
        "phase_to_earth_rms",
        "phase_to_artificial_neutral_rms",
        "phase_to_phase_rms",
        "between_supply_conductors_rms",
        "pre_rectifier_ac_rms",
        "highest_pre_rectifier_ac_rms_at_bridge",
    ]


class SystemVoltageApplicabilityFact(SystemVoltageStatement):
    """One statement of whether a topology's voltages count as system voltages, and for what.

    The carried-not-projected variant. Such a statement selects no measure: it establishes what
    the measure statements are *about*, for one input topology and one calculation purpose. It is
    accepted by resolution and covered by the fact-set digest, so completion and the approval gate
    know the reviewer read it -- and it contributes no row and no output, because the projected
    rule declares nothing that could carry it.

    Reviewed and disclosed rather than forced: authoring it as a ``measure`` statement would answer
    "which measure applies" with a reading that names none, and giving this route an applicability
    output is a contract change (#53C item L3). Until then the reading is recorded where it was
    read, and the gap is visible in the model instead of hidden in a measure token.

    It carries no ``phase_system``, ``earthing`` or ``measure``, because a statement of this kind
    states none of them.
    """

    statement_kind: Literal["applicability"] = "applicability"
    counts_as_system_voltage: bool


#: The family's two variants under one ``fact_kind``, discriminated by ``statement_kind``. The
#: route-to-family declaration, the family discriminator and the archive schema are unchanged: a
#: consumer still asks one question of one route, and a route still states one family.
SystemVoltageFact = Annotated[
    SystemVoltageMeasureFact | SystemVoltageApplicabilityFact,
    Field(discriminator="statement_kind"),
]


class PropagationStepFact(_Fact):
    fact_kind: Literal["propagation_step"] = "propagation_step"
    step: Literal["a", "b", "c", "d"]
    evaluated_side: Literal["mains", "non_mains"]
    operation: Literal["reduce_one_level", "resolve_rating", "take_more_severe_rating"]
    rating_source_side: Literal["mains", "non_mains"]


class BarrierTransferFact(_Fact):
    """One transfer statement, scoped to the barrier it is about and the connection downstream.

    ``downstream_connection_kind`` is a dimension the reviewed reading scopes, so a statement
    carrying none would answer for a connection outside its own scope.
    """

    fact_kind: Literal["barrier_transfer"] = "barrier_transfer"
    isolation_present: bool
    #: Spelled as the rule's own ``downstream_connection_kind`` vocabulary, because these mean
    #: the same thing -- the same reasoning ``SpdMonitoringFact.device_placement`` records.
    downstream_connection_kind: Literal["no_isolation", "verified_galvanic_isolation"]
    combined_circuit_rule: Literal["more_severe_of_both_sides", "side_specific_from_transfer"]


class SpdReductionFact(_Fact):
    """One reduction statement: which category step this supply kind permits, and its floor.

    Carries no device placement. Reduction and monitoring are reviewed from separate clauses, and
    a reduction statement refers to the monitoring route rather than restating it -- which is what
    ``monitoring_reference`` names. Placement belongs to ``SpdMonitoringFact``, whose own clause
    is where that dimension is read.
    """

    fact_kind: Literal["spd_reduction"] = "spd_reduction"
    supply_kind: Literal["mains", "non_mains"]
    source_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    target_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    insulation_class: Literal["functional", "basic", "supplementary", "double", "reinforced"]
    degradable: bool
    monitoring_obligation: Literal["required", "not_required"]
    #: The route whose statements the monitoring obligation defers to, never restated here.
    #:
    #: Known gap, disclosed rather than dropped: no projector reads this yet. Following the
    #: reference is what would let a consumer resolve the deferred obligation instead of reading
    #: the flattened ``monitoring_required`` this route emits, and that is part of the full
    #: reduction context #53C item 5 builds -- the same slice that right-sizes these three routes'
    #: shared output tuple.
    monitoring_reference: Identifier


#: The device placements a monitoring statement may name. Its own alias because the scope's
#: vocabulary is read back out of this annotation -- see ``scope_vocabulary`` -- and because the
#: reviewed domain is deliberately narrower than the consumer input's: the rule also declares a bare
#: external placement, which is wider than any reviewed reading of this clause, so an unrestricted
#: reading must not answer for it.
#:
#: Spelled as the rule's own ``device_placement`` vocabulary, because these mean the same thing. A
#: fact field may diverge from a consumer input where the two really are different concepts --
#: Table 2's basis against the curve basis in #53A is the precedent -- but only with an explicit
#: mapping. Two spellings of one concept and no mapping is just a field nothing can consume.
DevicePlacement = Literal["internal_to_pecs", "bundled_external_to_pecs"]

#: How compliance with a monitoring obligation is shown. Its own alias for the same reason: the
#: scope's vocabulary is read back out of the annotation. It carries no "not required" member,
#: because that is a monitoring state rather than a way of showing compliance -- a compliance
#: statement states which showings are accepted and nothing about whether monitoring is owed.
MonitoringComplianceEvidence = Literal["visual_inspection", "monitoring_test"]


class SpdMonitoringStatement(_Fact):
    """What every SPD monitoring statement shares, whichever kind of reading it is.

    Monitoring is its own normative concern rather than a dimension of reduction: every dimension
    below is read from the monitoring clause, and none of them appears in the reduction clauses at
    all.

    The family answers three normatively different questions from one clause -- when monitoring is
    owed, when it is not, and how compliance with it is shown -- so it discriminates on
    ``statement_kind`` inside one ``fact_kind``. This base carries only what all three kinds state,
    which is the family itself: each variant adds its own dimensions and nothing more. In
    particular the obligation is no longer a field. Whether monitoring is required is *what the
    variant is*, so a boolean beside the variant would let a requirement record that monitoring is
    not required -- two spellings of one reading, one of which contradicts itself.
    """

    fact_kind: Literal["spd_monitoring"] = "spd_monitoring"


class SpdMonitoringRequirementFact(SpdMonitoringStatement):
    """One statement of a placement whose device is owed monitoring.

    A scope rather than one placement, because a statement naming several placements is one
    statement: authored as a scalar it had to be authored once per placement, or once with an
    ``any_placement`` token that then had to be translated back into a scope at projection.

    ``participates_in_reduction`` is stated as well, and it is what separates a requirement from an
    exemption: the exemption is exactly the circuit that is not part of a category reduction, so a
    requirement recording no participation would overlap every exemption over the same placement
    and the projector would refuse the pair -- see ``_require_distinct_branches``.
    """

    statement_kind: Literal["requirement"] = "requirement"
    device_placement: DimensionScope[DevicePlacement]
    participates_in_reduction: bool


class SpdMonitoringExemptionFact(SpdMonitoringStatement):
    """One statement of a circuit that is owed no monitoring.

    It carries **no placement**. An exemption of this kind is stated over the monitoring
    obligations collectively rather than over a placement, so authoring one would need a placement
    the statement does not name -- and an unrestricted placement token would be that same invented
    dimension spelled as a scope. The projector reads the absence as unrestricted *within the
    reviewed placements*, which is the reading, and never widens to a placement no reviewed
    statement can name.
    """

    statement_kind: Literal["exemption"] = "exemption"
    participates_in_reduction: bool


class SpdMonitoringComplianceFact(SpdMonitoringStatement):
    """One statement of how compliance with the monitoring obligation is shown.

    The carried-not-projected variant. This route's declared ``verification_reference`` output
    carries none of this field's tokens, and widening it is a contract change (#53C item 5), so the
    statement is accepted by resolution and covered by the route's fact-set digest -- which is how
    completion and the approval gate know the reviewer read it -- and contributes no row.

    One scope rather than one fact per accepted showing: a statement accepting either of two
    showings is one statement, and splitting it would record one reading twice and claim twice the
    review. It carries no placement and no monitoring state, because a statement of this kind
    states neither.
    """

    statement_kind: Literal["compliance"] = "compliance"
    compliance_evidence: DimensionScope[MonitoringComplianceEvidence]


#: The family's three variants under one ``fact_kind``, discriminated by ``statement_kind``. The
#: route-to-family declaration, the family discriminator and the archive schema are unchanged.
SpdMonitoringFact = Annotated[
    SpdMonitoringRequirementFact | SpdMonitoringExemptionFact | SpdMonitoringComplianceFact,
    Field(discriminator="statement_kind"),
]


#: The DVC designations a gate reading may name. Its own alias because the scope's vocabulary is
#: read back out of this annotation -- see ``scope_vocabulary`` -- and because the reviewed domain
#: is deliberately narrower than the consumer input's: the third declared designation is one no
#: reviewed reading of this clause can name, so an unrestricted gate reading must not answer for it.
DvcGate = Literal["dvc_as", "dvc_b"]


class HfAttenuationFact(_Fact):
    fact_kind: Literal["hf_attenuation"] = "hf_attenuation"
    #: A scope rather than one designation, because a statement naming both gates is one
    #: statement. Authored as a scalar it had to be authored twice, which projected two rows and
    #: showed as two drafts for one sentence -- a reading duplicated to fit the field's shape.
    dvc_gate: DimensionScope[DvcGate]
    #: ``any_evidence`` records a reading not restricted to one evidence route, authored once
    #: rather than once per route -- the same shape ``any_purpose`` carries for a calculation
    #: purpose. Without it, authoring such a reading forces a single route and the others reach
    #: no row at all.
    evidence_kind: Literal["test", "simulation", "calculation", "any_evidence"]
    #: Known gap, disclosed rather than dropped: neither field is read by any projector yet. The
    #: executable contract this route needs is a verification *result* -- a comparison against the
    #: requirement the referenced route resolves -- rather than the evidence kind the rule can
    #: express today. #53C item 4 turns both into it; until then the fact carries a reading the
    #: rule cannot yet consume, the way ``SpdMonitoringFact.compliance_evidence`` does.
    threshold_reference: Identifier
    #: Carried rather than dropped even where every authored reading gives it the same value: it is
    #: part of the reading, and a field is not redundant for being constant across a fact set.
    #: #53C item 4 is where its second value becomes reachable.
    comparison_required: bool


SupplyFact = Annotated[
    SystemVoltageFact
    | PropagationStepFact
    | BarrierTransferFact
    | SpdReductionFact
    | SpdMonitoringFact
    | HfAttenuationFact,
    Field(discriminator="fact_kind"),
]


#: Fields that identify *which* statement this is rather than *what* it reads. Two statements
#: differing only in these record the same reading twice.
_STATEMENT_IDENTITY_FIELDS = frozenset({"statement_index", "node_references"})


def same_clause_fact_reading(first: SupplyFact, second: SupplyFact) -> bool:
    """Whether two statements record one reading: same dimensions and the same cited nodes.

    Compared by model type, which is the family *and*, where the family declares variants, the kind
    of statement: two readings of different kinds are never one reading, and asking a measure
    statement's field list of an applicability statement would ask it for dimensions it does not
    carry.

    ``statement_index`` is excluded because it names the slot, not the reading -- comparing it
    would make every statement unique and catch nothing. Citations are compared by node
    *identity* rather than by recorded digest: two statements citing one node record one
    evidentiary claim whether or not one of them has gone stale.

    Citations are compared *as well as* the dimensions, not instead of them. Two statements may
    legitimately agree on every dimension while resting on different nodes -- that is two
    readings of two parts of a clause that happen to say the same thing, and the projector's
    ``_require_distinct_branches`` is what judges whether their branches collide. Only a
    statement that agrees on both is a second copy of the first.
    """

    if type(first) is not type(second):
        return False
    if any(
        getattr(first, name) != getattr(second, name)
        for name in type(first).model_fields
        if name not in _STATEMENT_IDENTITY_FIELDS
    ):
        return False
    return _cited_nodes(first) == _cited_nodes(second)


def _cited_nodes(fact: SupplyFact) -> frozenset[tuple[str, int]]:
    return frozenset((node.fragment_id, node.node_order) for node in fact.node_references)


def evidence_sha256(nodes: tuple[CitedNode, ...]) -> str:
    """Digest of every cited node's identity and content, independent of citation order.

    Changing a cited node, or moving it, changes this digest and re-opens exactly the facts that
    cited it. A change to an uncited sibling node does not appear here at all.
    """

    members = sorted(f"{node.fragment_id}|{node.node_order}|{node.node_sha256}" for node in nodes)
    return hashlib.sha256("\n".join(members).encode("utf-8")).hexdigest()


class ClauseFactReview(FrozenModel):
    """Exact draft-only review of one authored statement."""

    rule_route: Identifier
    statement_index: int = Field(ge=0)
    fact: SupplyFact
    fact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    evidence_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ClauseFactCompletion(FrozenModel):
    """The reviewer's assertion that one route's fact set is complete.

    Scoped to a route, never to a fragment: a fragment may carry statements belonging to rules
    outside this route, and this record must not claim those were reviewed.
    """

    rule_route: Identifier
    fragment_id: Identifier
    fragment_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    fact_set_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ConfirmedFacts(FrozenModel):
    """Resolved reviewed facts handed to a clause projector."""

    by_route: dict[str, tuple[SupplyFact, ...]] = Field(default_factory=dict)

    def for_route(self, rule_route: str) -> tuple[SupplyFact, ...]:
        return self.by_route.get(rule_route, ())


__all__ = [
    "BarrierTransferFact",
    "CitedNode",
    "ClauseFactCompletion",
    "ClauseFactReview",
    "ConfirmedFacts",
    "DevicePlacement",
    "DimensionScope",
    "DvcGate",
    "HfAttenuationFact",
    "MonitoringComplianceEvidence",
    "Obligation",
    "PropagationStepFact",
    "ScopeMode",
    "SpdMonitoringComplianceFact",
    "SpdMonitoringExemptionFact",
    "SpdMonitoringFact",
    "SpdMonitoringRequirementFact",
    "SpdMonitoringStatement",
    "SpdReductionFact",
    "SupplyFact",
    "SystemVoltageApplicabilityFact",
    "SystemVoltageFact",
    "SystemVoltageMeasureFact",
    "SystemVoltageStatement",
    "evidence_sha256",
    "same_clause_fact_reading",
    "scope_vocabulary",
]
