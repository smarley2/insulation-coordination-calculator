"""IEC 62477-1:2022 supply-side clause recipes and their decision projections.

The recipe declares page/bbox/shape locators only. Every branch, input, and output
vocabulary below is an author-written neutral identifier: no source value, heading,
note, or clause prose lives in this file. A reviewed fragment whose node shape falls
outside the declared contract blocks with ``AMBIGUOUS_CLAUSE_STRUCTURE`` rather than
letting a projection guess a branch.

Each ``ClauseAuditSpec`` carries the ordered physical regions of one semantic clause, so a
projection is grounded in the whole clause rather than in whichever rectangle reached part
of it. A ported route's branch content comes from its reviewed clause facts (system voltage
resolution, verified barrier transfer, the SPD reduction and monitoring routes, HF
transformer attenuation): the fragment anchors the clause structurally and a
maintainer-authored fact states the branch. A route not yet ported still declares its branch
inventory here, the same way the DVC fault-applicability projection derives its selectors
from the maintained curve recipes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    GuidanceRule,
    Matcher,
    RuleKind,
    SourceReference,
)
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    ConfirmedFacts,
    HfAttenuationFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SupplyFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    SemanticProposal,
    aggregate_artifact_sha256,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseSegmentSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)

#: The non-mains system voltage subclause. Its statement belongs to the same rule the mains
#: subclause states, so it is declared as that rule's evidence rather than as a second route:
#: physical pagination and clause numbering are provenance, not application semantics, and a
#: consumer still asks one ``supply.system_voltage_resolution`` question.
SUPPLY_SYSTEM_VOLTAGE_NON_MAINS = f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.non_mains_evidence"

#: Measured with pdfplumber against the licensed document; the x range excludes the
#: licence watermark columns at either margin.
SUPPLY_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        clause="4.4.7.1.7.1",
        #: Three regions in reading order, not one rectangle and not one per page. The
        #: subclause opens at the foot of the earlier page, continues at the head of the next,
        #: and resumes on that same later page below the region it opened there. A single
        #: rectangle reached the middle region only, so the statements before and after it were
        #: never extracted and could not be cited by any reviewed fact.
        segments=(
            ClauseSegmentSpec(
                page_number=63,
                expected_bbox=(65.0, 725.0, 535.0, 792.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 80.0, 535.0, 232.0),
                expected_root_kind="bullets",
            ),
            #: Running prose rather than bullets, which is why the root shape is per segment:
            #: one contract for the whole clause could not describe both.
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 232.0, 535.0, 382.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        #: The clause's NOTEs become guidance rather than executable branches, and that
        #: guidance is grounded in this same fragment. A clause that declares routes declares
        #: all of them, this one's own decision included.
        projected_rule_ids=(
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
            f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
        ),
        evidence_clause_ids=(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,),
    ),
    #: The sibling subclause, its own reviewed fragment and its own evidence scope, feeding
    #: the rule above. Kept apart from that fragment rather than merged into it: a fragment
    #: whose nominal clause is one subclause must not quietly carry another's statements.
    ClauseAuditSpec(
        semantic_id=SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        clause="4.4.7.1.7.2",
        segments=(
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 410.0, 535.0, 445.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projection_role="evidence",
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        clause="4.4.7.2.5",
        segments=(
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 630.0, 535.0, 792.0),
                expected_root_kind="bullets",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        clause="4.4.7.2.5",
        segments=(
            ClauseSegmentSpec(
                page_number=67,
                expected_bbox=(65.0, 80.0, 535.0, 180.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",
        clause="4.4.7.2.3",
        segments=(
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 390.0, 535.0, 518.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",),
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",
        clause="4.4.7.2.4",
        segments=(
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 385.0, 535.0, 512.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",),
    ),
    # Retained as cited evidence, not as the source of the reduction rule: the monitoring
    # obligation each reduction route defers to is stated here.
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        clause="4.4.7.2.2",
        segments=(
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 110.0, 535.0, 258.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",),
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        clause="4.4.7.2.6",
        segments=(
            ClauseSegmentSpec(
                page_number=67,
                expected_bbox=(65.0, 185.0, 535.0, 350.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: Supply routes whose branch authority stays in this file rather than moving to reviewed
#: clause facts. Propagation's contract *is* an ordinal comparison over the overvoltage
#: category scale -- the ``reduce_one_level`` and ``take_more_severe_rating`` operations the
#: fact vocabulary names -- and no honest reviewed fact can express an ordinal comparison,
#: only the branches it enumerates. Porting it would therefore change behaviour, so it is
#: deliberately left here and tracked as #53C item 3 instead.
LEGACY_BRANCH_AUTHORITY_RULE_IDS = frozenset({ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION})

#: The one fact family each route's reviewed statements may belong to, by ``fact_kind``. Declared
#: beside the clause specs because it is the same reviewed reading: which clause states what kind
#: of rule. Authoring and the approval gate both enforce it, so a fact that cannot express a
#: route's branches cannot certify that route as reviewed, and a projector reading a route's facts
#: knows their type without inspecting them. Propagation is declared for completeness even though
#: it is the legacy route the gate skips.
SUPPLY_FACT_FAMILY_BY_ROUTE: dict[str, str] = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: "system_voltage",
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: "system_voltage",
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: "propagation_step",
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: "barrier_transfer",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": "spd_monitoring",
    ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: "hf_attenuation",
}


def _require_declared_fact_families(
    specs: tuple[ClauseAuditSpec, ...], families: dict[str, str]
) -> None:
    """Refuse, at import, a clause spec inventory and a fact family map that disagree.

    The approval gate blocks any declared supply route carrying no authored fact, while authoring
    and resolution both refuse a route this map forgets. A spec added without its entry is
    therefore unapprovable and unauthorable at once -- blocked for want of facts, and refused when
    a maintainer authors one -- with nothing saying so until someone tries both. The two are one
    reviewed reading, of which clause states what kind of rule, so they are checked where they are
    declared rather than trusted to stay in step.
    """

    declared = {spec.semantic_id for spec in specs}
    disagreement = declared.symmetric_difference(families)
    if disagreement:
        raise ValueError(
            f"supply clause specs and fact families disagree on: {sorted(disagreement)}"
        )


_require_declared_fact_families(SUPPLY_CLAUSES, SUPPLY_FACT_FAMILY_BY_ROUTE)

#: A ported projector's default when its call site supplies nothing: still refuses to
#: project, through the same "no facts for this route" check as a caller-supplied empty
#: result -- never a second, quieter way to get the old fallback.
_NO_CONFIRMED_FACTS = ConfirmedFacts()

#: Reviewed structural contract per projection: the node kind expected at each position, in
#: order. An ordered sequence rather than one (kind, count) pair because a clause spanning
#: several regions need not read as one kind throughout -- the system voltage clause is five
#: bullets and then one paragraph -- and "any kind" is the one weakening that would let a
#: reflowed clause project silently.
_SYSTEM_VOLTAGE_SHAPE = ("bullet", "bullet", "bullet", "bullet", "bullet", "paragraph")
_SYSTEM_VOLTAGE_NON_MAINS_SHAPE = ("paragraph",)
_PROPAGATION_SHAPE = ("bullet", "bullet", "bullet", "bullet")
_BARRIER_SHAPE = ("paragraph",)
_SPD_SHAPE = ("paragraph",)
_HF_TRANSFORMER_SHAPE = ("paragraph",)

#: Reviewed structural contract per SPD reduction route. Each was measured against the
#: licensed document from the fragment the recipe's own bbox extracts, so a reprint that
#: reflows any of these three clauses across a different number of nodes stops the build
#: instead of projecting a rule from a region nobody reviewed.
_SPD_SHAPE_BY_ROUTE: dict[str, tuple[str, ...]] = {
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": _SPD_SHAPE,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": _SPD_SHAPE,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": _SPD_SHAPE,
}


def _fail(message: str) -> NoReturn:
    raise ClauseStructureError(f"AMBIGUOUS_CLAUSE_STRUCTURE: {message}")


def _require_own_fragment(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    semantic_id: str,
    label: str,
) -> None:
    if fragment.id != f"raw-{semantic_id}":
        raise ValueError(f"{label} projection requires its own fragment")
    if fragment.source.standard != identity.standard or fragment.source.edition != identity.edition:
        raise ValueError(f"{label} fragment does not match its identified source")


def _require_shape(
    fragment: RawClauseFragment,
    shape: tuple[str, ...],
    label: str,
) -> None:
    if tuple(node.kind for node in fragment.nodes) != shape:
        _fail(f"{label} expected {len(shape)} reviewed node(s) of kinds {shape}")


def _matcher(name: str, values: tuple[str, ...] | None) -> Matcher:
    """Match a categorical input against a declared branch, or any value."""

    if values is None:
        return Matcher(input=name, op="any")
    if len(values) == 1:
        return Matcher(input=name, op="equals", values=values)
    return Matcher(input=name, op="in", values=values)


def _rows_overlap(first: tuple[Matcher, ...], second: tuple[Matcher, ...]) -> bool:
    """Whether some input tuple both rows would match.

    Two rows overlap when, for every input, their matchers are either equal or one of them
    matches any value: an ``op="any"`` matcher is what an unrestricted statement projects, and
    an unrestricted statement covers every value the specific one covers. Equality alone is not
    the test -- a statement stated without a purpose and one stated for a single purpose are
    never equal and still both answer the same question.
    """

    return all(
        one == other or one.op == "any" or other.op == "any"
        for one, other in zip(first, second, strict=True)
    )


def _require_distinct_branches(
    label: str, facts: tuple[SupplyFact, ...], rows: tuple[DecisionRow, ...]
) -> None:
    """Refuse two reviewed statements of one route whose branches are not disjoint.

    ``evaluate_decision`` serves the first row whose matchers fit, so two statements projecting
    overlapping matchers leave the later one shadowed over the overlap and its contradicting
    values unserved, with no error, no warning and a ``fact_set_sha256`` that covers both
    happily. That is the hazard ``_require_distinct_selectors`` refuses for two axis positions
    confirmed as the same selector.

    Overlap rather than equality, because equality catches only the narrowest case: an
    ``any_placement`` or ``any_purpose`` statement that also covers a specific one projects
    matchers that are never equal to it, and row order alone would decide which reading a
    consumer receives. Where the source really states a general rule and a special case, the
    special case's own dimension is what distinguishes them, and a set of statements this
    refuses is one whose distinguishing dimension nobody authored.

    Expressed over the projected matchers rather than over the facts, and so living here rather
    than in ``resolve_confirmed_clause_facts`` with the other refusals: which fields are branch
    dimensions and which are answers is the projector's own reading, and comparing facts would
    miss exactly the pair that matters -- two reduction statements agreeing on every dimension
    while naming different target categories.
    """

    seen: list[tuple[tuple[Matcher, ...], int]] = []
    for fact, row in zip(facts, rows, strict=True):
        for matchers, statement_index in seen:
            if _rows_overlap(matchers, row.matchers):
                raise ClauseStructureError(
                    f"{label} statements {statement_index} and {fact.statement_index} "
                    f"state branches that are not disjoint"
                )
        seen.append((row.matchers, fact.statement_index))


def _proposal(
    rule: DecisionRule | GuidanceRule,
    rule_kind: RuleKind,
    *fragments: RawClauseFragment,
) -> SemanticProposal:
    """One proposal grounded in every fragment the rule was read from.

    Several fragments aggregate through ``aggregate_artifact_sha256``, which is the function the
    approval gate re-derives a proposal's current source digest with, so a rule two subclauses
    state between them goes stale when either fragment changes. One fragment aggregates to its
    own digest, so a single-clause rule is grounded exactly as before.
    """

    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind=rule_kind,
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=aggregate_artifact_sha256(
            tuple((item.id, canonical_model_sha256(item)) for item in fragments)
        ),
    )


# --- system voltage resolution -----------------------------------------------------

_SUPPLY_KINDS = ("mains", "non_mains")
_PHASE_SYSTEMS = (
    "three_phase_star",
    "three_phase_delta",
    "three_phase_it",
    "single_phase_it",
    "single_phase",
    "unspecified",
)
_EARTHING_ARRANGEMENTS = ("tn", "tt", "it", "unspecified")
_INPUT_TOPOLOGIES = (
    "direct",
    "rectified_dc",
    "series_rectifier_bridges",
    "isolated_secondary",
)
#: The consumer's question space for the calculation purpose, declared here and never derived
#: from the reviewed facts. A declared input's vocabulary is the question space, not the
#: reviewed answer space: several of the clause's statements restrict no purpose at all, so a
#: fact set of only those would derive an empty tuple and ``DecisionRule`` would refuse the
#: whole rule with a message about a categorical input rather than about the authoring.
_CALCULATION_PURPOSES = ("impulse", "temporary_overvoltage")

#: Which fact field feeds which declared input, and the token that means "this statement
#: restricts this dimension to nothing". Every dimension gets a real matcher: two of these
#: inputs were once wired to ``op="any"`` on every row, which left them declared, asked about
#: by consumers, and unable to affect any answer.
_SYSTEM_VOLTAGE_DIMENSIONS = (
    ("supply_kind", "supply_kind", "any_supply_kind"),
    ("phase_system", "phase_system", "any_phase_system"),
    ("earthing_arrangement", "earthing", "any_earthing"),
    ("input_topology", "input_topology", "any_input_topology"),
    ("calculation_purpose", "purpose", "any_purpose"),
)


def _system_voltage_evidence_fragment(
    draft: object,
    identity: StandardIdentity,
    label: str,
) -> RawClauseFragment | None:
    """The non-mains subclause's fragment from the reviewed draft, or ``None`` without one.

    Read from the draft the way the preconditioning projection reads its sibling artifacts: the
    rule rests on two subclauses, and the fragment argument carries only the one whose identifier
    the rule bears. Resolution has already refused unless both scopes are reviewed and complete,
    so a draft reaching here holds both fragments; a caller supplying no draft grounds the
    proposal in the fragment it did supply.
    """

    fragments: tuple[RawClauseFragment, ...] = getattr(draft, "raw_clause_fragments", ())
    evidence = next(
        (item for item in fragments if item.id == f"raw-{SUPPLY_SYSTEM_VOLTAGE_NON_MAINS}"),
        None,
    )
    if evidence is None:
        return None
    _require_own_fragment(evidence, identity, SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, label)
    _require_shape(evidence, _SYSTEM_VOLTAGE_NON_MAINS_SHAPE, label)
    return evidence


def _statement_source(
    fact: SystemVoltageFact,
    fragments: tuple[RawClauseFragment, ...],
) -> SourceReference:
    """Where one statement was read: the first node it cites, in whichever fragment holds it.

    Two subclauses on two pages feed this one rule, and a node keeps the page it came from, so a
    row citing the rule's own fragment's first node unconditionally would name a page its
    statement is not on.
    """

    by_id = {item.id: item for item in fragments}
    for cited in fact.node_references:
        fragment = by_id.get(cited.fragment_id)
        node = (
            next((item for item in fragment.nodes if item.order == cited.node_order), None)
            if fragment is not None
            else None
        )
        if node is not None:
            return node.source
    return fragments[0].nodes[0].source


def _dimension_matcher(input_name: str, value: str, unrestricted: str) -> Matcher:
    """Match one authored dimension value, or every value where the statement states none.

    A statement its source leaves unrestricted on a dimension is one statement covering every
    value, not one per value, so it projects ``op="any"`` rather than being authored repeatedly.
    Unlike the attenuation clause's evidence kinds, none of these vocabularies carries a value
    the statement must be kept away from -- there is no "no supply kind yet" to accidentally
    answer for -- so the whole declared vocabulary is what an unrestricted statement covers.
    """

    if value == unrestricted:
        return Matcher(input=input_name, op="any")
    return _matcher(input_name, (value,))


def project_system_voltage_resolution(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule | GuidanceRule, ...], tuple[SemanticProposal, ...]]:
    """Project the reviewed mains and non-mains system voltage subclauses into one decision.

    Every row comes from one reviewed ``SystemVoltageFact``: the clause states the branch,
    this projection only shapes it into the rule's declared inputs and outputs. A route with
    no reviewed facts refuses rather than falling back to an inventory nobody reviewed.

    Two subclauses state this one rule between them, so the facts come from two evidence
    scopes and the rule's proposal is grounded in the aggregate of both fragments. One
    ``DecisionRule`` and one ``SemanticProposal`` come out regardless: pagination and clause
    numbering are provenance, and a consumer asks one question.
    """

    label = "supply system voltage resolution"
    _require_own_fragment(fragment, identity, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, label)
    _require_shape(fragment, _SYSTEM_VOLTAGE_SHAPE, label)
    evidence = _system_voltage_evidence_fragment(draft, identity, label)

    facts = (
        *confirmed_facts.for_route(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION),
        *confirmed_facts.for_route(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS),
    )
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    system_voltage_facts = tuple(fact for fact in facts if isinstance(fact, SystemVoltageFact))
    if len(system_voltage_facts) != len(facts):
        raise ValueError(f"{label} projection requires system voltage facts")

    grounding = (fragment,) if evidence is None else (fragment, evidence)
    measures = tuple(dict.fromkeys(fact.measure for fact in system_voltage_facts))
    rows = tuple(
        DecisionRow(
            matchers=tuple(
                _dimension_matcher(input_name, getattr(fact, field), unrestricted)
                for input_name, field, unrestricted in _SYSTEM_VOLTAGE_DIMENSIONS
            ),
            values=(DecisionValue(name="system_voltage_measure", categorical=fact.measure),),
            source=_statement_source(fact, grounding),
        )
        for fact in system_voltage_facts
    )
    _require_distinct_branches(label, system_voltage_facts, rows)

    rule = DecisionRule(
        id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        inputs=(
            DecisionInput(name="supply_kind", kind="categorical", allowed_values=_SUPPLY_KINDS),
            DecisionInput(name="phase_system", kind="categorical", allowed_values=_PHASE_SYSTEMS),
            DecisionInput(
                name="earthing_arrangement",
                kind="categorical",
                allowed_values=_EARTHING_ARRANGEMENTS,
            ),
            DecisionInput(
                name="input_topology", kind="categorical", allowed_values=_INPUT_TOPOLOGIES
            ),
            DecisionInput(
                name="calculation_purpose",
                kind="categorical",
                allowed_values=_CALCULATION_PURPOSES,
            ),
        ),
        outputs=(
            DecisionOutput(
                name="system_voltage_measure",
                kind="categorical",
                allowed_values=measures,
            ),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )
    guidance = GuidanceRule(
        id=f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
        title="System voltage resolution notes",
        summary=(
            "The source attaches NOTEs to the three-phase IT branches that relate the "
            "phase-to-artificial-neutral measure to the phase-to-phase measure and "
            "describe single-fault behaviour. They stay guidance: this projection names "
            "which measure applies and never computes one measure from another."
        ),
        warnings=(
            (
                "Read the source NOTEs in the cited clause before converting between "
                "the resolved measures."
            ),
        ),
        source=fragment.source,
    )
    return (rule, guidance), (
        _proposal(rule, "decision", *grounding),
        _proposal(guidance, "guidance", *grounding),
    )


# --- multiple source propagation ---------------------------------------------------

#: Overvoltage category designations in increasing severity. Designations, not values.
_OVERVOLTAGE_CATEGORIES = ("ovc_i", "ovc_ii", "ovc_iii", "ovc_iv")
_EVALUATED_SIDES = ("mains", "non_mains")


def _reduced_by_one_level(category: str) -> str:
    index = _OVERVOLTAGE_CATEGORIES.index(category)
    return _OVERVOLTAGE_CATEGORIES[max(index - 1, 0)]


def _more_severe(first: str, second: str) -> str:
    return max(first, second, key=_OVERVOLTAGE_CATEGORIES.index)


def project_multiple_source_propagation(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    # The legacy branch-authority route: resolution declares no facts for it, so this stays
    # the parameter every registered clause projector takes and this one never reads.
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the lettered alternatives of the two-supply clause into a decision."""

    label = "supply multiple source propagation"
    _require_own_fragment(fragment, identity, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION, label)
    _require_shape(fragment, _PROPAGATION_SHAPE, label)

    rows: list[DecisionRow] = []
    for side in _EVALUATED_SIDES:
        for mains_category in _OVERVOLTAGE_CATEGORIES:
            for non_mains_category in _OVERVOLTAGE_CATEGORIES:
                own = mains_category if side == "mains" else non_mains_category
                other = non_mains_category if side == "mains" else mains_category
                transferred = _reduced_by_one_level(other)
                rows.append(
                    DecisionRow(
                        matchers=(
                            Matcher(input="evaluated_side", op="equals", values=(side,)),
                            Matcher(
                                input="mains_overvoltage_category",
                                op="equals",
                                values=(mains_category,),
                            ),
                            Matcher(
                                input="non_mains_overvoltage_category",
                                op="equals",
                                values=(non_mains_category,),
                            ),
                            Matcher(input="galvanic_isolation_present", op="equals", boolean=True),
                        ),
                        values=(
                            DecisionValue(name="source_requirement", categorical=own),
                            DecisionValue(name="transferred_requirement", categorical=transferred),
                            DecisionValue(
                                name="governing_requirement",
                                categorical=_more_severe(own, transferred),
                            ),
                        ),
                        source=fragment.nodes[0].source,
                    )
                )
    rule = DecisionRule(
        id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        inputs=(
            DecisionInput(
                name="evaluated_side", kind="categorical", allowed_values=_EVALUATED_SIDES
            ),
            DecisionInput(
                name="mains_overvoltage_category",
                kind="categorical",
                allowed_values=_OVERVOLTAGE_CATEGORIES,
            ),
            DecisionInput(
                name="non_mains_overvoltage_category",
                kind="categorical",
                allowed_values=_OVERVOLTAGE_CATEGORIES,
            ),
            DecisionInput(name="galvanic_isolation_present", kind="boolean"),
        ),
        outputs=tuple(
            DecisionOutput(name=name, kind="categorical", allowed_values=_OVERVOLTAGE_CATEGORIES)
            for name in (
                "source_requirement",
                "transferred_requirement",
                "governing_requirement",
            )
        ),
        rows=tuple(rows),
        # Without galvanic isolation the barrier-transfer rule governs, so this rule
        # deliberately covers no such row.
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- verified barrier transfer -----------------------------------------------------

_ISOLATION_EVIDENCE_KINDS = ("none", "test", "calculation", "construction")
#: Every declared evidence kind except the absence of one. What this route asks about is a
#: *verified* barrier, which is this rule's own input name: a barrier claimed with no evidence at
#: all is not one, so the isolation-present statement is not answered for it.
_VERIFYING_EVIDENCE_KINDS = tuple(kind for kind in _ISOLATION_EVIDENCE_KINDS if kind != "none")
_DOWNSTREAM_CONNECTION_KINDS = ("no_isolation", "verified_galvanic_isolation")


def project_verified_barrier_transfer(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the isolation and no-isolation paths into a decision.

    Every row comes from one reviewed ``BarrierTransferFact``, and matches on both dimensions the
    statement is scoped to: the barrier and the kind of connection downstream of it. A row that
    matched every connection kind would answer for one the clause excludes -- the source scopes
    its propagation statement to circuits connected without galvanic isolation.

    ``transfer_permitted`` and ``propagates_to_connected_circuits`` are not independently authored
    content: a verified barrier is what makes the transfer permitted and what stops it propagating
    to circuits connected without isolation, so both mirror ``isolation_present`` by definition.
    Nor is the evidence a statement requires: the source states no evidence kinds at all, and
    ``_ISOLATION_EVIDENCE_KINDS`` is this recipe's own question vocabulary, so authoring one would
    be inventing source content. What "verified" excludes is the absence of evidence, and that
    much follows from the rule's own input name.
    """

    label = "supply verified barrier transfer"
    _require_own_fragment(fragment, identity, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, label)
    _require_shape(fragment, _BARRIER_SHAPE, label)

    facts = confirmed_facts.for_route(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    barrier_facts = tuple(fact for fact in facts if isinstance(fact, BarrierTransferFact))
    if len(barrier_facts) != len(facts):
        raise ValueError(f"{label} projection requires barrier transfer facts")

    requirements = tuple(dict.fromkeys(fact.combined_circuit_rule for fact in barrier_facts))
    rows = tuple(
        DecisionRow(
            matchers=(
                Matcher(
                    input="galvanic_isolation_verified",
                    op="equals",
                    boolean=fact.isolation_present,
                ),
                _matcher(
                    "isolation_evidence_kind",
                    _VERIFYING_EVIDENCE_KINDS if fact.isolation_present else None,
                ),
                _matcher("downstream_connection_kind", (fact.downstream_connection_kind,)),
            ),
            values=(
                DecisionValue(name="transfer_permitted", boolean=fact.isolation_present),
                DecisionValue(
                    name="combined_circuit_requirement",
                    categorical=fact.combined_circuit_rule,
                ),
                DecisionValue(
                    name="propagates_to_connected_circuits",
                    boolean=not fact.isolation_present,
                ),
            ),
            source=fragment.nodes[0].source,
        )
        for fact in barrier_facts
    )
    _require_distinct_branches(label, barrier_facts, rows)

    rule = DecisionRule(
        id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        inputs=(
            DecisionInput(name="galvanic_isolation_verified", kind="boolean"),
            DecisionInput(
                name="isolation_evidence_kind",
                kind="categorical",
                allowed_values=_ISOLATION_EVIDENCE_KINDS,
            ),
            DecisionInput(
                name="downstream_connection_kind",
                kind="categorical",
                allowed_values=_DOWNSTREAM_CONNECTION_KINDS,
            ),
        ),
        outputs=(
            DecisionOutput(name="transfer_permitted", kind="boolean"),
            DecisionOutput(
                name="combined_circuit_requirement",
                kind="categorical",
                allowed_values=requirements,
            ),
            DecisionOutput(name="propagates_to_connected_circuits", kind="boolean"),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- transient limiter (SPD) reduction requirements --------------------------------

#: The consumer's question space for placement. ``bundled_external_to_pecs`` is its own question
#: because the monitoring clause's external-device requirement reaches only a device the
#: manufacturer bundles with their product: a consumer asking about any other external device gets
#: no match, which is what the source states about it -- nothing.
_DEVICE_PLACEMENTS = ("internal_to_pecs", "external_to_pecs", "bundled_external_to_pecs")
_INSULATION_CLASSES = ("functional", "basic", "supplementary", "double", "reinforced")
_VERIFICATION_REFERENCES = ("inspection_and_dielectric_verification", "not_required")

_SPD_MONITORING_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"

#: The monitoring route's own clause states no category step at all (``SpdMonitoringFact``
#: carries no OVC field), so its rows fill this shared output with this one fixed token
#: rather than a value borrowed from the mains/non-mains routes' vocabulary.
_NOT_REDUCED = "not_reduced"


def _spd_reduction_row(fact: SpdReductionFact, fragment: RawClauseFragment) -> DecisionRow:
    """One row for one reviewed mains/non-mains reduction statement.

    ``reduction_permitted`` and ``reduced_category`` both come from comparing the fact's own
    ``source_ovc`` and ``target_ovc``: a statement whose target differs from its source is a
    permitted reduction to that category, one whose target repeats its source is the
    unreduced floor -- not independently authored content, the same way a verified barrier
    mirrors its own presence in ``project_verified_barrier_transfer``.
    """

    reduced = fact.target_ovc != fact.source_ovc
    monitoring_required = fact.monitoring_obligation == "required"
    return DecisionRow(
        matchers=(
            # The source requires monitoring for an internal and a qualifying external
            # device alike, so placement is declared but does not discriminate.
            Matcher(input="device_placement", op="any"),
            _matcher("insulation_class", (fact.insulation_class,)),
            Matcher(input="device_degradable", op="equals", boolean=fact.degradable),
            Matcher(input="part_of_category_reduction", op="equals", boolean=True),
        ),
        values=(
            DecisionValue(name="reduction_permitted", boolean=reduced),
            DecisionValue(name="reduced_category", categorical=fact.target_ovc),
            DecisionValue(name="monitoring_required", boolean=monitoring_required),
            DecisionValue(name="status_indication_required", boolean=monitoring_required),
            DecisionValue(
                name="verification_reference",
                categorical="inspection_and_dielectric_verification",
            ),
            DecisionValue(
                name="reinforced_floor_applies",
                boolean=fact.insulation_class in ("double", "reinforced"),
            ),
        ),
        source=fragment.nodes[0].source,
    )


def _placement_matcher(placement: str) -> Matcher:
    """Match one authored placement, or every placement the monitoring clause distinguishes.

    ``any_placement`` names a statement the source makes once for the external-device monitoring
    and the internal monitoring test together -- one statement, not two, the way ``any_purpose``
    names one system voltage statement. Without it that statement cannot be authored at all: a
    single required placement leaves whichever one the maintainer did not pick reaching no row.
    """

    if placement == "any_placement":
        return Matcher(input="device_placement", op="any")
    return _matcher("device_placement", (placement,))


def _spd_monitoring_row(fact: SpdMonitoringFact, fragment: RawClauseFragment) -> DecisionRow:
    """One row for one reviewed monitoring statement.

    ``device_placement`` and ``participates_in_reduction`` are both read as branch values: the
    source gates the monitoring obligation on each of them, and the fact's placement vocabulary
    is this rule's own.

    ``compliance_evidence`` is not, and that one is a real gap rather than an oversight. The
    source names two compliance routes for monitoring, while this rule's declared
    ``verification_reference`` output carries neither of them -- it has the mains/non-mains
    routes' tokens. Widening that output is a contract change, so it is #53C item 5, and until
    then the fact carries a reading the rule cannot yet express.

    The three reduction outputs below are the mains and non-mains routes' concern; this route
    fills them with a fixed, uninformative value only because all three routes still share one
    declared output tuple. Right-sizing that per route is #53C item 5 as well.
    """

    return DecisionRow(
        matchers=(
            _placement_matcher(fact.device_placement),
            Matcher(input="insulation_class", op="any"),
            Matcher(input="device_degradable", op="any"),
            Matcher(
                input="part_of_category_reduction",
                op="equals",
                boolean=fact.participates_in_reduction,
            ),
        ),
        values=(
            DecisionValue(name="reduction_permitted", boolean=False),
            DecisionValue(name="reduced_category", categorical=_NOT_REDUCED),
            DecisionValue(name="monitoring_required", boolean=fact.monitoring_required),
            DecisionValue(name="status_indication_required", boolean=fact.monitoring_required),
            DecisionValue(
                name="verification_reference",
                categorical=(
                    "inspection_and_dielectric_verification"
                    if fact.monitoring_required
                    else "not_required"
                ),
            ),
            DecisionValue(name="reinforced_floor_applies", boolean=False),
        ),
        source=fragment.nodes[0].source,
    )


def project_spd_reduction_requirements(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the transient-limiter monitoring and reduction clause into a decision.

    Registered for all three SPD reduction routes (mains, non_mains, monitoring) under one
    function body: the fragment passed to a given call is that route's own fragment, and its
    id says which route this call produces. The mains and non-mains routes derive their rows
    from their own reviewed ``SpdReductionFact``s; the monitoring route derives its rows from
    its own reviewed ``SpdMonitoringFact``s. Every route refuses to project without its own
    family's facts.
    """

    label = "supply SPD reduction requirements"
    rule_id = fragment.id.removeprefix("raw-")
    shape = _SPD_SHAPE_BY_ROUTE.get(rule_id)
    if shape is None:
        raise ValueError(f"{label} projection requires its own fragment")
    _require_own_fragment(fragment, identity, rule_id, label)
    _require_shape(fragment, shape, label)

    facts = confirmed_facts.for_route(rule_id)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")

    if rule_id == _SPD_MONITORING_ROUTE:
        monitoring_facts = tuple(fact for fact in facts if isinstance(fact, SpdMonitoringFact))
        if len(monitoring_facts) != len(facts):
            raise ValueError(f"{label} projection requires SPD monitoring facts")
        rows = tuple(_spd_monitoring_row(fact, fragment) for fact in monitoring_facts)
        _require_distinct_branches(label, monitoring_facts, rows)
        reduced_categories: tuple[str, ...] = (_NOT_REDUCED,)
    else:
        reduction_facts = tuple(fact for fact in facts if isinstance(fact, SpdReductionFact))
        if len(reduction_facts) != len(facts):
            raise ValueError(f"{label} projection requires SPD reduction facts")
        rows = tuple(_spd_reduction_row(fact, fragment) for fact in reduction_facts)
        _require_distinct_branches(label, reduction_facts, rows)
        reduced_categories = tuple(dict.fromkeys(fact.target_ovc for fact in reduction_facts))

    rule = DecisionRule(
        id=rule_id,
        inputs=(
            DecisionInput(
                name="device_placement", kind="categorical", allowed_values=_DEVICE_PLACEMENTS
            ),
            DecisionInput(
                name="insulation_class",
                kind="categorical",
                allowed_values=_INSULATION_CLASSES,
            ),
            DecisionInput(name="device_degradable", kind="boolean"),
            DecisionInput(name="part_of_category_reduction", kind="boolean"),
        ),
        outputs=(
            DecisionOutput(name="reduction_permitted", kind="boolean"),
            DecisionOutput(
                name="reduced_category",
                kind="categorical",
                allowed_values=reduced_categories,
            ),
            DecisionOutput(name="monitoring_required", kind="boolean"),
            DecisionOutput(name="status_indication_required", kind="boolean"),
            DecisionOutput(
                name="verification_reference",
                kind="categorical",
                allowed_values=_VERIFICATION_REFERENCES,
            ),
            DecisionOutput(name="reinforced_floor_applies", kind="boolean"),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- high-frequency isolating transformer ------------------------------------------

#: DVC designations. Designations only; no source value or wording. The document defines
#: exactly these three (3.19, 3.20, 3.21) and Table 2 and Table 3 name no others; there is
#: no DVC A and no DVC D. Table 2 splits DVC As into a wet and a dry row, which changes the
#: voltage limits, not the designation.
_DVC_DESIGNATIONS = ("dvc_as", "dvc_b", "dvc_c")
#: The consumer's question space for evidence, declared here and never derived from the reviewed
#: facts. ``none`` -- no evidence yet -- is the first question a consumer asks and no authored
#: statement can name it, so deriving this vocabulary from the facts would put that question
#: outside the input's allowed values and raise instead of answering it.
_ATTENUATION_EVIDENCE_KINDS = ("none", "test", "simulation", "calculation")
#: The evidence routes a statement may accept: every declared kind except the absence of one.
_SHOWN_EVIDENCE_KINDS = tuple(kind for kind in _ATTENUATION_EVIDENCE_KINDS if kind != "none")
#: What a consumer must still show, never an echo of what it supplied.
_REQUIRED_EVIDENCE_KINDS = ("test_or_simulation_or_calculation", "already_provided")
#: Multipliers from a reviewed frequency unit token to hertz. Names the units the
#: generic tokenizer emits; the threshold itself is read from the document.
_FREQUENCY_UNIT_SCALES = {"Hz": 1, "kHz": 1_000, "MHz": 1_000_000}


def _evidence_matcher(evidence_kind: str) -> Matcher:
    """Match one authored evidence route, or every route the statement accepts.

    Deliberately not ``op="any"`` for ``any_evidence``, unlike ``any_purpose``: there every
    declared value of ``calculation_purpose`` is one the statement covers, while here the declared
    vocabulary also carries ``none``, which is the one value the permission may never be granted
    for. A kind this rule declares but no statement accepts falls through to no match, the way a
    DVC designation no fact gates through does.
    """

    if evidence_kind == "any_evidence":
        return _matcher("attenuation_evidence_kind", _SHOWN_EVIDENCE_KINDS)
    return _matcher("attenuation_evidence_kind", (evidence_kind,))


def _frequency_threshold_hz(fragment: RawClauseFragment, label: str) -> Decimal:
    """Read the clause's single frequency threshold from its reviewed tokens."""

    pairs = [
        (token, fragment.tokens[index + 1])
        for index, token in enumerate(fragment.tokens)
        if token.kind == "quantity"
        and index + 1 < len(fragment.tokens)
        and fragment.tokens[index + 1].kind == "unit"
        and str(fragment.tokens[index + 1].normalized) in _FREQUENCY_UNIT_SCALES
    ]
    if len(pairs) != 1:
        _fail(f"{label} expected exactly one reviewed frequency quantity and unit pair")
    quantity, unit = pairs[0]
    return Decimal(quantity.normalized) * _FREQUENCY_UNIT_SCALES[str(unit.normalized)]


def project_hf_transformer_attenuation(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the isolating-transformer attenuation clause into a decision.

    Every row comes from one reviewed ``HfAttenuationFact``: it states the DVC gate the clause
    applies to and the evidence route or routes it accepts.
    ``working_voltage_basis_permitted`` is not independently authored content -- an accepted
    evidence kind is what grants the permission, so it mirrors the fact's presence, the same way
    a verified barrier's transfer permission mirrors its own presence in
    ``project_verified_barrier_transfer``. Neither is the outstanding-showing row each gate also
    gets: it is the same statement read from the other side, the route being an engineering-input
    requirement until the attenuation is shown, never a permission. It comes first, so no
    consumer reaches a permission by supplying no evidence.

    The frequency threshold stays read from the fragment's own tokens rather than declared: it is
    a numeric source value, and an existing test pins that behaviour. A route with no
    reviewed facts refuses rather than falling back to an inventory nobody reviewed.
    """

    label = "supply high-frequency transformer attenuation"
    _require_own_fragment(fragment, identity, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION, label)
    _require_shape(fragment, _HF_TRANSFORMER_SHAPE, label)
    threshold_hz = _frequency_threshold_hz(fragment, label)

    facts = confirmed_facts.for_route(ids.SUPPLY_HF_TRANSFORMER_ATTENUATION)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    attenuation_facts = tuple(fact for fact in facts if isinstance(fact, HfAttenuationFact))
    if len(attenuation_facts) != len(facts):
        raise ValueError(f"{label} projection requires HF attenuation facts")

    def _row(*, gate: str, evidence: Matcher, permitted: bool, required: str) -> DecisionRow:
        return DecisionRow(
            matchers=(
                _matcher("circuit_dvc", (gate,)),
                Matcher(input="transformer_frequency_hz", op="range", minimum=threshold_hz),
                Matcher(input="isolation_provided", op="equals", boolean=True),
                evidence,
            ),
            values=(
                DecisionValue(name="working_voltage_basis_permitted", boolean=permitted),
                DecisionValue(name="required_evidence_kinds", categorical=required),
            ),
            source=fragment.nodes[0].source,
        )

    # One outstanding-showing row per gate the facts state rather than per fact: several
    # statements may accept different routes through one gate, and they all leave the same
    # showing outstanding.
    outstanding = tuple(
        _row(
            gate=gate,
            evidence=_matcher("attenuation_evidence_kind", ("none",)),
            permitted=False,
            required="test_or_simulation_or_calculation",
        )
        for gate in dict.fromkeys(fact.dvc_gate for fact in attenuation_facts)
    )
    shown = tuple(
        _row(
            gate=fact.dvc_gate,
            evidence=_evidence_matcher(fact.evidence_kind),
            permitted=True,
            required="already_provided",
        )
        for fact in attenuation_facts
    )
    # Over the per-statement rows only: the outstanding-showing rows are one per distinct gate
    # and so distinct by construction, and they carry no statement to name in a refusal.
    _require_distinct_branches(label, attenuation_facts, shown)

    rule = DecisionRule(
        id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        inputs=(
            DecisionInput(name="circuit_dvc", kind="categorical", allowed_values=_DVC_DESIGNATIONS),
            DecisionInput(name="transformer_frequency_hz", kind="numeric", unit="Hz"),
            DecisionInput(name="isolation_provided", kind="boolean"),
            DecisionInput(
                name="attenuation_evidence_kind",
                kind="categorical",
                allowed_values=_ATTENUATION_EVIDENCE_KINDS,
            ),
        ),
        outputs=(
            DecisionOutput(name="working_voltage_basis_permitted", kind="boolean"),
            DecisionOutput(
                name="required_evidence_kinds",
                kind="categorical",
                allowed_values=_REQUIRED_EVIDENCE_KINDS,
            ),
        ),
        rows=outstanding + shown,
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: project_system_voltage_resolution,
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: project_multiple_source_propagation,
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: project_verified_barrier_transfer,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": project_spd_reduction_requirements,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": project_spd_reduction_requirements,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": project_spd_reduction_requirements,
    ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: project_hf_transformer_attenuation,
}

__all__ = [
    "CLAUSE_PROJECTORS",
    "LEGACY_BRANCH_AUTHORITY_RULE_IDS",
    "SUPPLY_CLAUSES",
    "SUPPLY_FACT_FAMILY_BY_ROUTE",
    "SUPPLY_SYSTEM_VOLTAGE_NON_MAINS",
    "project_hf_transformer_attenuation",
    "project_multiple_source_propagation",
    "project_spd_reduction_requirements",
    "project_system_voltage_resolution",
    "project_verified_barrier_transfer",
]
