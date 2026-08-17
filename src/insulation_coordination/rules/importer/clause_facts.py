"""Reviewed normative statements: the licensed clause as the authority for its own branches.

A statement is authored by a maintainer from the private fragment, never proposed by public code,
and binds a digest of exactly the nodes it cites. No statement text, clause wording or numeric
source content belongs here: only the neutral vocabulary each field draws from.

That first sentence was false for as long as a keyword grammar mapping the source's phrasing to
these typed fields sat in the public recipe: it derived complete typed readings from licensed text,
which amendment A1's audit judged licensed-derived normative content. Such a grammar now loads only
from beside the licensed material, and the contract is *asserted* rather than restated --
``test_no_public_module_declares_a_clause_fact_grammar`` fails if any module under ``src`` builds
one again, so this docstring cannot quietly go false a second time.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal, get_args, get_origin

from pydantic import AfterValidator, Field, model_validator

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


def pair_vocabulary(annotation: object) -> tuple[str, ...] | None:
    """The vocabulary both members of one ordered-pair collection draw from, or ``None``.

    The collection counterpart of ``scope_vocabulary``, and the one reader for it, so the editor and
    the proposer do not each carry their own introspection. ``None`` for any other annotation,
    including a collection whose members do not all draw from one vocabulary: a pair whose halves
    were different scales would need two vocabularies to offer, and guessing which is which is worse
    than refusing in ``fact_dimensions``.

    A pair collection is not a scope and does not project like one. A scope is one condition over
    several values with one answer, so it is one row. A pair is a *mapping*: each member carries its
    own answer, so a statement enumerating several of them projects one row per pair -- which is why
    the collection needs the consumer input that separates them.
    """

    if get_origin(annotation) is not tuple:
        return None
    args = get_args(annotation)
    member = args[0] if args else None
    if not (isinstance(member, type) and issubclass(member, FrozenModel)):
        return None
    vocabularies = {
        tuple(value for value in get_args(field.annotation) if isinstance(value, str))
        for field in member.model_fields.values()
    }
    if len(vocabularies) != 1:
        return None
    return vocabularies.pop()


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


#: How a supply reaches the equipment. Its own alias because a reviewed scope's vocabulary is read
#: back out of the annotation -- see ``scope_vocabulary``.
InputTopology = Literal["direct", "rectified_dc", "series_rectifier_bridges", "isolated_secondary"]

#: What a resolved voltage is calculated for. Its own alias for the same reason.
CalculationPurpose = Literal["impulse", "temporary_overvoltage"]


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
    ``clause_fact_defect``, which is what refuses a statement contradicting its own route. It is
    the one dimension of this family that is **not** a scope, and deliberately: the route settles
    it, so there is no unrestricted reading of it to state and no set of values a statement could
    name. It carried an ``any_supply_kind`` token for exactly as long as the other dimensions
    carried theirs, and that token was authorable by nothing -- the dialog prefills this field from
    the route's declaration and disables it -- so it left with them rather than becoming a scope
    nothing would ever widen.

    Every other dimension here is a ``DimensionScope``, which is what a statement naming several
    values needs: as scalars with an ``any_*`` token, one sentence naming three earthing
    arrangements became three drafts and, once authored, three statements of one reading. Where a
    general reading and a narrower one cover the same values, the narrower one's own dimension is
    what separates them, and the projector refuses an overlapping pair rather than serving
    whichever row comes first.
    """

    fact_kind: Literal["system_voltage"] = "system_voltage"
    supply_kind: Literal["mains", "non_mains"]
    input_topology: DimensionScope[InputTopology]
    #: An unrestricted reading names a statement that does not restrict which calculation purpose
    #: it applies to -- one normative statement, not two, and not one per purpose.
    purpose: DimensionScope[CalculationPurpose]


#: The phase systems a reviewed measure statement may name. Its own alias because the scope's
#: vocabulary is read back out of the annotation, and because the reviewed domain is deliberately
#: narrower than the consumer input's: the rule also declares a bare single-phase system and an
#: unspecified one, so an unrestricted reading must not answer for them.
PhaseSystem = Literal["three_phase_star", "three_phase_delta", "three_phase_it", "single_phase_it"]

#: The earthing arrangements a reviewed measure statement may name. Its own alias for the same
#: reason; here the reviewed and consumer domains coincide, so an unrestricted reading is a wildcard.
EarthingArrangement = Literal["tn", "tt", "it", "unspecified"]


