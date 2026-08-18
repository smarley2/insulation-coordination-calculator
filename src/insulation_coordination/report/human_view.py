"""Human-facing projection of the validated report snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from insulation_coordination.calculation.stress_propagation import (
    DomainStress,
    EffectivePairStressResolution,
    TemporaryOvervoltageSource,
)
from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.domain.supply import DerivedSupplyScenario
from insulation_coordination.domain.topology import GalvanicBarrier
from insulation_coordination.report.model import (
    MatrixRow,
    PairCalculationReport,
    ReportModel,
    ReportStress,
    ReportSupply,
)


@dataclass(frozen=True)
class HumanValue:
    name: str
    value: str
    provenance: str = ""


@dataclass(frozen=True)
class HumanMatrix:
    name: str
    unit: str
    headers: tuple[str, ...]
    values: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class HumanCandidate:
    name: str
    stress: str
    distance: str
    reason: str
    source_reference: SourceReference | None


@dataclass(frozen=True)
class HumanAdvisory:
    code: str
    message: str
    source_reference: SourceReference | None


@dataclass(frozen=True)
class HumanRule:
    description: str
    source_reference: SourceReference | None


@dataclass(frozen=True)
class HumanPairCalculation:
    pair_label: str
    effective_conditions: tuple[HumanValue, ...]
    stresses: tuple[ReportStress, ...]
    clearance_candidates: tuple[HumanCandidate, ...]
    creepage_candidates: tuple[HumanCandidate, ...]
    clearance_explanation: str
    creepage_explanation: str
    pre_altitude_clearance: str
    altitude_correction_applied: bool
    clearance: str
    creepage: str
    inner_clearance: str
    inner_creepage: str
    warnings: tuple[HumanAdvisory, ...]
    verification_requirements: tuple[HumanAdvisory, ...]


@dataclass(frozen=True)
class HumanPairSupply:
    """One supply derivation, and the pairs it is the derivation of.

    Pairs sharing a calculation group already share every result value, and they usually
    share this too - so one block names all of them. Where two of them differ, in the
    relationship that decides whether a mains temporary overvoltage applies for instance,
    they get a block each rather than the first pair's route standing in for the second's.
    """

    pair_labels: tuple[str, ...]
    stages: tuple[HumanValue, ...]
    evidence: tuple[HumanValue, ...]


@dataclass(frozen=True)
class HumanGroup:
    name: str
    pair_labels: tuple[str, ...]
    calculations: tuple[HumanPairCalculation, ...]
    rules: tuple[HumanRule, ...]
    supply: tuple[HumanPairSupply, ...] = ()


@dataclass(frozen=True)
class HumanNetClassification:
    name: str
    net_type: str
    source_relationship: str
    connection_exposure: str
    decisive_voltage_class: str
    galvanic_domain: str
    review_state: str


@dataclass(frozen=True)
class HumanGalvanicDomain:
    name: str
    description: str
    is_direct_source_domain: bool
    review_state: str


@dataclass(frozen=True)
class HumanGalvanicBarrier:
    domain_a: str
    domain_b: str
    status: str
    verification_method: str
    evidence_reference: str
    notes: str


@dataclass(frozen=True)
class HumanTopologyStatus:
    """What is still unresolved, by name rather than by ID, plus domain review state.

    ``is_complete`` mirrors :func:`topology_completion`'s own field exactly - it never
    looks at ``GalvanicDomain.review_state``. ``fully_resolved`` adds that missing axis so
    a domain still awaiting review is never reported as nothing left to look at.
    """

    is_complete: bool
    nets_needing_review: tuple[str, ...]
    circuit_nets_without_domain: tuple[str, ...]
    circuit_nets_with_unevaluated_dvc: tuple[str, ...]
    domain_pairs_without_barrier: tuple[str, ...]
    unevaluated_barriers: tuple[str, ...]
    domains_needing_review: tuple[str, ...]

    @property
    def fully_resolved(self) -> bool:
        return self.is_complete and not self.domains_needing_review


@dataclass(frozen=True)
class HumanSupplyConfiguration:
    """One declared supply arrangement, as it was entered."""

    name: str
    status: str
    supply_kind: str
    nominal_voltage: str
    phase_system: str
    earthing_arrangement: str
    overvoltage_category: str
    input_topology: str
    notes: str


@dataclass(frozen=True)
class HumanSupplyScenario:
    """One arrangement's derived result, with the system voltages it resolved to."""

    name: str
    system_voltage_impulse: str
    system_voltage_tov: str
    overvoltage_category: str
    rated_impulse: str
    temporary_overvoltage_rms: str
    temporary_overvoltage_peak: str
    governs: str


@dataclass(frozen=True)
class HumanBlockedSupplyScenario:
    """An enabled arrangement that produced no scenario, and every reason it did not."""

    name: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class HumanSupplyDomain:
    """One galvanic domain of the graph the stresses were carried through."""

    name: str
    state: str
    electrical_set: str
    own_impulse: str
    transferred_impulse: str
    governing_impulse: str
    route: str
    unresolved_barriers: str


