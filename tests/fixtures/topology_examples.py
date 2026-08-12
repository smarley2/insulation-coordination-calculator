"""Three worked IEC 62477-1 project-topology examples, as reusable fixtures.

Every value below is invented for this repository: net names, domain names, evidence
references, and every voltage/frequency figure are synthetic and carry no licensed IEC
content. The (insulation type, frequency, peak voltage) triples in ``_KNOWN_GOOD`` are
copied from the already-verified combinations in ``tests/test_end_to_end.py`` rather than
invented afresh, so every "applicable" pair is guaranteed to calculate successfully
against the semantic rule packages in ``tests/calculation/conftest.py``.

Each builder returns a fully valid, already-classified :class:`Project`: every circuit net
carries a resolved domain and a decisive voltage class, every domain pair a barrier, and
every net-class pair either an applicable stress or a recorded exclusion - there is no
lingering ``NOT_EVALUATED``/blank state left for a reviewer to close. ``topology_completion``
on any of them reports ``is_complete=True``.

The on-board-charger (OBC) example's domains carry
:data:`insulation_coordination.domain.display.OBC_APPLICABILITY_WARNING` verbatim in
their ``description`` field, so the warning is genuinely part of the fixture data and shows
up in a rendered report - not only in this docstring.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations
from uuid import UUID

from insulation_coordination.domain.display import OBC_APPLICABILITY_WARNING
from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    CircuitSourceRelationship,
    ConnectionExposure,
    ConstructionType,
    DecisiveVoltageClass,
    FieldCondition,
    InsulationType,
    NetClassType,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.project import (
    NetClass,
    OverrideValue,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.project.pairs import canonical_pair_key, reconcile_pairs

_DEFAULTS = ProjectDefaults(
    frequency_hz=Decimal(50),
    impulse_v=Decimal(1000),
    insulation_type=InsulationType.BASIC,
    field_condition=FieldCondition.INHOMOGENEOUS,
    altitude_m=Decimal(0),
    pollution_degree=2,
    construction_type=ConstructionType.PRINTED_WIRING,
    cti_or_material_group="I",
)

#: (insulation type, frequency, peak voltage) triples already proven to calculate
#: successfully against the semantic Part 1 / Part 4 rule packages built in
#: ``tests/test_end_to_end.py``. Reused here verbatim rather than re-derived.
_KNOWN_GOOD = (
    (InsulationType.FUNCTIONAL, Decimal(150), Decimal(300)),
    (InsulationType.BASIC, Decimal(300), Decimal(300)),
    (InsulationType.REINFORCED, Decimal(500), Decimal(500)),
    (InsulationType.FUNCTIONAL, Decimal(60000), Decimal(300)),
    (InsulationType.BASIC, Decimal(60000), Decimal(300)),
    (InsulationType.REINFORCED, Decimal(60000), Decimal(500)),
)

_NO_COUPLING = "No coupling recorded between these nets in this topology example."


def _uuid(seed: int) -> UUID:
    return UUID(int=seed)


def _circuit(
    seed: int,
    name: str,
    *,
    source: CircuitSourceRelationship,
    exposure: ConnectionExposure,
    dvc: DecisiveVoltageClass,
    domain_id: UUID,
) -> NetClass:
    return NetClass(
        id=_uuid(seed),
        name=name,
        source_relationship=source,
        connection_exposure=exposure,
        decisive_voltage_class=dvc,
        galvanic_domain_id=domain_id,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def _non_circuit(seed: int, name: str, net_type: NetClassType) -> NetClass:
    return NetClass(
        id=_uuid(seed),
        name=name,
        net_type=net_type,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def _domain(seed: int, name: str, *, direct: bool = False) -> GalvanicDomain:
    return GalvanicDomain(
        id=_uuid(seed),
        name=name,
        is_direct_source_domain=direct,
        review_state=ReviewState.USER_CONFIRMED,
    )


def _verified_barrier(
    seed: int, domain_a: UUID, domain_b: UUID, description: str, evidence: str
) -> GalvanicBarrier:
    return GalvanicBarrier(
        id=_uuid(seed),
        domain_a_id=domain_a,
        domain_b_id=domain_b,
        status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
        description=description,
        verification_method=VerificationMethod.TEST,
        evidence_reference=evidence,
    )


def _unverified_barrier(
    seed: int, domain_a: UUID, domain_b: UUID, description: str
) -> GalvanicBarrier:
    return GalvanicBarrier(
        id=_uuid(seed),
        domain_a_id=domain_a,
        domain_b_id=domain_b,
        status=BarrierVerificationStatus.NO_GALVANIC_ISOLATION,
        description=description,
    )


def _excluded_voltages(reason: str = _NO_COUPLING) -> PairVoltages:
    blank = PairVoltage.not_applicable(reason)
    return PairVoltages(
        long_term_rms_v=blank,
        steady_state_peak_v=blank,
        recurring_peak_v=blank,
        temporary_overvoltage_peak_v=blank,
    )


def _applicable_voltages(peak: Decimal) -> PairVoltages:
    return PairVoltages(
        long_term_rms_v=PairVoltage.applicable(peak),
        steady_state_peak_v=PairVoltage.applicable(peak),
        recurring_peak_v=PairVoltage.not_applicable(
            "No recurring peak recorded for this topology example."
        ),
        temporary_overvoltage_peak_v=PairVoltage.not_applicable(
            "No temporary overvoltage recorded for this topology example."
        ),
    )


def _build_pairs(
    net_classes: tuple[NetClass, ...],
    applicable: dict[frozenset[UUID], tuple[InsulationType, Decimal, Decimal]],
) -> tuple[PairCase, ...]:
    """Every combination of ``net_classes``: an applicable stress, or a recorded exclusion.

    A pair left ``BLANK`` (``reconcile_pairs``'s own default for a newly added net) is not
    the same thing as an excluded one and would leave the report build blocked on missing
    data - so every pair this project ever presents is resolved one way or the other here.
    """
    pairs: list[PairCase] = []
    for left, right in combinations([net.id for net in net_classes], 2):
        key = canonical_pair_key(left, right)
        spec = applicable.get(frozenset((left, right)))
        if spec is None:
            pairs.append(PairCase(key=key, net_a=left, net_b=right, voltages=_excluded_voltages()))
        else:
            insulation_type, frequency, peak = spec
            pairs.append(
                PairCase(
                    key=key,
                    net_a=left,
                    net_b=right,
                    voltages=_applicable_voltages(peak),
                    frequency_hz=OverrideValue[Decimal].override(frequency),
                    insulation_type=OverrideValue[InsulationType].override(insulation_type),
                )
            )
    return reconcile_pairs(net_classes, tuple(pairs))


def _override_pair(
    pairs: tuple[PairCase, ...], net_a: UUID, net_b: UUID, **overrides: object
) -> tuple[PairCase, ...]:
    key = canonical_pair_key(net_a, net_b)
    return tuple(pair.model_copy(update=overrides) if pair.key == key else pair for pair in pairs)


# --- wireless power charging -------------------------------------------------------


def wireless_charging_project(required_rules: RulePackageReference | None = None) -> Project:
    """Mains input through a coreless coil coupling to a receiver-side battery output.

    Two galvanic domains (primary, receiver) joined by one verified barrier - the
    coreless wireless-power coupling itself.
    """
    primary_domain = _domain(1, "Primary side", direct=True)
    receiver_domain = _domain(2, "Receiver side")

    ac_input = _circuit(
        10,
        "AC Mains Input",
        source=CircuitSourceRelationship.MAINS_CONNECTED,
        exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=primary_domain.id,
    )
    dc_link = _circuit(
        11,
        "Primary DC Link",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=primary_domain.id,
    )
    resonant_node = _circuit(
        12,
        "Primary Switching/Resonant Node",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=primary_domain.id,
    )
    receiver_coil = _circuit(
        13,
        "Receiver Coil/Rectifier",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_B,
        domain_id=receiver_domain.id,
    )
    battery_output = _circuit(
        14,
        "Battery/DC Output",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
        dvc=DecisiveVoltageClass.DVC_AS,
        domain_id=receiver_domain.id,
    )
    pe_enclosure = _non_circuit(15, "PE Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART)
    accessible_cover = _non_circuit(
        16, "Accessible Polymer Cover", NetClassType.ACCESSIBLE_INSULATING_SURFACE
    )

    net_classes = (
        ac_input,
        dc_link,
        resonant_node,
        receiver_coil,
        battery_output,
        pe_enclosure,
        accessible_cover,
    )
    barrier = _verified_barrier(
        50,
        primary_domain.id,
        receiver_domain.id,
        "Coreless wireless-power coupling between the primary and receiver coils.",
        "WPC-EXAMPLE-COUPLING-01",
    )
    applicable = {
        frozenset((ac_input.id, pe_enclosure.id)): _KNOWN_GOOD[1],
        frozenset((resonant_node.id, receiver_coil.id)): _KNOWN_GOOD[5],
        frozenset((receiver_coil.id, battery_output.id)): _KNOWN_GOOD[0],
        frozenset((battery_output.id, accessible_cover.id)): _KNOWN_GOOD[2],
    }
    pairs = _build_pairs(net_classes, applicable)
    # Exercise an override beyond frequency/insulation type, across the isolation boundary.
    pairs = _override_pair(
        pairs,
        resonant_node.id,
        receiver_coil.id,
        electrode_radius_mm=OverrideValue[Decimal].override(Decimal("1.5")),
    )

    return Project(
        id=_uuid(900),
        metadata=ProjectMetadata(title="Wireless Power Charging Topology Example"),
        application_version="test",
        required_rules=required_rules,
        defaults=_DEFAULTS,
        net_classes=net_classes,
        pairs=pairs,
        galvanic_domains=(primary_domain, receiver_domain),
        galvanic_barriers=(barrier,),
    )


# --- on-board charger (isolated / non-isolated) -------------------------------------


def _obc_nets(
    base_seed: int, primary_domain_id: UUID, secondary_domain_id: UUID
) -> tuple[NetClass, ...]:
    """The six OBC nodes, shared by both variants so only their grouping differs.

    A real non-isolated charger would have no isolation transformer, so "Transformer
    Primary" is a node it would not carry. It stays here because the two variants must
    differ in their domains and barrier alone: that is what the examples are contrasting,
    and a second skeleton would let a reader attribute the difference to the net list.
    """
    return (
        _circuit(
            base_seed + 1,
            "AC Input",
            source=CircuitSourceRelationship.MAINS_CONNECTED,
            exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
            dvc=DecisiveVoltageClass.DVC_C,
            domain_id=primary_domain_id,
        ),
        _circuit(
            base_seed + 2,
            "PFC/DC Link",
            source=CircuitSourceRelationship.INTERNALLY_GENERATED,
            exposure=ConnectionExposure.INTERNAL_ONLY,
            dvc=DecisiveVoltageClass.DVC_C,
            domain_id=primary_domain_id,
        ),
        _circuit(
            base_seed + 3,
            "Transformer Primary",
            source=CircuitSourceRelationship.INTERNALLY_GENERATED,
            exposure=ConnectionExposure.INTERNAL_ONLY,
            dvc=DecisiveVoltageClass.DVC_C,
            domain_id=primary_domain_id,
        ),
        _circuit(
            base_seed + 4,
            "HV Battery Output",
            source=CircuitSourceRelationship.INTERNALLY_GENERATED,
            exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
            dvc=DecisiveVoltageClass.DVC_B,
            domain_id=secondary_domain_id,
        ),
        _circuit(
            base_seed + 5,
            "12V/CAN",
            source=CircuitSourceRelationship.INTERNALLY_GENERATED,
            exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
            dvc=DecisiveVoltageClass.DVC_AS,
            domain_id=secondary_domain_id,
        ),
        _non_circuit(base_seed + 6, "Chassis", NetClassType.PE_BONDED_CONDUCTIVE_PART),
    )


def _obc_applicable(
    nets: tuple[NetClass, ...],
) -> dict[frozenset[UUID], tuple[InsulationType, Decimal, Decimal]]:
    ac_input, _pfc_link, transformer_primary, hv_battery, lv_can, chassis = nets
    return {
        frozenset((ac_input.id, chassis.id)): _KNOWN_GOOD[1],
        frozenset((transformer_primary.id, hv_battery.id)): _KNOWN_GOOD[5],
        frozenset((hv_battery.id, lv_can.id)): _KNOWN_GOOD[2],
        frozenset((lv_can.id, chassis.id)): _KNOWN_GOOD[0],
    }


def obc_isolated_project(required_rules: RulePackageReference | None = None) -> Project:
    """An isolated on-board charger: primary and secondary sides on separate, verified domains.

    Carries :data:`OBC_APPLICABILITY_WARNING` verbatim on both domain descriptions.
    """
    primary = _domain(200, "Primary side", direct=True)
    secondary = _domain(201, "Secondary side")
    nets = _obc_nets(2100, primary.id, secondary.id)
    barrier = _verified_barrier(
        250,
        primary.id,
        secondary.id,
        "Isolation transformer and isolated gate-drive supply.",
        "OBC-EXAMPLE-ISO-01",
    )
    pairs = _build_pairs(nets, _obc_applicable(nets))
    primary = primary.model_copy(
        update={
            "description": (
                f"Mains-referenced primary side of the OBC isolated-variant topology "
                f"example. {OBC_APPLICABILITY_WARNING}"
            )
        }
    )
    secondary = secondary.model_copy(
        update={
            "description": (
                f"HV-battery-referenced secondary side of the OBC isolated-variant "
                f"topology example. {OBC_APPLICABILITY_WARNING}"
            )
        }
    )

    return Project(
        id=_uuid(2000),
        metadata=ProjectMetadata(title="On-Board Charger Topology Example (Isolated)"),
        application_version="test",
        required_rules=required_rules,
        defaults=_DEFAULTS,
        net_classes=nets,
        pairs=pairs,
        galvanic_domains=(primary, secondary),
        galvanic_barriers=(barrier,),
    )


def obc_non_isolated_project(required_rules: RulePackageReference | None = None) -> Project:
    """A non-isolated on-board charger: both sides share one domain pair, with no isolation.

    Same net skeleton as :func:`obc_isolated_project`; only the domain/barrier assignment
    differs, showing that the pair matrix itself does not depend on it.
    """
    primary = _domain(300, "Mains-referenced side", direct=True)
    secondary = _domain(301, "Battery-referenced side")
    nets = _obc_nets(3100, primary.id, secondary.id)
    barrier = _unverified_barrier(
        350,
        primary.id,
        secondary.id,
        (
            "Non-isolated DC-DC conversion stage; the battery-referenced side shares a "
            "common return with the mains-referenced primary."
        ),
    )
    pairs = _build_pairs(nets, _obc_applicable(nets))
    primary = primary.model_copy(
        update={
            "description": (
                f"Mains-referenced side of the OBC non-isolated-variant topology example. "
                f"{OBC_APPLICABILITY_WARNING}"
            )
        }
    )
    secondary = secondary.model_copy(
        update={
            "description": (
                f"Battery-referenced side of the OBC non-isolated-variant topology example. "
                f"{OBC_APPLICABILITY_WARNING}"
            )
        }
    )

    return Project(
        id=_uuid(3000),
        metadata=ProjectMetadata(title="On-Board Charger Topology Example (Non-Isolated)"),
        application_version="test",
        required_rules=required_rules,
        defaults=_DEFAULTS,
        net_classes=nets,
        pairs=pairs,
        galvanic_domains=(primary, secondary),
        galvanic_barriers=(barrier,),
    )


# --- variable-speed drive ------------------------------------------------------------


def variable_speed_drive_project(required_rules: RulePackageReference | None = None) -> Project:
    """Mains through an inverter to a motor output, plus an optional isolated-control domain."""
    power = _domain(400, "Power domain", direct=True)
    isolated_control = _domain(401, "Isolated control domain")

    mains = _circuit(
        4101,
        "Mains Input",
        source=CircuitSourceRelationship.MAINS_CONNECTED,
        exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=power.id,
    )
    dc_bus = _circuit(
        4102,
        "DC Bus",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=power.id,
    )
    inverter_node = _circuit(
        4103,
        "Inverter Switching Node",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=power.id,
    )
    motor_output = _circuit(
        4104,
        "Motor Phase Output (U/V/W)",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
        dvc=DecisiveVoltageClass.DVC_C,
        domain_id=power.id,
    )
    fieldbus = _circuit(
        4105,
        "Control/Fieldbus Port",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE,
        dvc=DecisiveVoltageClass.DVC_AS,
        domain_id=isolated_control.id,
    )
    enclosure = _non_circuit(4106, "PE/Heatsink/Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART)
    isolated_supply = _circuit(
        4107,
        "Isolated Control Supply",
        source=CircuitSourceRelationship.INTERNALLY_GENERATED,
        exposure=ConnectionExposure.INTERNAL_ONLY,
        dvc=DecisiveVoltageClass.DVC_AS,
        domain_id=isolated_control.id,
    )

    net_classes = (mains, dc_bus, inverter_node, motor_output, fieldbus, enclosure, isolated_supply)
    barrier = _verified_barrier(
        450,
        power.id,
        isolated_control.id,
        "Opto-isolated gate-drive and control-supply barrier.",
        "VSD-EXAMPLE-CTRL-ISO-01",
    )
    applicable = {
        frozenset((mains.id, enclosure.id)): _KNOWN_GOOD[1],
        frozenset((dc_bus.id, motor_output.id)): _KNOWN_GOOD[3],
        frozenset((motor_output.id, enclosure.id)): _KNOWN_GOOD[5],
        frozenset((isolated_supply.id, dc_bus.id)): _KNOWN_GOOD[2],
        frozenset((fieldbus.id, enclosure.id)): _KNOWN_GOOD[0],
    }
    pairs = _build_pairs(net_classes, applicable)

    return Project(
        id=_uuid(4000),
        metadata=ProjectMetadata(title="Variable-Speed Drive Topology Example"),
        application_version="test",
        required_rules=required_rules,
        defaults=_DEFAULTS,
        net_classes=net_classes,
        pairs=pairs,
        galvanic_domains=(power, isolated_control),
        galvanic_barriers=(barrier,),
    )
