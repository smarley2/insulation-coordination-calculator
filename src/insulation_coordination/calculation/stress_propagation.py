"""Carries derived supply stresses across a project's galvanic domains and onto its pairs.

Two questions, and the topology of issue #35 answers the first of them entirely: this module
reads ``domain_for_net``, ``barrier_between`` and ``topology_completion`` and derives no
topology of its own.

*Which stress reaches which domain?* A supply enters at the domains whose nets declare it as
their external source. Domains a barrier records **no galvanic isolation** between are one
electrical set and share the highest stress entering any of them. Across a **verified**
barrier the package's own transfer decision states what requirement carries over - one level,
and only one level. That is the whole of what verified isolation buys: it is not a licence to
attenuate further, and a claim that a barrier does more than the rules give it is an override
with evidence, not a property of the barrier - see
:mod:`~insulation_coordination.calculation.impulse_override`.

A barrier recorded as **not evaluated** is not isolation and is not a connection either. It is
an unknown, and an unknown anywhere a stress could travel from leaves every domain it could
have reached in :attr:`DomainStressState.NOT_EVALUATED` - a state kept carefully apart from
:attr:`DomainStressState.NO_STRESS`, which is the settled answer that nothing reaches a
domain. The first blocks automatic propagation onto the affected pairs and leaves the manual
route available; the second is a result.

*What does a pair make of the stresses either side of it?* Its two net types classify it - see
:class:`~insulation_coordination.domain.supply.PairRelationship` - and the classification is
what decides whether a mains temporary overvoltage is automatically its concern. Only
circuit-to-surroundings insulation receives one. A circuit-to-circuit pair keeps whatever its
own entry states and is otherwise told, with a reason, that none applies; nothing copies the
project's mains figure onto it.

Every value that comes out names where it came from: the configuration, the domain it entered
at, the barriers it crossed in order, and the requirement it arrived as. A value without that
trail is not produced.

No IEC value appears here. The identifiers below are the neutral vocabulary the package
declares for these rules' inputs and outputs.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from itertools import combinations
from typing import Final
from uuid import UUID

from insulation_coordination.calculation.clearance import (
    apply_reinforced_stress_treatment,
    reinforced_stress_floor,
)
from insulation_coordination.calculation.impulse_override import (
    OverrideOutcome,
    PairImpulseOverride,
    resolve_impulse_override,
)
from insulation_coordination.calculation.reinforced_rules import (
    ReinforcedRuleSet,
    ReinforcedTreatmentUnavailable,
)
from insulation_coordination.calculation.supply_rules import SupplyForm, SupplyRuleSet
from insulation_coordination.calculation.supply_stress import select_impulse
from insulation_coordination.domain.enums import (
    Applicability,
    BarrierVerificationStatus,
    CircuitSourceRelationship,
    InsulationType,
    NetClassType,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import NetClass, PairCase, Project
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import DecisionValue
from insulation_coordination.domain.supply import (
    MAINS_SUPPLY_KINDS,
    DerivedSupplyScenario,
    ImpulseOverrideBasis,
    OvervoltageCategory,
    PairRelationship,
    SupplyKind,
    pair_relationship,
)
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    barrier_between,
    domain_for_net,
    topology_completion,
)
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_decision
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_VOLTAGE_UNIT: Final = "V"

#: The trace identifiers of this application's own arithmetic. Not semantic rule ids: taking
#: the worst of several stresses that reach one place is bookkeeping, not a reading of any
#: clause, and labelling it with a package identifier would credit the package with a decision
#: it did not make.
PROPAGATION_TRACE_ID: Final = "supply.domain_propagation"
PAIR_TRACE_ID: Final = "supply.pair_stress"
#: The comparison of two figures this resolution already holds. Not a semantic rule id for the
#: same reason as the two above: the package states the floor's clause in reviewed text and
#: projects it into no row, so there is no decision to credit with the answer.
REINFORCED_FLOOR_TRACE_ID: Final = "supply.reinforced_reduction_floor"

#: Warning codes a caller can group on without matching a message.
UNATTACHED_SCENARIO_WARNING: Final = "supply_scenario_reaches_no_domain"
UNRESOLVED_TOPOLOGY_WARNING: Final = "supply_topology_unresolved"
TRANSFER_UNSTATED_WARNING: Final = "supply_transfer_unstated"
CONNECTION_UNSTATED_WARNING: Final = "supply_connection_unstated"
REDUNDANT_BARRIER_WARNING: Final = "supply_barrier_bypassed"
TOV_ENTRY_CONTRADICTS_WARNING: Final = "supply_pair_tov_entry_contradicts_derivation"
TREATMENT_UNAVAILABLE_WARNING: Final = "supply_insulation_treatment_unavailable"
REINFORCED_FLOOR_WARNING: Final = "supply_reinforced_reduction_floor_applied"
REINFORCED_FLOOR_UNRESOLVED_WARNING: Final = "supply_reinforced_reduction_floor_unresolved"

#: This application's overvoltage categories in the package's own words, and back again.
_RULE_CATEGORIES: Final[Mapping[OvervoltageCategory, str]] = {
    OvervoltageCategory.I: "ovc_i",
    OvervoltageCategory.II: "ovc_ii",
    OvervoltageCategory.III: "ovc_iii",
    OvervoltageCategory.IV: "ovc_iv",
}
_CATEGORY_BY_RULE: Final[Mapping[str, OvervoltageCategory]] = {
    name: category for category, name in _RULE_CATEGORIES.items()
}

#: Which external source relationship each supply kind enters a project through. A circuit
#: generated inside the equipment is never an entry: it is what receives.
_ENTRY_RELATIONSHIPS: Final[Mapping[bool, CircuitSourceRelationship]] = {
    True: CircuitSourceRelationship.MAINS_CONNECTED,
    False: CircuitSourceRelationship.NON_MAINS_EXTERNAL,
}


class DomainStressState(StrEnum):
    """How one galvanic domain came by the impulse stress it carries, if any."""

    #: A supply enters this domain, or one electrically connected to it.
    SUPPLIED = "supplied"
    #: No supply enters, and stress arrives only across verified isolation.
    TRANSFERRED = "transferred"
    #: Evaluated, and nothing reaches it. A result, not a gap.
    NO_STRESS = "no_stress"
    #: A barrier somewhere a stress could travel from is unevaluated, so what reaches this
    #: domain is unknown. Automatic propagation is blocked for its pairs; nothing about the
    #: manual route is.
    NOT_EVALUATED = "not_evaluated"


class DomainSourceStress(FrozenModel):
    """One derived scenario, at the domain its supply enters the project through."""

    entry_domain_id: UUID
    scenario: DerivedSupplyScenario


class TransferredStress(FrozenModel):
    """One source's stress as it arrives across one route of verified barriers.

    ``barrier_path`` is the barriers crossed in order and ``domain_path`` the domains they
    were crossed into, so the two together are the route: one entry per hop, and the entry
    domain at the head. ``transferred_ovc`` is what the package's transfer decision states the
    requirement became after those hops - never a category this application chose.
    """

    source: DomainSourceStress
    transferred_ovc: OvervoltageCategory
    impulse_v: DecimalValue
    domain_path: tuple[UUID, ...]
    barrier_path: tuple[UUID, ...]
    trace_steps: tuple[TraceStep, ...] = ()


class DomainStress(FrozenModel):
    """What one galvanic domain requires, and everything that explains it."""

    domain_id: UUID
    state: DomainStressState
    #: Every domain sharing this one's electrical set, in project order - itself included.
    #: A set of more than one is a set no barrier records isolation between, and they carry
    #: one answer between them.
    component_domain_ids: tuple[UUID, ...]
    own: tuple[DomainSourceStress, ...] = ()
    own_impulse_v: DecimalValue | None = None
    transferred: tuple[TransferredStress, ...] = ()
    transferred_impulse_v: DecimalValue | None = None
    governing_impulse_v: DecimalValue | None = None
    #: Set when a transfer governs rather than the domain's own supply, so a reader can follow
    #: the winning route without re-comparing the alternatives.
    governing_transfer: TransferredStress | None = None
    unresolved_barrier_ids: tuple[UUID, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()
    warnings: tuple[CalculationWarning, ...] = ()


class DomainStressMap(FrozenModel):
    """Every domain of one project, with the stress that reaches it and why."""

    domains: tuple[DomainStress, ...] = ()
    warnings: tuple[CalculationWarning, ...] = ()

    def for_domain(self, domain_id: UUID) -> DomainStress | None:
        return next((item for item in self.domains if item.domain_id == domain_id), None)


class TemporaryOvervoltageSource(StrEnum):
    """Where a pair's temporary overvoltage came from."""

    DERIVED_MAINS = "derived_mains"
    PAIR_ENTRY = "pair_entry"
    NONE = "none"