@dataclass(frozen=True)
class HumanSupplyView:
    """Everything the project's supply derivation determined, before any pair reads it."""

    configurations: tuple[HumanSupplyConfiguration, ...]
    scenarios: tuple[HumanSupplyScenario, ...]
    scenario_rules: tuple[HumanValue, ...]
    blocked: tuple[HumanBlockedSupplyScenario, ...]
    domains: tuple[HumanSupplyDomain, ...]
    governing: tuple[HumanValue, ...]
    altitude_statement: str


@dataclass(frozen=True)
class HumanReportView:
    common_values: tuple[HumanValue, ...]
    comparison_matrices: tuple[HumanMatrix, ...]
    groups: tuple[HumanGroup, ...]
    advisories: tuple[HumanAdvisory, ...]
    verification_requirements: tuple[HumanAdvisory, ...]
    net_classifications: tuple[HumanNetClassification, ...]
    galvanic_domains: tuple[HumanGalvanicDomain, ...]
    galvanic_barriers: tuple[HumanGalvanicBarrier, ...]
    topology_status: HumanTopologyStatus
    supply: HumanSupplyView | None
    rules: object


def build_human_report_view(model: ReportModel) -> HumanReportView:
    """Derive display-only report data without weakening report validation."""
    headers = tuple(net.name for net in model.net_classes)
    excluded = frozenset(frozenset((pair.net_a, pair.net_b)) for pair in model.excluded_pairs)
    common_values: list[HumanValue] = []
    matrices: list[HumanMatrix] = []
    default_specs: tuple[tuple[str, str, str, Callable[[MatrixRow], str]], ...] = (
        ("Frequency", "Hz", "frequency", lambda row: _effective_text(row.frequency.value, "Hz")),
        ("Impulse", "V", "impulse", lambda row: _effective_text(row.impulse.value, "V")),
        ("Insulation type", "", "insulation", lambda row: row.insulation_type or "—"),
        ("Field condition", "", "field", lambda row: row.field_condition or "—"),
        (
            "Electrode radius",
            "mm",
            "radius",
            lambda row: _effective_text(row.electrode_radius_mm, "mm"),
        ),
        ("Altitude", "m", "altitude", lambda row: _effective_text(row.altitude_m, "m")),
        (
            "Pollution degree",
            "",
            "pollution",
            lambda row: _effective_text(row.pollution_degree, ""),
        ),
        ("Construction", "", "construction", lambda row: row.construction_type or "—"),
        (
            "CTI/material group",
            "",
            "cti",
            lambda row: row.cti_or_material_group or "—",
        ),
        (
            "Required clearance",
            "mm",
            "clearance",
            lambda row: _effective_text(row.clearance_mm, "mm"),
        ),
        ("Required creepage", "mm", "creepage", lambda row: _effective_text(row.creepage_mm, "mm")),
        (
            "Required inner-layer clearance",
            "mm",
            "inner clearance",
            lambda row: _effective_text(row.inner_clearance_mm, "mm"),
        ),
        (
            "Required inner-layer creepage",
            "mm",
            "inner creepage",
            lambda row: _effective_text(row.inner_creepage_mm, "mm"),
        ),
    )
    for name, unit, _key, value_getter in default_specs:
        values = tuple(value_getter(row) for row in model.matrix_rows)
        if not values:
            continue
        if len(set(values)) == 1:
            common_values.append(HumanValue(name=name, value=values[0], provenance="common"))
        else:
            matrices.append(
                _matrix_for(name, unit, headers, model.matrix_rows, value_getter, excluded)
            )

    voltage_specs = (
        ("Long-term RMS voltage", "V", "long-term RMS"),
        ("Steady-state peak voltage", "V", "steady-state peak"),
        ("Recurring peak voltage", "V", "recurring peak"),
        ("Temporary overvoltage peak voltage", "V", "temporary overvoltage peak"),
    )
    for name, unit, stress_name in voltage_specs:
        matrices.append(
            _matrix_for(
                name,
                unit,
                headers,
                model.matrix_rows,
                _stress_getter(stress_name),
                excluded,
            )
        )

    # Four topology sections name the same domains, so the lookup is built once here.
    domain_names = {domain.id: domain.name for domain in model.galvanic_domains}

    row_by_id = {row.pair_id: row for row in model.matrix_rows}
    report_groups: list[HumanGroup] = []
    for group_index, group in enumerate(model.groups, start=1):
        calculations = tuple(
            _human_calculation(row_by_id[calculation.pair_id], calculation)
            for calculation in group.calculations
        )
        report_groups.append(
            HumanGroup(
                name=f"Group {group_index}",
                pair_labels=tuple(calculation.pair_label for calculation in calculations),
                calculations=calculations,
                rules=_human_rules(group.calculations),
                supply=_human_group_supply(
                    group.calculations,
                    tuple(calculation.pair_label for calculation in calculations),
                    model,
                    domain_names,
                ),
            )
        )

    warnings = _deduplicate_advisories(model.warnings)
    verification_requirements = _deduplicate_advisories(model.verification_requirements)
    warning_codes = {item.code for item in warnings}
    verification_requirements = tuple(
        item for item in verification_requirements if item.code not in warning_codes
    )
    return HumanReportView(
        common_values=tuple(common_values),
        comparison_matrices=tuple(matrices),
        groups=tuple(report_groups),
        advisories=warnings,
        verification_requirements=verification_requirements,
        net_classifications=_human_net_classifications(model, domain_names),
        galvanic_domains=_human_galvanic_domains(model),
        galvanic_barriers=_human_galvanic_barriers(model, domain_names),
        topology_status=_human_topology_status(model, domain_names),
        supply=_human_supply(model, domain_names),
        rules=model.rules,
    )