class SystemVoltageMeasureFact(SystemVoltageStatement):
    """One statement of which measure is the system voltage, on the dimensions it scopes.

    One field per dimension the projected rule declares as an input, each drawn from that
    input's own vocabulary. Four were once collapsed into ``phase_system``, whose token
    list mixed two phase systems with a supply kind and two input topologies: three of those
    four raised at projection because the rule's ``phase_system`` never declared them, and the
    ``supply_kind`` and ``input_topology`` inputs sat declared but unreachable behind matchers
    that accepted anything. A statement's dimensions are separate readings and need separate
    fields.

    ``measure`` stays one value while the dimensions above are scopes, because it is the *answer*
    rather than a condition: the projected rule carries one categorical output, and a statement
    naming two measures would not say which of them a consumer gets.
    """

    statement_kind: Literal["measure"] = "measure"
    phase_system: DimensionScope[PhaseSystem]
    earthing: DimensionScope[EarthingArrangement]
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


#: Which supply side a rating is resolved for. Its own alias because the scope's vocabulary is read
#: back out of the annotation -- see ``scope_vocabulary``.
SupplySide = Literal["mains", "non_mains"]

#: How a circuit downstream of a combined circuit is connected to it. Spelled as the rule's own
#: ``downstream_connection_kind`` vocabulary, because these mean the same thing -- the same
#: reasoning ``DevicePlacement`` records.
DownstreamConnection = Literal["no_isolation", "verified_galvanic_isolation"]


class BarrierTransferStatement(_Fact):
    """What every barrier transfer statement shares, whichever kind of reading it is.

    The family states three normatively different readings under one common condition -- how each
    side's rating is resolved, which rating the combined circuit takes, and what a circuit connected
    downstream inherits -- so it discriminates on ``statement_kind`` inside one ``fact_kind``.

    The **isolation state is not a field here**. It is the condition the whole clause fragment is
    scoped by, so it is route-declared structural scope, the way the supply kind already is: see
    ``SUPPLY_FACT_ISOLATION_BY_ROUTE`` and ``clause_fact_defect``. As a field it was a reviewed
    choice, which made a positive-isolation statement authorable from the fragment that states the
    unisolated case -- a contradiction nothing refused, and one the private placeholder authored.
    Now such a statement cannot be spelled at all, and the recipe's evidence-kind branch that only
    it could reach is gone with it.
    """

    fact_kind: Literal["barrier_transfer"] = "barrier_transfer"


class BarrierRatingResolutionFact(BarrierTransferStatement):
    """One statement of where each side's own impulse withstand rating is resolved.

    A carried-not-projected variant: it selects no rating and states no rule for the combined
    circuit, so none of this route's declared outputs can carry it. It is resolved and covered by
    the route's fact-set digest, which is how completion and the approval gate know the reviewer
    read it.

    ``rated_side`` is a scope because the statement names both sides in one reading rather than one
    statement per side. It carries no downstream connection kind: which side's rating is resolved
    and what a downstream circuit inherits are separate readings.
    """

    statement_kind: Literal["rating_resolution"] = "rating_resolution"
    rated_side: DimensionScope[SupplySide]
    #: The route family each side's own rating is resolved by, never restated here -- the same
    #: deferral shape ``SpdReductionFact.monitoring_reference`` carries. The side and this
    #: reference together name the route; the reference alone would have to be authored once per
    #: side, which would split one reading in two.
    rating_reference: Identifier


class BarrierCombinedRequirementFact(BarrierTransferStatement):
    """One statement of which requirement governs the whole combined circuit.

    The projected variant. It carries **no** downstream connection kind: the requirement is stated
    over the combined circuit itself, and scoping it to a connection would be a dimension the
    reading does not make.

    ``combined_circuit_rule`` is a reviewed semantic, not an executable comparison: naming the more
    severe of two sides is what the source states, and resolving which of two ratings that is
    belongs to the comparison contracts of #53C.
    """

    statement_kind: Literal["combined_requirement"] = "combined_requirement"
    combined_circuit_rule: Literal["more_severe_of_both_sides", "side_specific_from_transfer"]


class BarrierDownstreamInheritanceFact(BarrierTransferStatement):
    """One statement of what a circuit connected to the combined circuit inherits.

    A carried-not-projected variant, and the reading that justifies this route's structural
    derivation of ``propagates_to_connected_circuits``: it states that the combined circuit's rating
    reaches a circuit connected to it, for the connection kind it names. It **restates no
    more-severe selection** -- which rating the combined circuit carries is the combined
    requirement statement's reading, and repeating it here would record one reading twice.

    ``downstream_connection_kind`` is the dimension it does state, and it is checked against the
    route's declared isolation scope: a statement naming an isolated connection on the route that
    states the unisolated case is refused rather than merely undocumented.
    """

    statement_kind: Literal["downstream_inheritance"] = "downstream_inheritance"
    downstream_connection_kind: DownstreamConnection
    inherits_combined_circuit_rating: bool


