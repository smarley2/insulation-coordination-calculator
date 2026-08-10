from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING, Self
from uuid import UUID

from pydantic import Field, model_validator

from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    DecisiveVoltageClass,
    NetClassType,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.frozen_model import FrozenModel

if TYPE_CHECKING:
    from insulation_coordination.domain.project import NetClass, Project


class GalvanicDomain(FrozenModel):
    id: UUID
    name: str = Field(min_length=1)
    description: str = ""
    is_direct_source_domain: bool = False
    review_state: ReviewState = ReviewState.NEEDS_REVIEW


class GalvanicBarrier(FrozenModel):
    id: UUID
    domain_a_id: UUID
    domain_b_id: UUID
    status: BarrierVerificationStatus
    description: str
    verification_method: VerificationMethod | None = None
    evidence_reference: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _requires_consistent_verification(self) -> Self:
        if self.domain_a_id == self.domain_b_id:
            raise ValueError("A barrier requires two different domains")
        if self.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
            if self.verification_method is None or not (self.evidence_reference or "").strip():
                raise ValueError(
                    "Verified isolation requires a verification method and an evidence reference"
                )
        elif self.verification_method is not None or self.evidence_reference is not None:
            raise ValueError(
                "Only verified isolation may carry a verification method or evidence reference"
            )
        return self

    @property
    def domain_key(self) -> tuple[str, str]:
        """The unordered identity of this barrier's domain pair.

        A-B and B-A are the same barrier. The project validator and any editor must agree on
        that, so this is the one place the ordering rule lives.
        """
        return _unordered_domain_key(self.domain_a_id, self.domain_b_id)


class TopologyCompletion(FrozenModel):
    """What is still unresolved about a project's topology.

    Incomplete topology is a status, not an error - a legacy project with no domains yet, or a
    circuit net still awaiting classification, must keep calculating. This model never raises;
    it only reports what a reviewer still has to look at, in a fixed order.
    """

    nets_needing_review: tuple[UUID, ...] = ()
    circuit_nets_without_domain: tuple[UUID, ...] = ()
    circuit_nets_with_unevaluated_dvc: tuple[UUID, ...] = ()
    domain_pairs_without_barrier: tuple[tuple[UUID, UUID], ...] = ()
    unevaluated_barriers: tuple[UUID, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not (
            self.nets_needing_review
            or self.circuit_nets_without_domain
            or self.circuit_nets_with_unevaluated_dvc
            or self.domain_pairs_without_barrier
            or self.unevaluated_barriers
        )


def circuit_nets(project: Project) -> tuple[NetClass, ...]:
    return tuple(net for net in project.net_classes if net.net_type is NetClassType.CIRCUIT)


def domain_for_net(project: Project, net_id: UUID) -> GalvanicDomain | None:
    net = next((candidate for candidate in project.net_classes if candidate.id == net_id), None)
    if net is None or net.galvanic_domain_id is None:
        return None
    return next(
        (domain for domain in project.galvanic_domains if domain.id == net.galvanic_domain_id),
        None,
    )


def barrier_between(project: Project, a: UUID, b: UUID) -> GalvanicBarrier | None:
    key = _unordered_domain_key(a, b)
    return next(
        (barrier for barrier in project.galvanic_barriers if barrier.domain_key == key), None
    )


def topology_completion(project: Project) -> TopologyCompletion:
    circuits = circuit_nets(project)
    domain_ids = tuple(domain.id for domain in project.galvanic_domains)
    return TopologyCompletion(
        nets_needing_review=tuple(
            net.id
            for net in project.net_classes
            if net.classification_review_state is ReviewState.NEEDS_REVIEW
        ),
        circuit_nets_without_domain=tuple(
            net.id for net in circuits if net.galvanic_domain_id is None
        ),
        circuit_nets_with_unevaluated_dvc=tuple(
            net.id
            for net in circuits
            if net.decisive_voltage_class is DecisiveVoltageClass.NOT_EVALUATED
        ),
        domain_pairs_without_barrier=tuple(
            (left, right)
            for left, right in combinations(domain_ids, 2)
            if barrier_between(project, left, right) is None
        ),
        unevaluated_barriers=tuple(
            barrier.id
            for barrier in project.galvanic_barriers
            if barrier.status is BarrierVerificationStatus.NOT_EVALUATED
        ),
    )


def _unordered_domain_key(a: UUID, b: UUID) -> tuple[str, str]:
    first, second = sorted((str(a), str(b)))
    return (first, second)