def _human_net_classifications(
    model: ReportModel, domain_names: dict[UUID, str]
) -> tuple[HumanNetClassification, ...]:
    return tuple(
        HumanNetClassification(
            name=net.name,
            net_type=_value_text(net.net_type),
            source_relationship=_value_text(net.source_relationship),
            connection_exposure=_value_text(net.connection_exposure),
            decisive_voltage_class=_value_text(net.decisive_voltage_class),
            galvanic_domain=(
                "—"
                if net.galvanic_domain_id is None
                else domain_names.get(net.galvanic_domain_id, "—")
            ),
            review_state=_value_text(net.classification_review_state),
        )
        for net in model.net_classes
    )


def _human_galvanic_domains(model: ReportModel) -> tuple[HumanGalvanicDomain, ...]:
    return tuple(
        HumanGalvanicDomain(
            name=domain.name,
            description=domain.description or "—",
            is_direct_source_domain=domain.is_direct_source_domain,
            review_state=_value_text(domain.review_state),
        )
        for domain in model.galvanic_domains
    )


def _human_galvanic_barriers(
    model: ReportModel, domain_names: dict[UUID, str]
) -> tuple[HumanGalvanicBarrier, ...]:
    return tuple(
        HumanGalvanicBarrier(
            domain_a=domain_names.get(barrier.domain_a_id, "?"),
            domain_b=domain_names.get(barrier.domain_b_id, "?"),
            status=_value_text(barrier.status),
            verification_method=_value_text(barrier.verification_method),
            evidence_reference=barrier.evidence_reference or "—",
            notes=barrier.notes or "—",
        )
        for barrier in model.galvanic_barriers
    )


def _domain_pair_label(left: UUID, right: UUID, domain_names: dict[UUID, str]) -> str:
    return f"{domain_names.get(left, '?')} ↔ {domain_names.get(right, '?')}"


def _barrier_label(
    barrier_id: UUID,
    barriers: tuple[GalvanicBarrier, ...],
    domain_names: dict[UUID, str],
) -> str:
    barrier = next((item for item in barriers if item.id == barrier_id), None)
    if barrier is None:
        return str(barrier_id)
    return _domain_pair_label(barrier.domain_a_id, barrier.domain_b_id, domain_names)


def _human_topology_status(
    model: ReportModel, domain_names: dict[UUID, str]
) -> HumanTopologyStatus:
    net_names = {net.id: net.name for net in model.net_classes}
    topology = model.topology
    return HumanTopologyStatus(
        is_complete=topology.is_complete,
        nets_needing_review=tuple(
            net_names.get(net_id, str(net_id)) for net_id in topology.nets_needing_review
        ),
        circuit_nets_without_domain=tuple(
            net_names.get(net_id, str(net_id)) for net_id in topology.circuit_nets_without_domain
        ),
        circuit_nets_with_unevaluated_dvc=tuple(
            net_names.get(net_id, str(net_id))
            for net_id in topology.circuit_nets_with_unevaluated_dvc
        ),
        domain_pairs_without_barrier=tuple(
            _domain_pair_label(left, right, domain_names)
            for left, right in topology.domain_pairs_without_barrier
        ),
        unevaluated_barriers=tuple(
            _barrier_label(barrier_id, model.galvanic_barriers, domain_names)
            for barrier_id in topology.unevaluated_barriers
        ),
        domains_needing_review=tuple(
            domain_names.get(domain_id, str(domain_id))
            for domain_id in model.domains_needing_review
        ),
    )


#: The statement the issue requires the report to make explicitly. Altitude corrects a
#: dimensioned distance once a governing candidate has been chosen; it is never applied to
#: a source voltage, and a reader should not have to infer that from an absence.
ALTITUDE_STATEMENT = (
    "Altitude did not alter any source voltage. The derived impulse withstand voltage and "
    "the derived temporary overvoltage are source stresses; the altitude correction is "
    "applied to a dimensioned distance, after the governing clearance candidate has been "
    "selected, and is reported with that clearance."
)