#: The family's three variants under one ``fact_kind``, discriminated by ``statement_kind``.
BarrierTransferFact = Annotated[
    BarrierRatingResolutionFact | BarrierCombinedRequirementFact | BarrierDownstreamInheritanceFact,
    Field(discriminator="statement_kind"),
]


#: Overvoltage category designations, in the order the scale declares them, increasing in severity.
#: Designations only; no source value. Its own alias because a step collection's canonical order is
#: read from it and because a reviewed scope's vocabulary is read out of the annotation.
OvercategoryDesignation = Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]

#: Insulation classes, in declared order.
InsulationClass = Literal["functional", "basic", "supplementary", "double", "reinforced"]

_OVERCATEGORY_ORDER: tuple[str, ...] = get_args(OvercategoryDesignation)


class OvercategoryStep(FrozenModel):
    """One permitted category transition: the category reduced from, and the one reduced to.

    A pair rather than two independent value sets. Two sets would fabricate a cartesian product the
    reviewer never stated -- a statement permitting one transition and another would read as
    permitting every crossing of their endpoints -- and each pair carries its own answer, so the
    pairing is the reading rather than a presentation of it.
    """

    source_ovc: OvercategoryDesignation
    target_ovc: OvercategoryDesignation

    @model_validator(mode="after")
    def _a_step_moves(self) -> OvercategoryStep:
        if self.source_ovc == self.target_ovc:
            raise ValueError("a permitted step reduces to a different category")
        return self