class PairTemporaryOvervoltage(FrozenModel):
    """Whether a temporary overvoltage applies to one pair, and on whose authority.

    ``applies`` false always carries a ``reason``: "not applicable" is an answer a reader is
    owed an explanation for, and it is the answer every pair that is not circuit-to-
    surroundings gets unless its own entry states one.
    """

    applies: bool
    source: TemporaryOvervoltageSource
    reason: str
    peak_v: DecimalValue | None = None
    rms_v: DecimalValue | None = None
    source_configuration_id: UUID | None = None
    #: What a mains supply does state for this pair, where the pair's own entry excludes it
    #: anyway. The entry stands - it is a recorded decision with a justification - but the
    #: disagreement is surfaced rather than swallowed.
    contradicted_derived_peak_v: DecimalValue | None = None


class PairSide(FrozenModel):
    """One net of a pair, with the domain stress behind it where it has one."""

    net_id: UUID
    net_type: NetClassType
    domain_id: UUID | None = None
    stress: DomainStress | None = None


class EffectivePairStressResolution(FrozenModel):
    """One pair's impulse and temporary overvoltage, at every stage they pass through.

    The stages are kept apart rather than collapsed because each answers a different question
    a reviewer asks: what the supply itself required, what the pair's own domain had, what
    arrived from elsewhere, what governed before anyone intervened, what a verified override
    made of it, and what the pair's own insulation class asks of that.
    """

    pair_id: UUID
    pair_key: str
    relationship: PairRelationship
    state: DomainStressState
    side_a: PairSide
    side_b: PairSide
    #: The rated impulse of the scenario the governing value originates from, before any
    #: transfer reduced it. Equal to the governing value where no barrier was crossed.
    source_scenario_impulse_v: DecimalValue | None = None
    #: The highest stress the pair's own domains are supplied with directly.
    local_domain_impulse_v: DecimalValue | None = None
    #: The highest stress reaching the pair's domains across verified barriers.
    transferred_impulse_v: DecimalValue | None = None
    #: What governs before any override: the worst of the two sides.
    governing_pre_override_impulse_v: DecimalValue | None = None
    #: What governs after one. Equal to the pre-override value when no override applied. This
    #: is the value the clearance engine is handed, and it is deliberately untreated.
    #:
    #: One thing holds it up: where a reducing means lowers a double or reinforced pair far
    #: enough that its treated figure would sit under the floor 4.4.7.2.3 and 4.4.7.2.4 both
    #: state, this is the deepest reduction whose treated figure still reaches that floor. See
    #: :func:`_floored_reduction`, and the warning it carries.
    verified_effective_impulse_v: DecimalValue | None = None
    #: The same value once the pair's insulation class has been treated. Reported, never
    #: consumed: the engine applies that treatment itself, to the untreated value above, so
    #: this figure exists to be read beside the others and feeding it back to the engine is
    #: exactly what applying the treatment twice would look like.
    insulation_treated_impulse_v: DecimalValue | None = None
    override_outcome: OverrideOutcome | None = None
    temporary_overvoltage: PairTemporaryOvervoltage
    warnings: tuple[CalculationWarning, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()


# --- domain propagation ---------------------------------------------------------------


def propagate_impulse_to_domains(
    project: Project,
    scenarios: tuple[DerivedSupplyScenario, ...],
    rules: SupplyRuleSet,
) -> DomainStressMap:
    """Every domain's impulse requirement, derived from ``scenarios`` and the project topology.

    A project with no galvanic domains gets an empty map: there is nothing to propagate
    through, which is the state every project that predates the topology model is in, and it
    is not an error.
    """

    if not project.galvanic_domains:
        return DomainStressMap()
    graph = _Graph(project, rules)
    sources = _entry_sources(project, scenarios, graph)
    transfers = _transfers(graph, sources, rules)
    return DomainStressMap(
        domains=tuple(
            _domain_stress(graph, domain.id, sources, transfers)
            for domain in project.galvanic_domains
        ),
        warnings=tuple(graph.warnings),
    )


class _Graph:
    """One project's domains as an electrical graph, built only from #35's own lookups."""

    def __init__(self, project: Project, rules: SupplyRuleSet) -> None:
        self.project = project
        self.warnings: list[CalculationWarning] = []
        domain_ids = tuple(domain.id for domain in project.galvanic_domains)
        connections: list[tuple[UUID, UUID]] = []
        verified: list[tuple[UUID, UUID, GalvanicBarrier]] = []
        unresolved: list[tuple[UUID, UUID, GalvanicBarrier]] = []
        for left, right in combinations(domain_ids, 2):
            barrier = barrier_between(project, left, right)
            if barrier is None:
                # Nobody has recorded anything about this pair, which is not a claim that the
                # two are connected. `topology_completion` reports it; nothing crosses it here.
                continue
            if barrier.status is BarrierVerificationStatus.NO_GALVANIC_ISOLATION:
                if self._connects(rules, barrier):
                    connections.append((left, right))
            elif barrier.status is BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION:
                verified.append((left, right, barrier))
            else:
                unresolved.append((left, right, barrier))

        self.components, self.component_of = _components(domain_ids, connections)
        self.transfer_edges: dict[int, list[tuple[int, GalvanicBarrier]]] = {}
        for left, right, barrier in verified:
            first, second = self.component_of[left], self.component_of[right]
            if first == second:
                self.warn(
                    REDUNDANT_BARRIER_WARNING,
                    f"Barrier {barrier.id} records verified isolation between two domains that "
                    "another barrier records no isolation between. Nothing transfers across it; "
                    "the domains are one electrical set.",
                )
                continue
            self.transfer_edges.setdefault(first, []).append((second, barrier))
            self.transfer_edges.setdefault(second, []).append((first, barrier))
        for neighbours in self.transfer_edges.values():
            neighbours.sort(key=lambda edge: (edge[0], str(edge[1].id)))

        self.unresolved_by_domain: dict[UUID, list[UUID]] = {}
        for left, right, barrier in unresolved:
            for domain_id in (left, right):
                self.unresolved_by_domain.setdefault(domain_id, []).append(barrier.id)
        self.tainted = _reachable(
            domain_ids,
            (
                *connections,
                *((left, right) for left, right, _ in verified),
                *((left, right) for left, right, _ in unresolved),
            ),
            seeds=tuple(self.unresolved_by_domain),
        )
        self._report_completion()

    def _connects(self, rules: SupplyRuleSet, barrier: GalvanicBarrier) -> bool:
        """Whether a recorded absence of isolation makes two domains one set.

        Asked of the package rather than assumed, because the package is what states that a
        combined circuit's requirement reaches the circuits connected to it. A package that
        states nothing still combines - that behaviour is this issue's own, not a value read
        off a silent rule - but the silence is reported rather than passed off as an answer.
        """

        rule = rules.verified_barrier_transfer
        try:
            result = evaluate_decision(
                rule,
                {
                    "galvanic_isolation_verified": False,
                    "isolation_evidence_kind": "none",
                    "downstream_connection_kind": "no_isolation",
                },
            )
        except EvaluationError as error:
            self.warn(
                CONNECTION_UNSTATED_WARNING,
                f"The active package could not be asked about barrier {barrier.id}: {error}",
                semantic_rule_id=rule.id,
            )
            return True
        if result.status != "matched":
            self.warn(
                CONNECTION_UNSTATED_WARNING,
                f"The active package states nothing about a circuit connected to a combined "
                f"circuit, so barrier {barrier.id} combines its domains on this issue's own "
                "reading rather than on a stated one.",
                semantic_rule_id=rule.id,
            )
            return True
        if _boolean(result.values, "propagates_to_connected_circuits") is False:
            self.warn(
                CONNECTION_UNSTATED_WARNING,
                f"The active package states that a combined circuit's requirement does not "
                f"reach a circuit connected to it, so nothing crosses barrier {barrier.id}.",
                semantic_rule_id=rule.id,
            )
            return False
        return True

    def _report_completion(self) -> None:
        completion = topology_completion(self.project)
        if completion.unevaluated_barriers:
            self.warn(
                UNRESOLVED_TOPOLOGY_WARNING,
                f"{len(completion.unevaluated_barriers)} barrier(s) are not evaluated. A "
                "barrier that is not evaluated is not isolation, so automatic propagation is "
                "blocked for every domain a stress could have reached through one. Manual "
                "entry is unaffected.",
            )
        if completion.circuit_nets_without_domain:
            self.warn(
                UNRESOLVED_TOPOLOGY_WARNING,
                f"{len(completion.circuit_nets_without_domain)} circuit net(s) belong to no "
                "galvanic domain, so no supply stress can be propagated to them.",
            )

    def warn(self, code: str, message: str, *, semantic_rule_id: str | None = None) -> None:
        self.warnings.append(
            CalculationWarning(code=code, message=message, semantic_rule_id=semantic_rule_id)
        )


def _components(
    domain_ids: tuple[UUID, ...], connections: Sequence[tuple[UUID, UUID]]
) -> tuple[tuple[tuple[UUID, ...], ...], dict[UUID, int]]:
    """The electrical sets of a domain graph, in project order and deterministically.

    Domains are visited in the order the project lists them and each set keeps that order, so
    the same project always produces the same set indices and the same representatives.
    """

    seen: set[UUID] = set()
    components: list[tuple[UUID, ...]] = []
    component_of: dict[UUID, int] = {}
    for domain_id in domain_ids:
        if domain_id in seen:
            continue
        members = _reachable(domain_ids, connections, seeds=(domain_id,))
        ordered = tuple(item for item in domain_ids if item in members)
        seen.update(ordered)
        for member in ordered:
            component_of[member] = len(components)
        components.append(ordered)
    return tuple(components), component_of


def _reachable(
    domain_ids: tuple[UUID, ...],
    edges: Sequence[tuple[UUID, UUID]],
    *,
    seeds: Sequence[UUID],
) -> frozenset[UUID]:
    """Every domain reachable from ``seeds`` over ``edges``, seeds included."""

    adjacency: dict[UUID, list[UUID]] = {domain_id: [] for domain_id in domain_ids}
    for left, right in edges:
        adjacency[left].append(right)
        adjacency[right].append(left)
    found: set[UUID] = set()
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if current in found:
            continue
        found.add(current)
        queue.extend(adjacency.get(current, ()))
    return frozenset(found)


def _entry_sources(
    project: Project,
    scenarios: tuple[DerivedSupplyScenario, ...],
    graph: _Graph,
) -> dict[int, list[DomainSourceStress]]:
    """Which electrical set each scenario supplies, read from the nets' source relationship.

    A scenario whose kind no net declares as its external source reaches nothing, and says so
    rather than being attached to a domain nobody named.
    """

    sources: dict[int, list[DomainSourceStress]] = {}
    for scenario in scenarios:
        wanted = _ENTRY_RELATIONSHIPS[scenario.supply_kind in MAINS_SUPPLY_KINDS]
        attached = False
        claimed: set[int] = set()
        for net in project.net_classes:
            if net.net_type is not NetClassType.CIRCUIT or net.source_relationship is not wanted:
                continue
            domain = domain_for_net(project, net.id)
            if domain is None:
                continue
            component = graph.component_of[domain.id]
            if component in claimed:
                continue
            claimed.add(component)
            attached = True
            sources.setdefault(component, []).append(
                DomainSourceStress(entry_domain_id=domain.id, scenario=scenario)
            )
        if not attached:
            graph.warn(
                UNATTACHED_SCENARIO_WARNING,
                f"No circuit net declares {wanted.value} as its source, so "
                f"{scenario.configuration_name} reaches no galvanic domain and stresses "
                "nothing automatically.",
            )
    return sources


def _transfers(
    graph: _Graph,
    sources: Mapping[int, list[DomainSourceStress]],
    rules: SupplyRuleSet,
) -> dict[int, list[TransferredStress]]:
    """Every stress that reaches an electrical set across verified barriers, by every route.

    Each route is evaluated in full and the worst of them governs, so a set reachable several
    ways is answered by the route that asks most of it rather than by whichever was found
    first. Routes are simple: no set appears twice, which is what bounds the search and what
    makes a cycle resolve rather than ambiguous - a cycle is simply more routes, and the
    comparison settles them.

    ponytail: exhaustive simple-path enumeration, which is factorial on a fully connected
    domain graph. Projects carry a handful of domains and the cost is invisible there. If one
    ever does not, the shortest route dominates as soon as the package guarantees its impulse
    table is monotone in the category - which nothing states today, so it is not assumed here.
    """

    transfers: dict[int, list[TransferredStress]] = {}
    for start, entries in sorted(sources.items()):
        for path, barriers in _simple_routes(graph, start):
            target = path[-1]
            for source in entries:
                arrival = _carry(graph, rules, source, path, barriers)
                if arrival is not None:
                    transfers.setdefault(target, []).append(arrival)
    return transfers


def _simple_routes(
    graph: _Graph, start: int
) -> Iterator[tuple[tuple[int, ...], tuple[GalvanicBarrier, ...]]]:
    """Every simple route out of ``start``, shortest first and deterministic within a length."""

    queue: deque[tuple[tuple[int, ...], tuple[GalvanicBarrier, ...]]] = deque([((start,), ())])
    while queue:
        path, barriers = queue.popleft()
        for neighbour, barrier in graph.transfer_edges.get(path[-1], ()):
            if neighbour in path:
                continue
            extended = ((*path, neighbour), (*barriers, barrier))
            yield extended
            queue.append(extended)


def _carry(
    graph: _Graph,
    rules: SupplyRuleSet,
    source: DomainSourceStress,
    path: tuple[int, ...],
    barriers: tuple[GalvanicBarrier, ...],
) -> TransferredStress | None:
    """One scenario carried along one route, or ``None`` when the package will not carry it."""

    category = source.scenario.source_ovc
    if category is None:
        return None
    for barrier in barriers:
        carried = _transferred_category(rules, source.scenario.supply_kind, category)
        if carried is None:
            graph.warn(
                TRANSFER_UNSTATED_WARNING,
                f"The active package states no transferred requirement for "
                f"{source.scenario.configuration_name} across barrier {barrier.id}, so nothing "
                "is carried past it.",
                semantic_rule_id=rules.multiple_source_propagation.id,
            )
            return None
        category = carried
    outcome = select_impulse(
        rules,
        _supply_form(source.scenario.supply_kind),
        source.scenario.system_voltage_for_impulse_v,
        category,
    )
    if outcome.value is None:
        graph.warn(
            TRANSFER_UNSTATED_WARNING,
            f"{source.scenario.configuration_name} transfers as {category.value} and the "
            f"active package refused that lookup: {outcome.message}",
            semantic_rule_id=outcome.rule_id,
        )
        return None
    entered = tuple(
        _entered_domain(graph, barrier, path[index]) for index, barrier in enumerate(barriers, 1)
    )
    return TransferredStress(
        source=source,
        transferred_ovc=category,
        impulse_v=outcome.value,
        domain_path=(source.entry_domain_id, *entered),
        barrier_path=tuple(barrier.id for barrier in barriers),
        trace_steps=outcome.steps,
    )


def _entered_domain(graph: _Graph, barrier: GalvanicBarrier, component: int) -> UUID:
    """Which side of ``barrier`` lies in ``component``. Always exactly one of the two does."""

    return (
        barrier.domain_a_id
        if graph.component_of[barrier.domain_a_id] == component
        else barrier.domain_b_id
    )


def _transferred_category(
    rules: SupplyRuleSet,
    source_kind: SupplyKind,
    source_category: OvervoltageCategory,
) -> OvervoltageCategory | None:
    """What requirement the package states carries across one verified barrier.

    The rule is asked from the receiving side, which is the side opposite the supply doing the
    transferring, and only its ``transferred_requirement`` is read - what the *other* side's
    category becomes once it has crossed. The rule's declared input set also requires the
    evaluated side's own category, which it uses for the two outputs this function does not
    read; it is mirrored from the source's rather than invented, and nothing read here depends
    on it. Comparing the arrival against what the receiving domain already had is done on
    voltages rather than on that output, because two supplies at the same category need not
    require the same impulse.
    """

    stated = _RULE_CATEGORIES[source_category]
    try:
        result = evaluate_decision(
            rules.multiple_source_propagation,
            {
                "evaluated_side": ("non_mains" if source_kind in MAINS_SUPPLY_KINDS else "mains"),
                "mains_overvoltage_category": stated,
                "non_mains_overvoltage_category": stated,
                "galvanic_isolation_present": True,
            },
        )
    except EvaluationError:
        return None
    if result.status != "matched":
        return None
    carried = _categorical(result.values, "transferred_requirement")
    return _CATEGORY_BY_RULE.get(carried or "")


def _supply_form(kind: SupplyKind) -> SupplyForm:
    """Which of the two parallel lookup axes a supply of this kind is answered on."""

    return "dc" if kind is SupplyKind.NON_MAINS_DC else "ac"


def _domain_stress(
    graph: _Graph,
    domain_id: UUID,
    sources: Mapping[int, list[DomainSourceStress]],
    transfers: Mapping[int, list[TransferredStress]],
) -> DomainStress:
    component = graph.component_of[domain_id]
    own = tuple(sources.get(component, ()))
    arrived = tuple(transfers.get(component, ()))
    own_impulse = max((item.scenario.rated_impulse_v for item in own), default=None)
    best_transfer = min(arrived, key=_transfer_key, default=None)
    transferred_impulse = best_transfer.impulse_v if best_transfer is not None else None

    unresolved = tuple(graph.unresolved_by_domain.get(domain_id, ()))
    if domain_id in graph.tainted:
        state = DomainStressState.NOT_EVALUATED
    elif own:
        state = DomainStressState.SUPPLIED
    elif arrived:
        state = DomainStressState.TRANSFERRED
    else:
        state = DomainStressState.NO_STRESS

    candidates = [value for value in (own_impulse, transferred_impulse) if value is not None]
    governing = max(candidates) if candidates else None
    transfer_wins = transferred_impulse is not None and (
        own_impulse is None or transferred_impulse > own_impulse
    )
    governing_transfer = best_transfer if transfer_wins else None
    return DomainStress(
        domain_id=domain_id,
        state=state,
        component_domain_ids=graph.components[component],
        own=own,
        own_impulse_v=own_impulse,
        transferred=arrived,
        transferred_impulse_v=transferred_impulse,
        governing_impulse_v=governing,
        governing_transfer=governing_transfer,
        unresolved_barrier_ids=unresolved,
        trace_steps=_governing_steps(own_impulse, best_transfer, governing),
    )


def _transfer_key(transfer: TransferredStress) -> tuple[Decimal, int, str]:
    """Sorts worst first, then shortest route, then lowest configuration identifier.

    The last two only ever separate equals, and they separate them the way the governing
    scenario selection already does: on something stable across runs rather than on the order
    the routes happened to be found in.
    """

    return (
        -transfer.impulse_v,
        len(transfer.barrier_path),
        str(transfer.source.scenario.configuration_id),
    )


def _governing_steps(
    own_impulse: Decimal | None,
    best_transfer: TransferredStress | None,
    governing: Decimal | None,
) -> tuple[TraceStep, ...]:
    if governing is None:
        return ()
    parts = []
    if own_impulse is not None:
        parts.append(f"supplied = {own_impulse} {_VOLTAGE_UNIT}")
    if best_transfer is not None:
        route = " -> ".join(str(item) for item in best_transfer.barrier_path)
        parts.append(
            f"transferred as {best_transfer.transferred_ovc.value} across {route} = "
            f"{best_transfer.impulse_v} {_VOLTAGE_UNIT}"
        )
    reason = (
        "the domain's own supply governs"
        if own_impulse == governing
        else "a stress transferred across verified isolation governs"
    )
    return (
        TraceStep(
            semantic_rule_id=PROPAGATION_TRACE_ID,
            operation="max",
            symbolic=r"\max(U_{imp})",
            substituted=", ".join(parts),
            inputs=(),
            source_reference=None,
            output=Quantity(value=governing, unit=_VOLTAGE_UNIT),
            unrounded_value=governing,
            reason=reason,
        ),
    )


# --- pair resolution ------------------------------------------------------------------


def resolve_pair_stresses(
    project: Project,
    pair: PairCase,
    domain_stresses: DomainStressMap,
    rules: SupplyRuleSet,
    *,
    override: PairImpulseOverride | None = None,
    reinforced: ReinforcedRuleSet | None = None,
) -> EffectivePairStressResolution:
    """What one pair requires, at every stage between the supply and the clearance engine.

    ``override`` is supplied by the caller rather than read off the pair, because where a
    verified override is stored is issue #36's persistence task and this resolution is already
    the thing that decides whether one applies. Passing none is the ordinary case and restores
    the derived and propagated value exactly - nothing is copied into a manual field on the
    way out.

    ``reinforced`` is the resolved reinforced treatment, used only to *report* what the pair's
    insulation class makes of its effective impulse. ``None`` is what an installation whose
    package cannot state the treatment gets, and a reinforced pair then reports a warning
    instead of a treated figure. It is never a licence to report an untreated one as treated.
    """

    nets = {net.id: net for net in project.net_classes}
    side_a = _pair_side(project, domain_stresses, nets.get(pair.net_a), pair.net_a)
    side_b = _pair_side(project, domain_stresses, nets.get(pair.net_b), pair.net_b)
    relationship = pair_relationship(side_a.net_type, side_b.net_type)
    state = _pair_state(side_a, side_b)
    warnings: list[CalculationWarning] = []
    steps: list[TraceStep] = []

    stresses = tuple(side.stress for side in (side_a, side_b) if side.stress is not None)
    blocked = state is DomainStressState.NOT_EVALUATED
    if blocked:
        warnings.append(
            CalculationWarning(
                code=UNRESOLVED_TOPOLOGY_WARNING,
                message=(
                    "This pair sits where the topology is unresolved, so no supply stress is "
                    "propagated to it automatically. Its manual entries are unaffected."
                ),
            )
        )
    worst = _worst_of_both_sides(() if blocked else stresses)
    governing = worst("governing_impulse_v")
    local = worst("own_impulse_v")
    transferred = worst("transferred_impulse_v")
    origin = None if blocked else _origin_impulse(stresses, governing)
    if governing is not None:
        steps.append(
            TraceStep(
                semantic_rule_id=PAIR_TRACE_ID,
                operation="max",
                symbolic=r"\max(U_{imp})",
                substituted=", ".join(
                    f"{item.domain_id} = {item.governing_impulse_v} {_VOLTAGE_UNIT}"
                    for item in stresses
                    if item.governing_impulse_v is not None
                ),
                inputs=(),
                source_reference=None,
                output=Quantity(value=governing, unit=_VOLTAGE_UNIT),
                unrounded_value=governing,
                reason="the worse of the two sides governs the insulation between them",
            )
        )

    insulation = resolve_effective_case(project.defaults, pair).insulation_type.value
    outcome = _apply_override(project, pair, override, rules, stresses, governing, insulation)
    if outcome is not None:
        warnings.extend(outcome.warnings)
        steps.extend(outcome.trace_steps)
    effective = (
        outcome.effective_impulse_v if outcome is not None and outcome.applied else governing
    )
    effective, floor_step, floor_warning = _floored_reduction(
        governing, effective, outcome, insulation, reinforced
    )
    if floor_step is not None:
        steps.append(floor_step)
    if floor_warning is not None:
        warnings.append(floor_warning)
    treated, treatment_step, treatment_warning = _insulation_treated(
        effective, insulation, reinforced
    )
    if treatment_step is not None:
        steps.append(treatment_step)
    if treatment_warning is not None:
        warnings.append(treatment_warning)

    temporary = _temporary_overvoltage(pair, relationship, stresses, blocked=blocked)
    if temporary.contradicted_derived_peak_v is not None:
        warnings.append(
            CalculationWarning(code=TOV_ENTRY_CONTRADICTS_WARNING, message=temporary.reason)
        )
    return EffectivePairStressResolution(
        pair_id=pair.id,
        pair_key=pair.key,
        relationship=relationship,
        state=state,
        side_a=side_a,
        side_b=side_b,
        source_scenario_impulse_v=origin,
        local_domain_impulse_v=local,
        transferred_impulse_v=transferred,
        governing_pre_override_impulse_v=governing,
        verified_effective_impulse_v=effective,
        insulation_treated_impulse_v=treated,
        override_outcome=outcome,
        temporary_overvoltage=temporary,
        warnings=tuple(warnings),
        trace_steps=tuple(steps),
    )


def _worst_of_both_sides(
    stresses: tuple[DomainStress, ...],
) -> Callable[[str], Decimal | None]:
    """Reads one stage off both sides of a pair and returns the worse of the two.

    An empty side list answers ``None`` for every stage, which is how a pair whose topology is
    unresolved reports every one of them: not zero, and not a value from a domain whose
    surroundings nobody has evaluated.
    """

    def worst(stage: str) -> Decimal | None:
        values = [value for item in stresses if (value := getattr(item, stage)) is not None]
        return max(values) if values else None

    return worst


def _pair_side(
    project: Project,
    domain_stresses: DomainStressMap,
    net: NetClass | None,
    net_id: UUID,
) -> PairSide:
    if net is None:
        raise ValueError("A pair references a net class the project does not carry")
    if net.net_type is not NetClassType.CIRCUIT:
        return PairSide(net_id=net_id, net_type=net.net_type)
    domain = domain_for_net(project, net_id)
    if domain is None:
        return PairSide(net_id=net_id, net_type=net.net_type)
    return PairSide(
        net_id=net_id,
        net_type=net.net_type,
        domain_id=domain.id,
        stress=domain_stresses.for_domain(domain.id),
    )


def _pair_state(side_a: PairSide, side_b: PairSide) -> DomainStressState:
    """The pair's own state: the least resolved of its two sides.

    A circuit with no domain is as unresolved as a domain behind an unevaluated barrier - in
    both cases nothing can be said about what reaches it - so both answer ``NOT_EVALUATED``
    and both leave the manual route untouched.
    """

    states = []
    for side in (side_a, side_b):
        if side.net_type is not NetClassType.CIRCUIT:
            continue
        if side.stress is None:
            return DomainStressState.NOT_EVALUATED
        states.append(side.stress.state)
    if DomainStressState.NOT_EVALUATED in states:
        return DomainStressState.NOT_EVALUATED
    if DomainStressState.SUPPLIED in states:
        return DomainStressState.SUPPLIED
    if DomainStressState.TRANSFERRED in states:
        return DomainStressState.TRANSFERRED
    return DomainStressState.NO_STRESS


def _origin_impulse(
    stresses: tuple[DomainStress, ...], governing: Decimal | None
) -> Decimal | None:
    """The rated impulse of the scenario the governing value came from, before any transfer."""

    if governing is None:
        return None
    for stress in stresses:
        if stress.governing_impulse_v != governing:
            continue
        if stress.governing_transfer is not None:
            return stress.governing_transfer.source.scenario.rated_impulse_v
        return max(
            (item.scenario.rated_impulse_v for item in stress.own),
            default=governing,
        )
    return governing


def _apply_override(
    project: Project,
    pair: PairCase,
    override: PairImpulseOverride | None,
    rules: SupplyRuleSet,
    stresses: tuple[DomainStress, ...],
    governing: Decimal | None,
    insulation: InsulationType | None,
) -> OverrideOutcome | None:
    if override is None:
        return None
    return resolve_impulse_override(
        project,
        pair,
        override,
        rules,
        derived_impulse_v=governing,
        insulation_type=insulation,
        mains_supplied=_is_mains_supplied(stresses),
    )


def _floored_reduction(
    unreduced: Decimal | None,
    effective: Decimal | None,
    outcome: OverrideOutcome | None,
    insulation: InsulationType | None,
    reinforced: ReinforcedRuleSet | None,
) -> tuple[Decimal | None, TraceStep | None, CalculationWarning | None]:
    """The effective impulse a reduced double or reinforced pair may be dimensioned from.

    Both subclauses that let a means of reducing the overvoltage lower an impulse requirement
    close with the same refusal: the requirement for a double or reinforced construction is not
    reduced below what basic insulation would need with that means absent. Basic insulation
    takes the impulse withstand voltage untreated, so the figure the refusal names is the
    pre-override one this resolution already holds - no second lookup states it, and none is
    made.

    *The floor is applied here rather than to the treated figure* because the treated figure is
    reported and the untreated one is dimensioned from. The clearance engine is handed the
    value below and applies the treatment itself, so a floor expressed only on what this module
    reports would leave the delivered spacing under it. What goes back is the deepest reduction
    whose treatment still reaches the floor, read through the same seam the forward treatment
    goes through, so the reported figure and the dimensioned one stay one figure.

    Nothing else is floored. The permission the refusal belongs to is the one a limiting device
    carries, and the other bases a reduction can rest on are separate permissions with separate
    clauses; and the refusal is about a stronger construction, so a functional, basic or
    supplementary pair keeps its reduction whole.
    """

    if (
        effective is None
        or unreduced is None
        or insulation is not InsulationType.REINFORCED
        or outcome is None
        or not outcome.applied
        or outcome.override.basis is not ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER
        or effective >= unreduced
    ):
        return effective, None, None
    location = outcome.override.affected_location
    try:
        deepest = reinforced_stress_floor(
            unreduced,
            kind=insulation,
            stress_field="impulse_v",
            reinforced=reinforced,
        )
    except ReinforcedTreatmentUnavailable as error:
        return (
            effective,
            None,
            CalculationWarning(
                code=REINFORCED_FLOOR_UNRESOLVED_WARNING,
                message=(
                    f"This pair is a reinforced one carrying a reduction at {location!r}, and "
                    f"4.4.7.2.3 and 4.4.7.2.4 hold its requirement at or above the {unreduced} "
                    f"{_VOLTAGE_UNIT} basic insulation would need with that reducing means "
                    f"absent. The active package cannot say which reduced stress carries that "
                    f"floor: {error}. The recorded reduction stands and this pair needs review."
                ),
                semantic_rule_id=ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
            ),
        )
    if effective >= deepest:
        return effective, None, None
    step = TraceStep(
        semantic_rule_id=REINFORCED_FLOOR_TRACE_ID,
        operation="reinforced_reduction_floor",
        symbolic=r"U_{imp}=\max(U_{imp}(reduced), U_{imp}(floor))",
        substituted=f"{effective} {_VOLTAGE_UNIT} -> {deepest} {_VOLTAGE_UNIT}",
        inputs=(Quantity(value=effective, unit=_VOLTAGE_UNIT),),
        source_reference=None,
        output=Quantity(value=deepest, unit=_VOLTAGE_UNIT),
        unrounded_value=deepest,
        reason=(
            "a reduction may not take a double or reinforced requirement below what basic "
            "insulation would need with the reducing means absent"
        ),
    )
    warning = CalculationWarning(
        code=REINFORCED_FLOOR_WARNING,
        message=(
            f"The reduction recorded at {location!r} takes this reinforced pair to {effective} "
            f"{_VOLTAGE_UNIT}, and the treated figure that follows sits below the {unreduced} "
            f"{_VOLTAGE_UNIT} basic insulation would need with that reducing means absent. "
            f"4.4.7.2.3 and 4.4.7.2.4 both refuse that, so this pair is dimensioned from "
            f"{deepest} {_VOLTAGE_UNIT} - the deepest reduction whose treated figure still "
            f"reaches {unreduced} {_VOLTAGE_UNIT}. The reduction those subclauses permit is one "
            "overvoltage-category step, and it is offered to basic and supplementary insulation."
        ),
        semantic_rule_id=ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
    )
    return deepest, step, warning


def _insulation_treated(
    effective_impulse: Decimal | None,
    insulation: InsulationType | None,
    reinforced: ReinforcedRuleSet | None,
) -> tuple[Decimal | None, TraceStep | None, CalculationWarning | None]:
    """What the pair's insulation class makes of the effective impulse, for a reader.

    The treatment itself belongs to the clearance engine and is applied there, once, to the
    untreated value this resolution hands over. Reproducing it here through the engine's own
    function rather than restating the arithmetic is what keeps the reported figure and the
    dimensioned one from drifting apart, and a class that treats nothing simply reports the
    value unchanged with no step to explain.

    Every refusal the adapter can raise arrives here as one warning and no figure: a package
    that states no treatment, a value the requirement axis does not carry, and a value at the
    top of it. This stage only *reports* the treated stress, so it says it cannot rather than
    aborting the resolution - the same pair's clearance calculation blocks on its own.
    """

    if effective_impulse is None or insulation is None:
        return None, None, None
    try:
        treated, step = apply_reinforced_stress_treatment(
            effective_impulse,
            kind=insulation,
            stress_field="impulse_v",
            reinforced=reinforced,
        )
    except ReinforcedTreatmentUnavailable as error:
        return (
            None,
            None,
            CalculationWarning(code=TREATMENT_UNAVAILABLE_WARNING, message=str(error)),
        )
    return treated, step, None


def _is_mains_supplied(stresses: tuple[DomainStress, ...]) -> bool:
    """Whether any supply reaching either side of the pair is a mains supply.

    It selects which of the two reduction routes a limiter's monitoring is asked of, and a
    transferred mains supply is still a mains supply for that question.
    """

    return any(
        source.scenario.supply_kind in MAINS_SUPPLY_KINDS
        for stress in stresses
        for source in (*stress.own, *(item.source for item in stress.transferred))
    )


def _temporary_overvoltage(
    pair: PairCase,
    relationship: PairRelationship,
    stresses: tuple[DomainStress, ...],
    *,
    blocked: bool,
) -> PairTemporaryOvervoltage:
    """Whether a temporary overvoltage applies to this pair, and where it came from.

    A mains temporary overvoltage is automatically the concern of circuit-to-surroundings
    insulation and of nothing else. It is taken from the mains supplies the pair's own domains
    are *supplied* by, not from ones that reach them across isolation: the package states a
    one-level transfer for the impulse requirement and states nothing that carries a temporary
    overvoltage across a barrier, so nothing here carries one.

    A circuit-to-circuit pair keeps whatever its own entry states and otherwise gets a reason.
    No approved rule of the active package requires a circuit-to-circuit temporary overvoltage
    to be derived from the governing circuit relationship, so none is derived; if one is ever
    added, this is the branch it belongs in.
    """

    entry = pair.voltages.temporary_overvoltage_peak_v
    stated = entry.value if entry.applicability is Applicability.APPLICABLE else None
    derived = None
    if relationship is PairRelationship.CIRCUIT_TO_SURROUNDINGS and not blocked:
        derived = max(
            (
                source
                for stress in stresses
                for source in stress.own
                if source.scenario.supply_kind in MAINS_SUPPLY_KINDS
                and source.scenario.temporary_overvoltage_peak_v is not None
            ),
            key=lambda source: source.scenario.temporary_overvoltage_peak_v or Decimal(0),
            default=None,
        )

    if entry.applicability is Applicability.NOT_APPLICABLE:
        reason = entry.justification or "This pair records no temporary overvoltage."
        if derived is not None:
            reason = (
                f"{reason} The mains supply {derived.scenario.configuration_name} does state a "
                "temporary overvoltage for insulation of this kind; the recorded exclusion is "
                "what stands."
            )
            return PairTemporaryOvervoltage(
                applies=False,
                source=TemporaryOvervoltageSource.NONE,
                reason=reason,
                contradicted_derived_peak_v=derived.scenario.temporary_overvoltage_peak_v,
            )
        return PairTemporaryOvervoltage(
            applies=False, source=TemporaryOvervoltageSource.NONE, reason=reason
        )

    derived_peak = derived.scenario.temporary_overvoltage_peak_v if derived is not None else None
    if derived_peak is not None and (stated is None or derived_peak >= stated):
        assert derived is not None
        return PairTemporaryOvervoltage(
            applies=True,
            source=TemporaryOvervoltageSource.DERIVED_MAINS,
            reason=(
                f"{derived.scenario.configuration_name} supplies a circuit of this pair, and a "
                "mains temporary overvoltage applies to circuit-to-surroundings insulation."
            ),
            peak_v=derived_peak,
            rms_v=derived.scenario.temporary_overvoltage_rms_v,
            source_configuration_id=derived.scenario.configuration_id,
        )
    if stated is not None:
        return PairTemporaryOvervoltage(
            applies=True,
            source=TemporaryOvervoltageSource.PAIR_ENTRY,
            reason="This pair states its own temporary overvoltage.",
            peak_v=stated,
        )
    return PairTemporaryOvervoltage(
        applies=False,
        source=TemporaryOvervoltageSource.NONE,
        reason=_no_temporary_overvoltage_reason(relationship, blocked=blocked),
    )


def _no_temporary_overvoltage_reason(relationship: PairRelationship, *, blocked: bool) -> str:
    if blocked:
        return (
            "The topology around this pair is unresolved, so no supply's temporary "
            "overvoltage is applied to it automatically."
        )
    if relationship is PairRelationship.CIRCUIT_TO_CIRCUIT:
        return (
            "A mains temporary overvoltage is not automatically applied between two circuits, "
            "and no rule of the active package requires one to be derived for this pair."
        )
    if relationship is PairRelationship.NON_CIRCUIT_REFERENCE:
        return "Neither side of this pair is a circuit, so no supply temporary overvoltage applies."
    return (
        "No enabled mains supply reaches a circuit of this pair, so there is no mains "
        "temporary overvoltage to apply."
    )


def _boolean(values: tuple[DecisionValue, ...], name: str) -> bool | None:
    return next((value.boolean for value in values if value.name == name), None)


def _categorical(values: tuple[DecisionValue, ...], name: str) -> str | None:
    return next((value.categorical for value in values if value.name == name), None)


__all__ = [
    "CONNECTION_UNSTATED_WARNING",
    "PAIR_TRACE_ID",
    "PROPAGATION_TRACE_ID",
    "REDUNDANT_BARRIER_WARNING",
    "TOV_ENTRY_CONTRADICTS_WARNING",
    "TRANSFER_UNSTATED_WARNING",
    "TREATMENT_UNAVAILABLE_WARNING",
    "UNATTACHED_SCENARIO_WARNING",
    "UNRESOLVED_TOPOLOGY_WARNING",
    "DomainSourceStress",
    "DomainStress",
    "DomainStressMap",
    "DomainStressState",
    "EffectivePairStressResolution",
    "PairSide",
    "PairTemporaryOvervoltage",
    "TemporaryOvervoltageSource",
    "TransferredStress",
    "propagate_impulse_to_domains",
    "resolve_pair_stresses",
]
