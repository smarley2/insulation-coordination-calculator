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
)

#: Reviewed structural contract per projection: (node kind, node count).
_SYSTEM_VOLTAGE_SHAPE = ("bullet", 3)
_PROPAGATION_SHAPE = ("bullet", 4)
_BARRIER_SHAPE = ("paragraph", 1)


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
    if (
        fragment.source.standard != identity.standard
        or fragment.source.edition != identity.edition
    ):
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
    (("mains",), ("three_phase_star",), ("tn", "tt"), ("direct",), _CALCULATION_PURPOSES,
     "phase_to_earth_rms"),
    (("mains",), ("three_phase_delta",), ("tn", "tt"), ("direct",), _CALCULATION_PURPOSES,
     "phase_to_phase_rms"),
    (("mains",), ("three_phase_it",), ("it",), ("direct",), ("impulse",),
     "phase_to_artificial_neutral_rms"),
    (("mains",), ("three_phase_it",), ("it",), ("direct",), ("temporary_overvoltage",),
     "phase_to_phase_rms"),
    (("mains",), ("single_phase_it",), ("it",), ("direct",), _CALCULATION_PURPOSES,
     "phase_to_phase_rms"),
    (("mains",), None, ("tn", "tt", "it"), ("rectified_dc",), _CALCULATION_PURPOSES,
     "pre_rectifier_ac_rms"),
    (("mains",), None, ("tn", "tt", "it"), ("series_rectifier_bridges",), ("impulse",),
     "pre_rectifier_ac_rms"),
    (("mains",), None, None, ("isolated_secondary",), _CALCULATION_PURPOSES,
     "not_derived_from_mains_supply"),
    (("non_mains",), None, ("unspecified",), ("direct",), _CALCULATION_PURPOSES,
     "phase_to_phase_rms"),
)


def project_system_voltage_resolution(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
) -> tuple[tuple[DecisionRule | GuidanceRule, ...], tuple[SemanticProposal, ...]]:
    """Project the reviewed mains/non-mains system voltage clause into a decision."""

    label = "supply system voltage resolution"
    _require_own_fragment(fragment, identity, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, label)
    _require_shape(fragment, _SYSTEM_VOLTAGE_SHAPE, label)

    rule = DecisionRule(
        id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        inputs=(
            DecisionInput(name="supply_kind", kind="categorical", allowed_values=_SUPPLY_KINDS),
            DecisionInput(
                name="phase_system", kind="categorical", allowed_values=_PHASE_SYSTEMS
            ),
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
                            Matcher(
                                input="galvanic_isolation_present", op="equals", boolean=True
                            ),
                        ),
                        values=(
                            DecisionValue(name="source_requirement", categorical=own),
                            DecisionValue(
                                name="transferred_requirement", categorical=transferred
                            ),
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
            DecisionOutput(
                name=name, kind="categorical", allowed_values=_OVERVOLTAGE_CATEGORIES
            )
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
                Matcher(
                    input="downstream_connection_kind", op="equals", values=(connection,)
                ),
            ),
            values=(
                DecisionValue(name="transfer_permitted", boolean=permitted),
                DecisionValue(name="combined_circuit_requirement", categorical=requirement),
                DecisionValue(
                    name="propagates_to_connected_circuits", boolean=propagates
                ),
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


CLAUSE_PROJECTORS = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: project_system_voltage_resolution,
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: project_multiple_source_propagation,
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: project_verified_barrier_transfer,
}

__all__ = [
    "CLAUSE_PROJECTORS",
    "SUPPLY_CLAUSES",
    "project_multiple_source_propagation",
    "project_system_voltage_resolution",
    "project_verified_barrier_transfer",
]
