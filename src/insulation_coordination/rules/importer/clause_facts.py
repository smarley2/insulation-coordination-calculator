"""Reviewed normative statements: the licensed clause as the authority for its own branches.

A statement is authored by a maintainer from the private fragment, never proposed by public code,
and binds a digest of exactly the nodes it cites. No statement text, clause wording or numeric
source content belongs here: only the neutral vocabulary each field draws from.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, NotesText

Obligation = Literal["requirement", "permission"]


class CitedNode(FrozenModel):
    """One fragment node a statement rests on, by identity and content."""

    fragment_id: Identifier
    node_order: int = Field(ge=0)
    node_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class _Fact(FrozenModel):
    statement_index: int = Field(ge=0)
    node_references: tuple[CitedNode, ...] = Field(min_length=1)
    obligation: Obligation


class SystemVoltageFact(_Fact):
    fact_kind: Literal["system_voltage"] = "system_voltage"
    phase_system: Literal[
        "three_phase_it",
        "single_phase_it",
        "rectified_from_mains",
        "series_rectifier_bridges",
        "isolated_secondary",
        "non_mains",
    ]
    earthing: Literal["tn", "tt", "it", "unspecified"]
    #: ``any_purpose`` names a statement that fixes its measure without restricting which
    #: calculation purpose it applies to -- one normative statement, not two, so it needs its
    #: own token rather than being authored as a separate fact per purpose.
    purpose: Literal["impulse", "temporary_overvoltage", "any_purpose"]
    measure: Literal[
        "phase_to_artificial_neutral_rms",
        "phase_to_phase_rms",
        "between_supply_conductors_rms",
        "pre_rectifier_ac_rms",
        "highest_pre_rectifier_ac_rms_at_bridge",
    ]


class PropagationStepFact(_Fact):
    fact_kind: Literal["propagation_step"] = "propagation_step"
    step: Literal["a", "b", "c", "d"]
    evaluated_side: Literal["mains", "non_mains"]
    operation: Literal["reduce_one_level", "resolve_rating", "take_more_severe_rating"]
    rating_source_side: Literal["mains", "non_mains"]


class BarrierTransferFact(_Fact):
    fact_kind: Literal["barrier_transfer"] = "barrier_transfer"
    isolation_present: bool
    combined_circuit_rule: Literal["more_severe_of_both_sides", "side_specific_from_transfer"]


class SpdReductionFact(_Fact):
    """One reduction statement: which category step this supply kind permits, and its floor.

    Carries no device placement. The source states reduction and monitoring in separate
    clauses, and a reduction statement refers to the monitoring one rather than restating it --
    which is what ``monitoring_reference`` names. Placement belongs to
    ``SpdMonitoringFact``, whose clause is the one that distinguishes it.
    """

    fact_kind: Literal["spd_reduction"] = "spd_reduction"
    supply_kind: Literal["mains", "non_mains"]
    source_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    target_ovc: Literal["ovc_i", "ovc_ii", "ovc_iii", "ovc_iv"]
    insulation_class: Literal["functional", "basic", "supplementary", "double", "reinforced"]
    degradable: bool
    monitoring_obligation: Literal["required", "not_required"]
    #: The route whose statements the monitoring obligation defers to, never restated here.
    monitoring_reference: Identifier


class SpdMonitoringFact(_Fact):
    """One monitoring statement, whose obligation turns on placement and on participation.

    Its own normative concern, not a dimension of reduction: the source gates monitoring on
    whether the device is bundled externally or internal to the equipment, and excuses it
    entirely for a device that takes no part in a category reduction.
    """

    fact_kind: Literal["spd_monitoring"] = "spd_monitoring"
    #: Spelled as the rule's own ``device_placement`` vocabulary, because these mean the same
    #: thing. A fact field may diverge from a consumer input where the two really are different
    #: concepts -- Table 2's basis against the curve basis in #53A is the precedent -- but only
    #: with an explicit mapping. Two spellings of one concept and no mapping is just a field
    #: nothing can consume.
    device_placement: Literal["internal_to_pecs", "external_to_pecs"]
    participates_in_reduction: bool
    monitoring_required: bool
    compliance_evidence: Literal["visual_inspection", "monitoring_test", "not_required"]


class HfAttenuationFact(_Fact):
    fact_kind: Literal["hf_attenuation"] = "hf_attenuation"
    dvc_gate: Literal["dvc_as", "dvc_b"]
    #: ``any_evidence`` names a statement that accepts every evidence route its source names,
    #: stated as one disjunction rather than one statement per route -- the same situation
    #: ``any_purpose`` covers for a calculation purpose. Without it a maintainer authoring that
    #: one statement has to pick a single route, and the other routes the source permits then
    #: reach no row at all.
    evidence_kind: Literal["test", "simulation", "calculation", "any_evidence"]
    threshold_reference: Identifier
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
    "HfAttenuationFact",
    "Obligation",
    "PropagationStepFact",
    "SpdMonitoringFact",
    "SpdReductionFact",
    "SupplyFact",
    "SystemVoltageFact",
    "evidence_sha256",
]