#: Stated instead when the derivation's own trace says otherwise. It should be unreachable;
#: printing a claim the trace contradicts would be worse than printing this.
ALTITUDE_CONTRADICTED_STATEMENT = (
    "An altitude rule was read while the source voltages of this project were derived. "
    "Altitude is not permitted to alter a source voltage, so this result must be explained "
    "before it is relied on."
)


def _human_supply(model: ReportModel, domain_names: dict[UUID, str]) -> HumanSupplyView | None:
    """Project the supply derivation, or ``None`` where the project declares no arrangement."""
    supply = model.supply
    if supply is None and not model.supply_configurations:
        return None
    scenarios = () if supply is None else supply.governing.scenarios
    governed_by = _governed_labels(supply)
    return HumanSupplyView(
        configurations=tuple(
            HumanSupplyConfiguration(
                name=configuration.name,
                status="enabled" if configuration.enabled else "not enabled",
                supply_kind=_value_text(configuration.supply_kind),
                nominal_voltage=_effective_text(configuration.nominal_voltage_v, "V"),
                phase_system=_value_text(configuration.phase_system),
                earthing_arrangement=_value_text(configuration.earthing_arrangement),
                overvoltage_category=_value_text(configuration.overvoltage_category),
                input_topology=_value_text(configuration.input_topology),
                notes=configuration.notes or "—",
            )
            for configuration in model.supply_configurations
        ),
        scenarios=tuple(
            HumanSupplyScenario(
                name=scenario.configuration_name,
                system_voltage_impulse=_effective_text(scenario.system_voltage_for_impulse_v, "V"),
                system_voltage_tov=_effective_text(scenario.system_voltage_for_tov_v, "V"),
                overvoltage_category=_value_text(scenario.source_ovc),
                rated_impulse=_effective_text(scenario.rated_impulse_v, "V"),
                temporary_overvoltage_rms=_effective_text(
                    scenario.temporary_overvoltage_rms_v, "V"
                ),
                temporary_overvoltage_peak=_effective_text(
                    scenario.temporary_overvoltage_peak_v, "V"
                ),
                governs=", ".join(governed_by.get(scenario.configuration_id, ())) or "—",
            )
            for scenario in scenarios
        ),
        scenario_rules=tuple(
            HumanValue(
                name=scenario.configuration_name,
                value=", ".join(scenario.source_rule_ids) or "—",
            )
            for scenario in scenarios
        ),
        blocked=tuple(
            HumanBlockedSupplyScenario(
                name=unresolved.configuration_name,
                reasons=tuple(
                    f"{_value_text(block.code)}: {_sentence(block.message)}"
                    for block in unresolved.blocks
                ),
            )
            for unresolved in (() if supply is None else supply.governing.unresolved)
        ),
        domains=_human_supply_domains(model, domain_names),
        governing=_human_governing(supply),
        altitude_statement=(
            ""
            if supply is None
            else (
                ALTITUDE_CONTRADICTED_STATEMENT
                if supply.altitude_altered_source_voltages
                else ALTITUDE_STATEMENT
            )
        ),
    )


def _governed_labels(supply: ReportSupply | None) -> dict[UUID, tuple[str, ...]]:
    """Which of the three governing stresses each configuration won, by configuration."""
    if supply is None:
        return {}
    governing = supply.governing
    labels: dict[UUID, tuple[str, ...]] = {}
    for label, owner in (
        ("impulse", governing.impulse_configuration_id),
        ("temporary overvoltage peak", governing.tov_configuration_id),
        ("temporary overvoltage RMS", governing.tov_rms_configuration_id),
    ):
        if owner is not None:
            labels[owner] = (*labels.get(owner, ()), label)
    return labels


def _human_governing(supply: ReportSupply | None) -> tuple[HumanValue, ...]:
    """The three governing values, each named with the scenario that produced it.

    They are selected independently, so three different arrangements can appear here.
    """
    if supply is None:
        return ()
    governing = supply.governing
    names = {
        scenario.configuration_id: scenario.configuration_name for scenario in governing.scenarios
    }
    return tuple(
        HumanValue(
            name=label,
            # A governing value and its owner are recorded together or not at all;
            # GoverningSupplyStress validates that, so one check answers for both.
            value=(
                "—"
                if value is None or owner is None
                else f"{_effective_text(value, 'V')} from {names.get(owner, str(owner))}"
            ),
        )
        for label, value, owner in (
            (
                "Governing impulse withstand voltage",
                governing.impulse_v,
                governing.impulse_configuration_id,
            ),
            (
                "Governing temporary overvoltage (peak)",
                governing.tov_peak_v,
                governing.tov_configuration_id,
            ),
            (
                "Governing temporary overvoltage (RMS)",
                governing.tov_rms_v,
                governing.tov_rms_configuration_id,
            ),
        )
    )


