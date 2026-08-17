"""A galvanic topology of any shape, for the supply-stress propagation tests.

Every name, identifier and figure here is invented for this repository; nothing carries an IEC
identity or reproduces any licensed content. The three worked examples in
:mod:`tests.fixtures.topology_examples` remain the realistic ones and are used wherever they
reach the case. This builder exists for the cases they do not: each of them carries two domains
and one barrier, which is enough for a single transfer and not enough for a cycle, a bypassed
barrier, an unevaluated one, or a domain nothing is recorded about.

Identifiers are derived from the caller's own indices, so a test can name the domain, net or
barrier it means without holding a fixture object.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from uuid import UUID

from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    CircuitSourceRelationship,
    ConnectionExposure,
    DecisiveVoltageClass,
    FieldCondition,
    InsulationType,
    NetClassType,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.project.pairs import canonical_pair_key, reconcile_pairs

VERIFIED = BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
NO_ISOLATION = BarrierVerificationStatus.NO_GALVANIC_ISOLATION
UNEVALUATED = BarrierVerificationStatus.NOT_EVALUATED

#: The two non-circuit nets every built project carries, so a circuit-to-surroundings pair and
#: a pair of two non-circuits are always available without naming a domain.
ENCLOSURE = UUID(int=290)
COVER = UUID(int=291)


def domain_id(index: int) -> UUID:
    return UUID(int=100 + index)


def circuit_id(index: int) -> UUID:
    """The circuit net belonging to the domain at ``index``."""

    return UUID(int=200 + index)


def barrier_id(index: int) -> UUID:
    """The barrier at ``index`` of the list the project was built from."""

    return UUID(int=300 + index)


def supply_topology(
    domain_names: Sequence[str],
    barriers: Sequence[tuple[int, int, BarrierVerificationStatus]] = (),
    sources: Mapping[int, CircuitSourceRelationship] | None = None,
) -> Project:
    """One project with a circuit per named domain, an enclosure, and an accessible cover.

    ``barriers`` names domain pairs by index; a pair not named carries no barrier at all,
    which is a different state from one recorded as carrying no isolation. ``sources`` names
    which domains' circuits are externally supplied and defaults to the first being
    mains-connected; every other circuit is internally generated and is therefore an entry
    point for nothing.
    """

    supplied = dict(sources or {0: CircuitSourceRelationship.MAINS_CONNECTED})
    domains = tuple(
        GalvanicDomain(
            id=domain_id(index),
            name=name,
            is_direct_source_domain=index == 0,
            review_state=ReviewState.USER_CONFIRMED,
        )
        for index, name in enumerate(domain_names)
    )
    circuits = tuple(
        NetClass(
            id=circuit_id(index),
            name=f"Circuit {domain.name}",
            source_relationship=supplied.get(index, CircuitSourceRelationship.INTERNALLY_GENERATED),
            connection_exposure=ConnectionExposure.INTERNAL_ONLY,
            decisive_voltage_class=DecisiveVoltageClass.DVC_B,
            galvanic_domain_id=domain.id,
            classification_review_state=ReviewState.USER_CONFIRMED,
        )
        for index, domain in enumerate(domains)
    )
    nets = (
        *circuits,
        _non_circuit(ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
        _non_circuit(COVER, "Cover", NetClassType.ACCESSIBLE_INSULATING_SURFACE),
    )
    return Project(
        id=UUID(int=9),
        metadata=ProjectMetadata(title="Supply topology example"),
        application_version="test",
        defaults=ProjectDefaults(
            insulation_type=InsulationType.BASIC,
            field_condition=FieldCondition.INHOMOGENEOUS,
            altitude_m=Decimal(0),
            pollution_degree=2,
        ),
        net_classes=nets,
        pairs=reconcile_pairs(nets, ()),
        galvanic_domains=domains,
        galvanic_barriers=tuple(
            _barrier(index, domains[left], domains[right], status)
            for index, (left, right, status) in enumerate(barriers)
        ),
    )


def pair_between(project: Project, first: UUID, second: UUID) -> PairCase:
    key = canonical_pair_key(first, second)
    return next(pair for pair in project.pairs if pair.key == key)


def _non_circuit(net_id: UUID, name: str, net_type: NetClassType) -> NetClass:
    return NetClass(
        id=net_id,
        name=name,
        net_type=net_type,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def _barrier(
    index: int,
    left: GalvanicDomain,
    right: GalvanicDomain,
    status: BarrierVerificationStatus,
) -> GalvanicBarrier:
    verified = status is VERIFIED
    return GalvanicBarrier(
        id=barrier_id(index),
        domain_a_id=left.id,
        domain_b_id=right.id,
        status=status,
        description=f"{left.name} to {right.name}",
        verification_method=VerificationMethod.TEST if verified else None,
        evidence_reference=f"SYN-BARRIER-{index}" if verified else None,
    )