def _canonical_steps(steps: tuple[OvercategoryStep, ...]) -> tuple[OvercategoryStep, ...]:
    """Refuse a step collection that is out of declared order or names one transition twice.

    Without this the fact digest is order-dependent, so one reading authored in two orders hashes
    twice and ``same_clause_fact_reading`` lets the reordered copy through as a distinct reading --
    which defeats the duplicate-reading refusal exactly. Sorted by the *declared* scale order rather
    than lexicographically, because a step's endpoints mean positions on that scale.

    Rejecting rather than silently sorting, unlike ``DimensionScope.of``: a collection arrives from
    an authored wire value whose order the reviewer typed, and quietly reordering it would hide a
    duplicate they meant to notice. ``DimensionScope.of`` canonicalises because it is a constructor
    the projector and the proposer call; this is a field validator on what a reviewer wrote.
    """

    keys = [
        (_OVERCATEGORY_ORDER.index(step.source_ovc), _OVERCATEGORY_ORDER.index(step.target_ovc))
        for step in steps
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("a reviewed step collection names each transition once")
    if keys != sorted(keys):
        raise ValueError("a reviewed step collection must be in declared vocabulary order")
    return steps


#: One statement's permitted transitions: at least one, each named once, in declared scale order.
OvercategoryStepSequence = Annotated[
    tuple[OvercategoryStep, ...],
    Field(min_length=1),
    AfterValidator(_canonical_steps),
]


class SpdReductionStatement(_Fact):
    """What every SPD reduction statement shares, whichever kind of reading it is.

    The family states three normatively different readings from one clause -- which transitions are
    permitted and for which insulation, the floor the permission may not cross, and the monitoring a
    degradable reducing device owes -- so it discriminates on ``statement_kind`` inside one
    ``fact_kind``. Merged into one shape, as it was, a single statement had to name a transition, an
    insulation class, a degradability and a monitoring obligation at once: four readings recorded as
    one, and the projector then had to fill six outputs from it.

    ``supply_kind`` sits here rather than on a variant because the route determines it structurally
    for every statement it carries -- see ``SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE`` and
    ``clause_fact_defect``.

    No variant carries a device placement. Reduction and monitoring are reviewed from separate
    clauses, and placement is read only from the monitoring clause -- see ``DevicePlacement``.
    """

    fact_kind: Literal["spd_reduction"] = "spd_reduction"
    supply_kind: Literal["mains", "non_mains"]


class SpdReductionPermissionFact(SpdReductionStatement):
    """One statement of the transitions a supply kind permits, and the insulation they apply to.

    The transitions are **one ordered collection of pairs**, so a statement naming several is one
    statement; the insulation classes are **one scope**, because the statement names them jointly and
    a class it does not name reaches no row.

    It states no degradability, no monitoring obligation and no monitoring reference. The monitoring
    a degradable reducing device owes is a separate normative statement of the same clause, and the
    reference to the route it defers to belongs on that statement -- so the runtime chain composes
    from separately reviewed authorities rather than from one merged fact.
    """

    statement_kind: Literal["permission"] = "permission"
    permitted_steps: OvercategoryStepSequence
    insulation_classes: DimensionScope[InsulationClass]


class SpdReductionFloorFact(SpdReductionStatement):
    """One statement of the floor a reduced requirement may not fall below.

    A carried-not-projected variant, and reviewed representation only: it states a *comparison*
    against a basis, and both the executable comparison and a route that evaluates it are #53C's.
    It is resolved and covered by the route's fact-set digest, so completion and the approval gate
    know the reviewer read it, and it reaches no row.

    Not a transition permission: it names the insulation classes it protects and no source or target
    category at all. Forcing it into the permission's shape is what made the merged fact record a
    floor as a transition to its own category.
    """

    statement_kind: Literal["floor"] = "floor"
    insulation_classes: DimensionScope[InsulationClass]
    #: The requirement the floor is measured against: the basic-insulation impulse withstand
    #: resolved as if the reducing means were not present. A typed token rather than prose, and its
    #: own vocabulary so a second basis can join it without reshaping the statement.
    unreduced_basis: Literal["basic_insulation_without_the_reducing_means"]
    #: How the reduced requirement must stand to that basis. Reviewed, never evaluated here.
    relation: Literal["must_not_fall_below"]


class SpdReductionMonitoringFact(SpdReductionStatement):
    """One statement of the monitoring a degradable reducing device owes.

    It states the condition -- a device whose ability to reduce impulses can degrade -- the
    obligation, the status indication that accompanies it, and the route the obligation is specified
    by. It states no category transition and no insulation class, because a statement of this kind
    states neither.

    ``monitoring_reference`` lives here rather than on the permission: the source states this as its
    own normative statement, so a consumer resolves the obligation by following the reference to a
    separately reviewed authority instead of reading a flattened copy off the permission.
    """

    statement_kind: Literal["monitoring"] = "monitoring"
    device_degradable: bool
    monitoring_obligation: Literal["required", "not_required"]
    status_indication: Literal["required", "not_required"]
    monitoring_reference: Identifier


#: The family's three variants under one ``fact_kind``, discriminated by ``statement_kind``.
SpdReductionFact = Annotated[
    SpdReductionPermissionFact | SpdReductionFloorFact | SpdReductionMonitoringFact,
    Field(discriminator="statement_kind"),
]


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

#: The evidence routes a statement may accept. Its own alias because the scope's vocabulary is read
#: back out of the annotation -- see ``scope_vocabulary`` -- and because the reviewed domain is
#: deliberately narrower than the consumer input's: that input also declares the *absence* of
#: evidence, which is the one state a permission may never be granted for, so an unrestricted
#: reading here projects an ``in`` over these three rather than a wildcard.
AttenuationEvidence = Literal["test", "simulation", "calculation"]


class HfAttenuationFact(_Fact):
    fact_kind: Literal["hf_attenuation"] = "hf_attenuation"
    #: A scope rather than one designation, because a statement naming both gates is one
    #: statement. Authored as a scalar it had to be authored twice, which projected two rows and
    #: showed as two drafts for one sentence -- a reading duplicated to fit the field's shape.
    dvc_gate: DimensionScope[DvcGate]
    #: A scope for the same reason, and the narrower-reviewed-domain case the general projection
    #: rule already handles: an unrestricted reading accepts every route the statement can name and
    #: never the absence of one, which is exactly what ``_evidence_matcher`` was written by hand to
    #: do while this field was a scalar carrying an ``any_evidence`` token.
    evidence_kind: DimensionScope[AttenuationEvidence]
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
    "AttenuationEvidence",
    "BarrierCombinedRequirementFact",
    "BarrierDownstreamInheritanceFact",
    "BarrierRatingResolutionFact",
    "BarrierTransferFact",
    "BarrierTransferStatement",
    "CalculationPurpose",
    "CitedNode",
    "ClauseFactCompletion",
    "ClauseFactReview",
    "ConfirmedFacts",
    "DevicePlacement",
    "DimensionScope",
    "DownstreamConnection",
    "DvcGate",
    "EarthingArrangement",
    "HfAttenuationFact",
    "InputTopology",
    "InsulationClass",
    "MonitoringComplianceEvidence",
    "Obligation",
    "OvercategoryDesignation",
    "OvercategoryStep",
    "OvercategoryStepSequence",
    "PhaseSystem",
    "PropagationStepFact",
    "ScopeMode",
    "SpdMonitoringComplianceFact",
    "SpdMonitoringExemptionFact",
    "SpdMonitoringFact",
    "SpdMonitoringRequirementFact",
    "SpdMonitoringStatement",
    "SpdReductionFact",
    "SpdReductionFloorFact",
    "SpdReductionMonitoringFact",
    "SpdReductionPermissionFact",
    "SpdReductionStatement",
    "SupplyFact",
    "SupplySide",
    "SystemVoltageApplicabilityFact",
    "SystemVoltageFact",
    "SystemVoltageMeasureFact",
    "SystemVoltageStatement",
    "evidence_sha256",
    "pair_vocabulary",
    "same_clause_fact_reading",
    "scope_vocabulary",
]