def _human_supply_domains(
    model: ReportModel, domain_names: dict[UUID, str]
) -> tuple[HumanSupplyDomain, ...]:
    """The domain graph: what each domain carries, and the route anything transferred took."""
    if model.supply is None:
        return ()
    return tuple(
        HumanSupplyDomain(
            name=domain_names.get(stress.domain_id, str(stress.domain_id)),
            state=_value_text(stress.state),
            electrical_set=", ".join(
                domain_names.get(domain_id, str(domain_id))
                for domain_id in stress.component_domain_ids
            )
            or "—",
            own_impulse=_effective_text(stress.own_impulse_v, "V"),
            transferred_impulse=_effective_text(stress.transferred_impulse_v, "V"),
            governing_impulse=_effective_text(stress.governing_impulse_v, "V"),
            route=_transfer_route(stress, model, domain_names),
            unresolved_barriers=", ".join(
                _barrier_label(barrier_id, model.galvanic_barriers, domain_names)
                for barrier_id in stress.unresolved_barrier_ids
            )
            or "—",
        )
        for stress in model.supply.domain_stresses.domains
    )


def _transfer_route(stress: DomainStress, model: ReportModel, domain_names: dict[UUID, str]) -> str:
    """The domains and barriers the governing stress crossed to arrive, or that none did."""
    transfer = stress.governing_transfer
    if transfer is None:
        return "no barrier crossed"
    hops = " to ".join(
        domain_names.get(domain_id, str(domain_id)) for domain_id in transfer.domain_path
    )
    crossed = ", ".join(
        _barrier_label(barrier_id, model.galvanic_barriers, domain_names)
        for barrier_id in transfer.barrier_path
    )
    return (
        f"{hops} across {crossed}, arriving in overvoltage category "
        f"{_value_text(transfer.transferred_ovc)}, from {transfer.source.scenario.configuration_name}"
    )


def _human_group_supply(
    calculations: tuple[PairCalculationReport, ...],
    pair_labels: tuple[str, ...],
    model: ReportModel,
    domain_names: dict[UUID, str],
) -> tuple[HumanPairSupply, ...]:
    """One block per distinct derivation in the group, naming the pairs it covers."""
    blocks: dict[tuple[tuple[HumanValue, ...], tuple[HumanValue, ...]], list[str]] = {}
    for calculation, label in zip(calculations, pair_labels, strict=True):
        if calculation.supply is None:
            continue
        key = (
            _human_supply_stages(calculation.supply, model, domain_names),
            _human_override_evidence(calculation.supply),
        )
        blocks.setdefault(key, []).append(label)
    return tuple(
        HumanPairSupply(pair_labels=tuple(labels), stages=stages, evidence=evidence)
        for (stages, evidence), labels in blocks.items()
    )


def _human_supply_stages(
    resolution: EffectivePairStressResolution,
    model: ReportModel,
    domain_names: dict[UUID, str],
) -> tuple[HumanValue, ...]:
    """Every stage between the supply and this pair's clearance input, in reading order."""
    return (
        HumanValue("Pair relationship", _value_text(resolution.relationship)),
        HumanValue("Topology state", _value_text(resolution.state)),
        HumanValue("Source scenarios", _source_scenarios(resolution)),
        HumanValue("Propagation path", _pair_route(resolution, model, domain_names)),
        HumanValue(
            "Source scenario impulse",
            _effective_text(resolution.source_scenario_impulse_v, "V"),
        ),
        HumanValue("Local domain impulse", _effective_text(resolution.local_domain_impulse_v, "V")),
        HumanValue("Transferred impulse", _effective_text(resolution.transferred_impulse_v, "V")),
        HumanValue(
            "Governing before override",
            _effective_text(resolution.governing_pre_override_impulse_v, "V"),
        ),
        HumanValue(
            "Verified effective impulse",
            _effective_text(resolution.verified_effective_impulse_v, "V"),
        ),
        HumanValue(
            "Insulation-treated impulse",
            _effective_text(resolution.insulation_treated_impulse_v, "V"),
        ),
        HumanValue("Temporary overvoltage", _pair_temporary_overvoltage(resolution)),
        HumanValue("Rules read", _pair_source_rules(resolution)),
    )


def _source_scenarios(resolution: EffectivePairStressResolution) -> str:
    """Every scenario whose stress reaches either side, entering or arriving."""
    scenarios: dict[UUID, DerivedSupplyScenario] = {}
    for side in (resolution.side_a, resolution.side_b):
        if side.stress is None:
            continue
        for source in (
            *side.stress.own,
            *(transfer.source for transfer in side.stress.transferred),
        ):
            scenarios.setdefault(source.scenario.configuration_id, source.scenario)
    return (
        "; ".join(
            f"{scenario.configuration_name}: {_effective_text(scenario.rated_impulse_v, 'V')}"
            for scenario in scenarios.values()
        )
        or "—"
    )


