"""IEC 62477-1:2022 supply-side clause recipes and their decision projections.

The recipe declares page/bbox/shape locators only. Every branch, input, and output
vocabulary below is an author-written neutral identifier: no source value, heading,
note, or clause prose lives in this file. A reviewed fragment whose node shape falls
outside the declared contract blocks with ``AMBIGUOUS_CLAUSE_STRUCTURE`` rather than
letting a projection guess a branch.

Each ``ClauseAuditSpec`` carries one page and one bbox, so a projection is grounded in
exactly one page region. Where the source states a branch inventory across a page break
(the mains system-voltage clause) the fragment anchors the clause structurally and the
branch inventory itself is declared here, the same way the DVC fault-applicability
projection derives its selectors from the maintained curve recipes.
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
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)

#: Measured with pdfplumber against the licensed document; the x range excludes the
#: licence watermark columns at either margin.
SUPPLY_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        clause="4.4.7.1.7.1",
        page_number=64,
        expected_bbox=(65.0, 80.0, 535.0, 232.0),
        expected_root_kind="bullets",
        output_kind="decision",
        #: The clause's NOTEs become guidance rather than executable branches, and that
        #: guidance is grounded in this same fragment. A clause that declares routes declares
        #: all of them, this one's own decision included.
        projected_rule_ids=(
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
            f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
        ),
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        clause="4.4.7.2.5",
        page_number=66,
        expected_bbox=(65.0, 630.0, 535.0, 792.0),
        expected_root_kind="bullets",
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        clause="4.4.7.2.5",
        page_number=67,
        expected_bbox=(65.0, 80.0, 535.0, 180.0),
        expected_root_kind="paragraph",
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",
        clause="4.4.7.2.3",
        page_number=65,
        expected_bbox=(65.0, 390.0, 535.0, 518.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",),
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",
        clause="4.4.7.2.4",
        page_number=66,
        expected_bbox=(65.0, 385.0, 535.0, 512.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",),
    ),
    # Retained as cited evidence, not as the source of the reduction rule: the monitoring
    # obligation each reduction route defers to is stated here.
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        clause="4.4.7.2.2",
        page_number=65,
        expected_bbox=(65.0, 110.0, 535.0, 258.0),
        expected_root_kind="paragraph",
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",),
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        clause="4.4.7.2.6",
        page_number=67,
        expected_bbox=(65.0, 185.0, 535.0, 350.0),
        expected_root_kind="paragraph",
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
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: "propagation_step",
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: "barrier_transfer",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": "spd_monitoring",
    ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: "hf_attenuation",
}

#: Reviewed structural contract per projection: (node kind, node count).
_SYSTEM_VOLTAGE_SHAPE = ("bullet", 3)
_PROPAGATION_SHAPE = ("bullet", 4)
_BARRIER_SHAPE = ("paragraph", 1)
_SPD_SHAPE = ("paragraph", 1)
_HF_TRANSFORMER_SHAPE = ("paragraph", 1)

#: Reviewed structural contract per SPD reduction route. Each was measured against the
#: licensed document from the fragment the recipe's own bbox extracts, so a reprint that
#: reflows any of these three clauses across a different number of nodes stops the build
#: instead of projecting a rule from a region nobody reviewed.
_SPD_SHAPE_BY_ROUTE: dict[str, tuple[str, int]] = {
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
    shape: tuple[str, int],
    label: str,
) -> None:
    kind, count = shape
    if len(fragment.nodes) != count or any(node.kind != kind for node in fragment.nodes):
        _fail(f"{label} expected {count} reviewed {kind} node(s)")


def _matcher(name: str, values: tuple[str, ...] | None) -> Matcher:
    """Match a categorical input against a declared branch, or any value."""

    if values is None:
        return Matcher(input=name, op="any")
    if len(values) == 1:
        return Matcher(input=name, op="equals", values=values)
    return Matcher(input=name, op="in", values=values)


def _proposal(
    rule: DecisionRule | GuidanceRule,
    rule_kind: RuleKind,
    fragment: RawClauseFragment,
) -> SemanticProposal:
    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind=rule_kind,
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
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
_CALCULATION_PURPOSES = ("impulse", "temporary_overvoltage")
#: Which voltage measure the consumer must use. Names the measure only; the recipe
#: projects no conversion between measures.
_SYSTEM_VOLTAGE_MEASURES = (
    "phase_to_earth_rms",
    "phase_to_phase_rms",
    "phase_to_artificial_neutral_rms",
    "pre_rectifier_ac_rms",
    "not_derived_from_mains_supply",
)

#: One row per source branch: supply kind, phase system, earthing arrangement, input
#: topology, calculation purpose, resolved measure. ``None`` means the branch does not
#: discriminate on that input. The inventory is nine branches; a projection that cannot
#: build all nine is a defect, not a fallback.
_SYSTEM_VOLTAGE_BRANCHES: tuple[
    tuple[
        tuple[str, ...],
        tuple[str, ...] | None,
        tuple[str, ...] | None,
        tuple[str, ...],
        tuple[str, ...],
        str,
    ],
    ...,
] = (
    (
        ("mains",),
        ("three_phase_star",),
        ("tn", "tt"),
        ("direct",),
        _CALCULATION_PURPOSES,
        "phase_to_earth_rms",
    ),
    (
        ("mains",),
        ("three_phase_delta",),
        ("tn", "tt"),
        ("direct",),
        _CALCULATION_PURPOSES,
        "phase_to_phase_rms",
    ),
    (
        ("mains",),
        ("three_phase_it",),
        ("it",),
        ("direct",),
        ("impulse",),
        "phase_to_artificial_neutral_rms",
    ),
    (
        ("mains",),
        ("three_phase_it",),
        ("it",),
        ("direct",),
        ("temporary_overvoltage",),
        "phase_to_phase_rms",
    ),
    (
        ("mains",),
        ("single_phase_it",),
        ("it",),
        ("direct",),
        _CALCULATION_PURPOSES,
        "phase_to_phase_rms",
    ),
    (
        ("mains",),
        None,
        ("tn", "tt", "it"),
        ("rectified_dc",),
        _CALCULATION_PURPOSES,
        "pre_rectifier_ac_rms",
    ),
    (
        ("mains",),
        None,
        ("tn", "tt", "it"),
        ("series_rectifier_bridges",),
        ("impulse",),
        "pre_rectifier_ac_rms",
    ),
    (
        ("mains",),
        None,
        None,
        ("isolated_secondary",),
        _CALCULATION_PURPOSES,
        "not_derived_from_mains_supply",
    ),
    (
        ("non_mains",),
        None,
        ("unspecified",),
        ("direct",),
        _CALCULATION_PURPOSES,
        "phase_to_phase_rms",
    ),
)


def project_system_voltage_resolution(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    # ponytail: ported in a later task of this slice
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule | GuidanceRule, ...], tuple[SemanticProposal, ...]]:
    """Project the reviewed mains/non-mains system voltage clause into a decision."""

    label = "supply system voltage resolution"
    _require_own_fragment(fragment, identity, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, label)
    _require_shape(fragment, _SYSTEM_VOLTAGE_SHAPE, label)

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
                allowed_values=_SYSTEM_VOLTAGE_MEASURES,
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    _matcher("supply_kind", supply_kind),
                    _matcher("phase_system", phase_system),
                    _matcher("earthing_arrangement", earthing),
                    _matcher("input_topology", topology),
                    _matcher("calculation_purpose", purpose),
                ),
                values=(DecisionValue(name="system_voltage_measure", categorical=measure),),
                source=fragment.nodes[0].source,
            )
            for supply_kind, phase_system, earthing, topology, purpose, measure in (
                _SYSTEM_VOLTAGE_BRANCHES
            )
        ),
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
        _proposal(rule, "decision", fragment),
        _proposal(guidance, "guidance", fragment),
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
_DOWNSTREAM_CONNECTION_KINDS = ("no_isolation", "verified_galvanic_isolation")
_COMBINED_CIRCUIT_REQUIREMENTS = ("more_severe_of_both_sides", "side_specific_from_transfer")


def project_verified_barrier_transfer(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    # ponytail: ported in a later task of this slice
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the isolation and no-isolation paths into a decision."""

    label = "supply verified barrier transfer"
    _require_own_fragment(fragment, identity, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, label)
    _require_shape(fragment, _BARRIER_SHAPE, label)

    def _row(
        *,
        verified: bool,
        evidence: tuple[str, ...] | None,
        connection: str,
        permitted: bool,
        requirement: str,
        propagates: bool,
    ) -> DecisionRow:
        return DecisionRow(
            matchers=(
                Matcher(input="galvanic_isolation_verified", op="equals", boolean=verified),
                _matcher("isolation_evidence_kind", evidence),
                Matcher(input="downstream_connection_kind", op="equals", values=(connection,)),
            ),
            values=(
                DecisionValue(name="transfer_permitted", boolean=permitted),
                DecisionValue(name="combined_circuit_requirement", categorical=requirement),
                DecisionValue(name="propagates_to_connected_circuits", boolean=propagates),
            ),
            source=fragment.nodes[0].source,
        )

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
                allowed_values=_COMBINED_CIRCUIT_REQUIREMENTS,
            ),
            DecisionOutput(name="propagates_to_connected_circuits", kind="boolean"),
        ),
        rows=(
            _row(
                verified=False,
                evidence=None,
                connection="no_isolation",
                permitted=False,
                requirement="more_severe_of_both_sides",
                propagates=True,
            ),
            _row(
                verified=True,
                evidence=("test", "calculation", "construction"),
                connection="verified_galvanic_isolation",
                permitted=True,
                requirement="side_specific_from_transfer",
                propagates=False,
            ),
        ),
        # Claimed isolation without evidence, and connection kinds the source does not
        # settle, are left uncovered on purpose so the consumer blocks instead of
        # inheriting a guessed outcome.
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- transient limiter (SPD) reduction requirements --------------------------------