def _pair_route(
    resolution: EffectivePairStressResolution,
    model: ReportModel,
    domain_names: dict[UUID, str],
) -> str:
    """The route the governing stress took to each side of the pair."""
    routes = [
        f"{domain_names.get(side.stress.domain_id, str(side.stress.domain_id))}: "
        f"{_transfer_route(side.stress, model, domain_names)}"
        for side in (resolution.side_a, resolution.side_b)
        if side.stress is not None
    ]
    return "; ".join(dict.fromkeys(routes)) or "—"


def _pair_temporary_overvoltage(resolution: EffectivePairStressResolution) -> str:
    """Whether one applies, on whose authority, and the reason where it does not."""
    temporary = resolution.temporary_overvoltage
    if not temporary.applies:
        return f"not applicable — {_sentence(temporary.reason)}"
    values = " / ".join(
        f"{_effective_text(value, 'V')} {basis}"
        for value, basis in ((temporary.peak_v, "peak"), (temporary.rms_v, "RMS"))
        if value is not None
    )
    source = (
        "this pair's own entry"
        if temporary.source is TemporaryOvervoltageSource.PAIR_ENTRY
        else "the derived mains supply"
    )
    return f"{values or '—'} from {source} — {_sentence(temporary.reason)}"


def _pair_source_rules(resolution: EffectivePairStressResolution) -> str:
    """Every semantic rule this pair's derivation read, in the order it read them."""
    groups = [
        *(
            scenario.source_rule_ids
            for side in (resolution.side_a, resolution.side_b)
            if side.stress is not None
            for scenario in (
                *(source.scenario for source in side.stress.own),
                *(transfer.source.scenario for transfer in side.stress.transferred),
            )
        ),
        tuple(step.semantic_rule_id for step in resolution.trace_steps),
        () if resolution.override_outcome is None else resolution.override_outcome.source_rule_ids,
    ]
    return ", ".join(dict.fromkeys(rule for group in groups for rule in group)) or "—"


def _human_override_evidence(
    resolution: EffectivePairStressResolution,
) -> tuple[HumanValue, ...]:
    """The verified override recorded at this pair, its evidence, and what became of it."""
    outcome = resolution.override_outcome
    if outcome is None:
        return ()
    override = outcome.override
    rows = [
        HumanValue("Recorded value", _effective_text(override.value_v, "V")),
        HumanValue("Basis", _value_text(override.basis)),
        HumanValue("Verification method", _value_text(override.verification_method)),
        HumanValue("Justification", _sentence(override.justification)),
        HumanValue("Evidence reference", override.evidence_reference or "—"),
        HumanValue("Affected location", override.affected_location or "—"),
    ]
    if override.transformer_frequency_hz is not None:
        rows.append(
            HumanValue(
                "Transformer frequency", _effective_text(override.transformer_frequency_hz, "Hz")
            )
        )
    if override.spd_device_placement is not None:
        rows.append(HumanValue("Device placement", _value_text(override.spd_device_placement)))
    if override.spd_device_degradable is not None:
        rows.append(
            HumanValue("Device can degrade", "yes" if override.spd_device_degradable else "no")
        )
    rows.append(
        HumanValue(
            "Outcome",
            (
                f"applied; effective impulse {_effective_text(outcome.effective_impulse_v, 'V')}"
                if outcome.applied
                else "not applied — "
                + "; ".join(
                    f"{_value_text(refusal.code)}: {_sentence(refusal.message)}"
                    for refusal in outcome.refusals
                )
            ),
        )
    )
    dependency = outcome.spd_monitoring_dependency
    if dependency is not None:
        rows.append(
            HumanValue(
                "Monitoring obligation",
                f"monitoring {'required' if dependency.monitoring_required else 'not required'}, "
                f"status indication "
                f"{'required' if dependency.status_indication_required else 'not required'}; "
                f"type test {dependency.required_type_test_semantic_id}",
            )
        )
    return tuple(rows)


def _matrix_for(
    name: str,
    unit: str,
    headers: tuple[str, ...],
    rows: tuple[MatrixRow, ...],
    value_getter: Callable[[MatrixRow], str],
    excluded: frozenset[frozenset[str]] = frozenset(),
) -> HumanMatrix:
    by_pair = {frozenset((row.net_a, row.net_b)): value_getter(row) for row in rows}
    values = tuple(
        tuple(
            "—"
            if row_header == column_header
            else _matrix_cell(frozenset((row_header, column_header)), by_pair, excluded)
            for column_header in headers
        )
        for row_header in headers
    )
    return HumanMatrix(name=name, unit=unit, headers=headers, values=values)


def _matrix_cell(
    key: frozenset[str],
    by_pair: dict[frozenset[str], str],
    excluded: frozenset[frozenset[str]],
) -> str:
    """Tell an excluded pair apart from a merely absent one."""
    if key in by_pair:
        return by_pair[key]
    return "N/A" if key in excluded else "—"


def _human_calculation(row: MatrixRow, calculation: PairCalculationReport) -> HumanPairCalculation:
    conditions = (
        HumanValue(
            "Frequency",
            _effective_text(calculation.effective_inputs.frequency_hz.value, "Hz"),
            calculation.effective_inputs.frequency_hz.provenance.value,
        ),
        HumanValue(
            "Impulse",
            _effective_text(calculation.effective_inputs.impulse_v.value, "V"),
            calculation.effective_inputs.impulse_v.provenance.value,
        ),
        HumanValue(
            "Insulation type",
            _value_text(calculation.effective_inputs.insulation_type.value),
            calculation.effective_inputs.insulation_type.provenance.value,
        ),
        HumanValue(
            "Field condition",
            _value_text(calculation.effective_inputs.field_condition.value),
            calculation.effective_inputs.field_condition.provenance.value,
        ),
        HumanValue(
            "Altitude",
            _effective_text(calculation.effective_inputs.altitude_m.value, "m"),
            calculation.effective_inputs.altitude_m.provenance.value,
        ),
        HumanValue(
            "Pollution degree",
            _effective_text(calculation.effective_inputs.pollution_degree.value, ""),
            calculation.effective_inputs.pollution_degree.provenance.value,
        ),
        HumanValue(
            "Construction",
            _value_text(calculation.effective_inputs.construction_type.value),
            calculation.effective_inputs.construction_type.provenance.value,
        ),
        HumanValue(
            "CTI/material group",
            _value_text(calculation.effective_inputs.cti_or_material_group.value),
            calculation.effective_inputs.cti_or_material_group.provenance.value,
        ),
    )
    return HumanPairCalculation(
        pair_label=f"{row.net_a} ↔ {row.net_b}",
        effective_conditions=conditions,
        stresses=calculation.stresses,
        clearance_candidates=tuple(
            _candidate(candidate) for candidate in calculation.clearance_candidates
        ),
        creepage_candidates=tuple(
            _candidate(candidate) for candidate in calculation.creepage_candidates
        ),
        clearance_explanation=_calculation_explanation(calculation.governing_clearance_reason),
        creepage_explanation=_calculation_explanation(calculation.governing_creepage_reason),
        pre_altitude_clearance=_effective_text(calculation.pre_altitude_clearance_mm, "mm"),
        altitude_correction_applied=calculation.altitude_correction_applied,
        clearance=_effective_text(calculation.clearance_mm, "mm"),
        creepage=_effective_text(calculation.creepage_mm, "mm"),
        inner_clearance=_effective_text(calculation.inner_clearance_mm, "mm"),
        inner_creepage=_effective_text(calculation.inner_creepage_mm, "mm"),
        warnings=tuple(_advisory(item) for item in calculation.warnings),
        verification_requirements=tuple(
            _advisory(item) for item in calculation.verification_requirements
        ),
    )


def _candidate(candidate: object) -> HumanCandidate:
    source_reference = next(
        (
            step.source_reference
            for step in reversed(getattr(candidate, "steps", ()))
            if step.source_reference is not None
        ),
        None,
    )
    return HumanCandidate(
        name=_candidate_name(getattr(candidate, "candidate_id", "candidate")),
        stress=_effective_text(
            getattr(getattr(candidate, "stress", None), "value", None),
            getattr(getattr(candidate, "stress", None), "unit", ""),
        ),
        distance=_effective_text(getattr(candidate, "distance_mm", None), "mm"),
        reason=_sentence(getattr(candidate, "reason", "")),
        source_reference=source_reference,
    )


def _human_rules(calculations: tuple[PairCalculationReport, ...]) -> tuple[HumanRule, ...]:
    result: list[HumanRule] = []
    seen: set[tuple[str, str]] = set()
    for calculation in calculations:
        for kind, candidates in (
            ("clearance", calculation.clearance_candidates),
            ("creepage", calculation.creepage_candidates),
        ):
            for candidate in candidates:
                key = (f"{kind}:{candidate.semantic_rule_id}", "candidate_selection")
                if key in seen:
                    continue
                seen.add(key)
                source_reference = next(
                    (
                        step.source_reference
                        for step in reversed(candidate.steps)
                        if step.source_reference is not None
                    ),
                    None,
                )
                if not _source_is_public(source_reference):
                    source_reference = None
                result.append(
                    HumanRule(
                        description=_candidate_rule_description(kind, candidate),
                        source_reference=source_reference,
                    )
                )
        for step in calculation.steps:
            if not _is_summary_step(step):
                continue
            key = (step.semantic_rule_id, step.operation)
            if key in seen:
                continue
            seen.add(key)
            source_reference = step.source_reference or step.formula_source_reference
            if not _source_is_public(source_reference):
                source_reference = None
            result.append(
                HumanRule(
                    description=_rule_description(step),
                    source_reference=source_reference,
                )
            )
    return tuple(result)