_DEVICE_PLACEMENTS = ("internal_to_pecs", "external_to_pecs")
_INSULATION_CLASSES = ("functional", "basic", "supplementary", "double", "reinforced")
#: Classes the source forbids reducing below the unreduced basic requirement.
_FLOORED_INSULATION_CLASSES = ("double", "reinforced")
_REDUCIBLE_INSULATION_CLASSES = ("functional", "basic", "supplementary")
_REDUCED_CATEGORIES = ("one_level_lower", "not_reduced")
_VERIFICATION_REFERENCES = ("inspection_and_dielectric_verification", "not_required")


def project_spd_reduction_requirements(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    # ponytail: ported in a later task of this slice
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the transient-limiter monitoring and reduction clause into a decision.

    Registered for all three SPD reduction routes (mains, non_mains, monitoring) under one
    function body: the fragment passed to a given call is that route's own fragment, and
    its id says which route this call produces. The rows below are still the single
    reviewed clause's rule, shared unchanged across routes -- #53 Task 6 gives each route
    its own reviewed branch logic.
    """

    label = "supply SPD reduction requirements"
    rule_id = fragment.id.removeprefix("raw-")
    shape = _SPD_SHAPE_BY_ROUTE.get(rule_id)
    if shape is None:
        raise ValueError(f"{label} projection requires its own fragment")
    _require_own_fragment(fragment, identity, rule_id, label)
    _require_shape(fragment, shape, label)

    def _row(
        *,
        part_of_reduction: bool,
        classes: tuple[str, ...] | None,
        degradable: bool | None,
        permitted: bool,
        reduced: str,
        monitoring: bool,
        indication: bool,
        verification: str,
        floor: bool,
    ) -> DecisionRow:
        matchers = [
            Matcher(input="part_of_category_reduction", op="equals", boolean=part_of_reduction),
            # The source requires monitoring for an internal and a qualifying external
            # device alike, so placement is declared but does not discriminate.
            Matcher(input="device_placement", op="any"),
            _matcher("insulation_class", classes),
        ]
        matchers.append(
            Matcher(input="device_degradable", op="any")
            if degradable is None
            else Matcher(input="device_degradable", op="equals", boolean=degradable)
        )
        return DecisionRow(
            matchers=tuple(matchers),
            values=(
                DecisionValue(name="reduction_permitted", boolean=permitted),
                DecisionValue(name="reduced_category", categorical=reduced),
                DecisionValue(name="monitoring_required", boolean=monitoring),
                DecisionValue(name="status_indication_required", boolean=indication),
                DecisionValue(name="verification_reference", categorical=verification),
                DecisionValue(name="reinforced_floor_applies", boolean=floor),
            ),
            source=fragment.nodes[0].source,
        )

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
                allowed_values=_REDUCED_CATEGORIES,
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
        # Row order mirrors the source: the exemption for a device outside a category
        # reduction first, then the double/reinforced floor, then the reducible classes.
        rows=(
            _row(
                part_of_reduction=False,
                classes=None,
                degradable=None,
                permitted=False,
                reduced="not_reduced",
                monitoring=False,
                indication=False,
                verification="not_required",
                floor=False,
            ),
            _row(
                part_of_reduction=True,
                classes=_FLOORED_INSULATION_CLASSES,
                degradable=True,
                permitted=False,
                reduced="not_reduced",
                monitoring=True,
                indication=True,
                verification="inspection_and_dielectric_verification",
                floor=True,
            ),
            _row(
                part_of_reduction=True,
                classes=_FLOORED_INSULATION_CLASSES,
                degradable=False,
                permitted=False,
                reduced="not_reduced",
                monitoring=False,
                indication=False,
                verification="inspection_and_dielectric_verification",
                floor=True,
            ),
            _row(
                part_of_reduction=True,
                classes=_REDUCIBLE_INSULATION_CLASSES,
                degradable=True,
                permitted=True,
                reduced="one_level_lower",
                monitoring=True,
                indication=True,
                verification="inspection_and_dielectric_verification",
                floor=False,
            ),
            _row(
                part_of_reduction=True,
                classes=_REDUCIBLE_INSULATION_CLASSES,
                degradable=False,
                permitted=True,
                reduced="one_level_lower",
                monitoring=False,
                indication=False,
                verification="inspection_and_dielectric_verification",
                floor=False,
            ),
        ),
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
#: The clause's own DVC gate.
_HF_TRANSFORMER_DVC_GATE = ("dvc_as", "dvc_b")
_ATTENUATION_EVIDENCE_KINDS = ("none", "test", "simulation", "calculation")
_REQUIRED_EVIDENCE_KINDS = ("test_or_simulation_or_calculation", "already_provided")
#: Multipliers from a reviewed frequency unit token to hertz. Names the units the
#: generic tokenizer emits; the threshold itself is read from the document.
_FREQUENCY_UNIT_SCALES = {"Hz": 1, "kHz": 1_000, "MHz": 1_000_000}


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
    # ponytail: ported in a later task of this slice
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the isolating-transformer attenuation clause into a decision."""

    label = "supply high-frequency transformer attenuation"
    _require_own_fragment(fragment, identity, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION, label)
    _require_shape(fragment, _HF_TRANSFORMER_SHAPE, label)
    threshold_hz = _frequency_threshold_hz(fragment, label)

    def _row(
        *,
        evidence: tuple[str, ...],
        permitted: bool,
        required: str,
    ) -> DecisionRow:
        return DecisionRow(
            matchers=(
                _matcher("circuit_dvc", _HF_TRANSFORMER_DVC_GATE),
                Matcher(input="transformer_frequency_hz", op="range", minimum=threshold_hz),
                Matcher(input="isolation_provided", op="equals", boolean=True),
                _matcher("attenuation_evidence_kind", evidence),
            ),
            values=(
                DecisionValue(name="working_voltage_basis_permitted", boolean=permitted),
                DecisionValue(name="required_evidence_kinds", categorical=required),
            ),
            source=fragment.nodes[0].source,
        )

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
        # Missing evidence first: the route is an engineering-input requirement until
        # the attenuation is shown, never a permission.
        rows=(
            _row(
                evidence=("none",),
                permitted=False,
                required="test_or_simulation_or_calculation",
            ),
            _row(
                evidence=("test", "simulation", "calculation"),
                permitted=True,
                required="already_provided",
            ),
        ),
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
    "project_hf_transformer_attenuation",
    "project_multiple_source_propagation",
    "project_spd_reduction_requirements",
    "project_system_voltage_resolution",
    "project_verified_barrier_transfer",
]