def _source_is_public(source_reference: SourceReference | None) -> bool:
    return source_reference is not None and source_reference.standard.startswith("IEC 60664-")


def _candidate_rule_description(kind: str, candidate: object) -> str:
    label = _candidate_name(str(getattr(candidate, "candidate_id", "candidate")))
    source_reference = next(
        (
            step.source_reference
            for step in reversed(getattr(candidate, "steps", ()))
            if step.source_reference is not None
        ),
        None,
    )
    if source_reference is not None:
        standard = source_reference.standard
        table = source_reference.table or "the approved table"
        return f"Select the {kind} candidate {label} from {standard} Table {table}."
    return f"Select the {kind} candidate {label} using the approved calculation rule."


def _is_summary_step(step: object) -> bool:
    semantic_rule_id = str(getattr(step, "semantic_rule_id", ""))
    operation = str(getattr(step, "operation", ""))
    return (
        semantic_rule_id == "clearance.maximum"
        or semantic_rule_id.startswith("part1.creepage.clearance_floor")
        or operation
        in {"altitude_boundary", "reinforced_stress_treatment", "reinforced_creepage_double"}
        or ":corrected_clearance" in semantic_rule_id
    )


def _rule_description(step: object) -> str:
    semantic_rule_id = str(getattr(step, "semantic_rule_id", ""))
    operation = str(getattr(step, "operation", ""))
    source = getattr(step, "source_reference", None) or getattr(
        step, "formula_source_reference", None
    )
    if semantic_rule_id == "clearance.maximum":
        return "The required clearance is the largest selected clearance candidate."
    if semantic_rule_id.startswith("part1.creepage.clearance_floor"):
        return "The final clearance is retained as a minimum creepage candidate."
    if operation == "altitude_boundary":
        return (
            "The altitude boundary is checked; no correction factor is applied at or below 2000 m."
        )
    if operation == "reinforced_stress_treatment":
        return _sentence(getattr(step, "reason", ""))
    if operation == "reinforced_creepage_double":
        return "Reinforced insulation uses twice the selected creepage distance."
    if operation == "table_select" and source is not None:
        table = getattr(source, "table", None) or "the approved table"
        standard = getattr(source, "standard", "the applicable IEC standard")
        return f"Select the required distance from {standard} Table {table} using the applicable branch."
    reason = str(getattr(step, "reason", ""))
    if reason:
        return _sentence(reason)
    return f"Apply the approved calculation rule {semantic_rule_id}."


def _advisory(item: object) -> HumanAdvisory:
    return HumanAdvisory(
        code=getattr(item, "code", ""),
        message=_sentence(getattr(item, "message", "")),
        source_reference=getattr(item, "source_reference", None),
    )


def _deduplicate_advisories(items: tuple[object, ...]) -> tuple[HumanAdvisory, ...]:
    result: list[HumanAdvisory] = []
    seen: set[str] = set()
    for item in items:
        advisory = _advisory(item)
        if advisory.code in seen:
            continue
        seen.add(advisory.code)
        result.append(advisory)
    return tuple(result)


def _candidate_name(value: str) -> str:
    names = {
        "impulse": "Impulse withstand",
        "steady_state_peak": "Steady-state peak",
        "recurring_peak": "Recurring peak",
        "temporary_overvoltage_peak": "Temporary overvoltage peak",
        "long_term_rms_tracking": "Long-term RMS tracking",
        "clearance_floor": "Clearance floor",
    }
    return names.get(value, _sentence(value.replace("_", " ")))


def _stress_text(row: MatrixRow, name: str) -> str:
    stress = next((item for item in row.stresses if item.name == name), None)
    if stress is None or stress.value_v is None:
        return "N/A" if stress is not None and stress.applicability == "not_applicable" else "—"
    return _effective_text(stress.value_v, "V")


def _stress_getter(name: str) -> Callable[[MatrixRow], str]:
    def getter(row: MatrixRow) -> str:
        return _stress_text(row, name)

    return getter


def _effective_text(value: object, unit: str) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    else:
        text = str(getattr(value, "value", value))
    return f"{text} {unit}".strip()


def _value_text(value: object) -> str:
    if value is None:
        return "—"
    return str(getattr(value, "value", value)).replace("_", " ")


def _sentence(value: str) -> str:
    text = str(value or "").replace("_", " ").strip()
    if not text:
        return "No additional explanation."
    return text[0].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")


def _calculation_explanation(reason: str) -> str:
    normalized = str(reason or "").replace("_", " ").strip().lower()
    if normalized == "impulse governs clearance":
        return "The impulse withstand requirement determined the clearance."
    if normalized == "calculated creepage governs":
        return "The calculated creepage requirement determined the creepage."
    return _sentence(reason)
