"""Five equipment topologies the dielectric verification plan has to handle.

Every name, identifier, voltage and reference here is invented for this repository. Nothing
reproduces a value, a heading, a note or any wording from any standard; what is faithful is the
*shape* of each arrangement.

``tests.fixtures.verification_topologies`` gives one general project that reaches every test
topology at once, which is what the routing tests need. These five are the opposite: each is a
recognisable piece of equipment that stresses one thing the others do not, so a change that
happens to work on the general fixture still has to answer for all five.

:func:`wireless_charger` - two circuits coupled across a barrier nobody has verified, running
above the frequency boundary where IEC 60664-4 governs. Proves that an unverified barrier still
carries stress into the receiver, and that a high-frequency project's partial-discharge
assessment raises the Part 4 review rather than settling quietly.

:func:`variable_speed_drive` - mains input, DC link and inverter output in **one** galvanic
domain with no barrier anywhere. Proves that a project with no isolation puts every circuit in
one live group, so the schedule folds their rows into one test naming every covered pair, and
that a mains-connected circuit and a non-mains one in the same project read different
dielectric routes.

:func:`multi_supply` - two enabled arrangements, an AC mains input and a DC input, feeding one
domain. Proves that a circuit connected to more than one source is planned at the more severe
of them and that both arrangements are named.

:func:`surge_protected_input` - a mains input whose impulse is reduced by a device inside the
equipment. Proves that the dedicated monitoring type test is generated for the reduction that
depends on it, that the plan stays incomplete while nothing acknowledges it, and that a pair
with no such reduction gets no monitoring row.

:func:`accessible_surfaces` - one circuit against a PE-bonded enclosure, an accessible
conductive part and an accessible insulating window at the same time. Proves the three
reference kinds stay three rows and that conductive-foil preparation attaches only to the
insulating one.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from insulation_coordination.calculation.high_frequency import PART4_FREQUENCY_THRESHOLD_HZ
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
)
from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    ImpulseOverrideBasis,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    SupplyConfiguration,
    SupplyKind,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.domain.verification import (
    ProtectionImplementation,
    SolidInsulationTestData,
)
from insulation_coordination.project.pairs import reconcile_pairs
from tests.fixtures.verification_topologies import SYSTEM_VOLTAGE_V

#: Every identifier below is drawn from a block of this module's own, so no fixture's net can
#: be mistaken for another's in a failure message.
CHARGER_TRANSMITTER = UUID(int=501)
CHARGER_RECEIVER = UUID(int=502)
CHARGER_HOUSING = UUID(int=503)
CHARGER_PRIMARY_DOMAIN = UUID(int=511)
CHARGER_SECONDARY_DOMAIN = UUID(int=512)
CHARGER_COUPLING = UUID(int=521)

DRIVE_INPUT = UUID(int=531)
DRIVE_DC_LINK = UUID(int=532)
DRIVE_OUTPUT = UUID(int=533)
DRIVE_ENCLOSURE = UUID(int=534)
DRIVE_DOMAIN = UUID(int=541)

MULTI_INPUT = UUID(int=551)
MULTI_ENCLOSURE = UUID(int=552)
MULTI_DOMAIN = UUID(int=561)
MULTI_AC_SUPPLY = UUID(int=571)
MULTI_SECOND_SUPPLY = UUID(int=572)

SPD_INPUT = UUID(int=581)
SPD_DOWNSTREAM = UUID(int=582)
SPD_ENCLOSURE = UUID(int=583)
SPD_DOMAIN = UUID(int=591)
SPD_SUPPLY = UUID(int=601)

SURFACE_CIRCUIT = UUID(int=611)
SURFACE_ENCLOSURE = UUID(int=612)
SURFACE_HANDLE = UUID(int=613)
SURFACE_WINDOW = UUID(int=614)
SURFACE_DOMAIN = UUID(int=621)

#: The frequency the wireless charger runs at: one step above the boundary the Part 4 review
#: warning is keyed on, read from the constant rather than written out, so this fixture cannot
#: drift from the rule it is exercising and states no figure of its own.
CHARGER_FREQUENCY_HZ = PART4_FREQUENCY_THRESHOLD_HZ + 1

#: A recurring peak inside the non-mains dielectric route's band axis, so a non-mains circuit
#: reads a value rather than reporting the table unreadable. This module's own number.
IN_BAND_RECURRING_PEAK_V = Decimal(25)

#: The second arrangement's declared voltage, deliberately below the first so the governing
#: selection across two sources is visibly the higher of them and not simply the last one read.
#: A band of the synthetic supply fixture's own axis; nothing here is read from any source.
LOWER_SYSTEM_VOLTAGE_V = Decimal(22)


def _defaults(
    *,
    frequency_hz: Decimal = Decimal(50),
    insulation: InsulationType = InsulationType.BASIC,
) -> ProjectDefaults:
    return ProjectDefaults(
        frequency_hz=frequency_hz,
        impulse_v=Decimal(150),
        insulation_type=insulation,
        field_condition=FieldCondition.INHOMOGENEOUS,
        altitude_m=Decimal(0),
        pollution_degree=2,
        construction_type=ConstructionType.OTHER,
        cti_or_material_group="I",
    )


def circuit(
    net_id: UUID,
    name: str,
    domain_id: UUID,
    source: CircuitSourceRelationship = CircuitSourceRelationship.INTERNALLY_GENERATED,
) -> NetClass:
    return NetClass(
        id=net_id,
        name=name,
        net_type=NetClassType.CIRCUIT,
        source_relationship=source,
        connection_exposure=ConnectionExposure.INTERNAL_ONLY,
        decisive_voltage_class=DecisiveVoltageClass.DVC_B,
        galvanic_domain_id=domain_id,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def reference(net_id: UUID, name: str, net_type: NetClassType) -> NetClass:
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


def domain(domain_id: UUID, name: str, *, direct_source: bool = False) -> GalvanicDomain:
    return GalvanicDomain(
        id=domain_id,
        name=name,
        is_direct_source_domain=direct_source,
        review_state=ReviewState.USER_CONFIRMED,
    )


def _dimensionable(pair: PairCase, recurring_peak_v: Decimal) -> PairCase:
    """Give every stress a value, so no pair is excluded and nothing is blank."""

    return pair.model_copy(
        update={
            "voltages": PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(300)),
                steady_state_peak_v=PairVoltage.applicable(Decimal(200)),
                recurring_peak_v=PairVoltage.applicable(recurring_peak_v),
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(250)),
            ),
            "protection_implementation": ProtectionImplementation.BASIC_INSULATION,
            "protection_review_state": ReviewState.USER_CONFIRMED,
        }
    )


def _project(
    *,
    identifier: int,
    title: str,
    nets: tuple[NetClass, ...],
    domains: tuple[GalvanicDomain, ...],
    barriers: tuple[GalvanicBarrier, ...] = (),
    supply_configurations: tuple[SupplyConfiguration, ...] = (),
    defaults: ProjectDefaults | None = None,
    recurring_peak_v: Decimal = IN_BAND_RECURRING_PEAK_V,
) -> Project:
    return Project(
        id=UUID(int=identifier),
        metadata=ProjectMetadata(title=title),
        application_version="test",
        defaults=defaults or _defaults(),
        net_classes=nets,
        pairs=tuple(_dimensionable(pair, recurring_peak_v) for pair in reconcile_pairs(nets, ())),
        galvanic_domains=domains,
        galvanic_barriers=barriers,
        supply_configurations=supply_configurations,
    )


def _mains(
    supply_id: UUID,
    name: str,
    *,
    voltage_v: Decimal = SYSTEM_VOLTAGE_V,
    phase: PhaseSystem = PhaseSystem.THREE_PHASE,
) -> SupplyConfiguration:
    """One enabled AC mains arrangement. Every figure is this module's own."""

    return SupplyConfiguration(
        id=supply_id,
        enabled=True,
        name=name,
        supply_kind=SupplyKind.AC_MAINS,
        nominal_voltage_v=voltage_v,
        phase_system=phase,
        earthing_arrangement=EarthingArrangement.TN_STAR_POINT_EARTHED,
        overvoltage_category=OvervoltageCategory.IV,
        input_topology=InputTopology.DIRECT_INPUT,
        declared_system_voltages=(
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=voltage_v),
        ),
    )


# --- the five ---------------------------------------------------------------------------


def wireless_charger() -> Project:
    """Transmitter and receiver across an unverified coupling, above the Part 4 boundary."""

    return _project(
        identifier=500,
        title="Wireless charger",
        nets=(
            circuit(
                CHARGER_TRANSMITTER,
                "Transmitter coil",
                CHARGER_PRIMARY_DOMAIN,
                CircuitSourceRelationship.MAINS_CONNECTED,
            ),
            circuit(CHARGER_RECEIVER, "Receiver coil", CHARGER_SECONDARY_DOMAIN),
            reference(CHARGER_HOUSING, "Housing", NetClassType.ACCESSIBLE_INSULATING_SURFACE),
        ),
        domains=(
            domain(CHARGER_PRIMARY_DOMAIN, "Transmitter", direct_source=True),
            domain(CHARGER_SECONDARY_DOMAIN, "Receiver"),
        ),
        barriers=(
            GalvanicBarrier(
                id=CHARGER_COUPLING,
                domain_a_id=CHARGER_PRIMARY_DOMAIN,
                domain_b_id=CHARGER_SECONDARY_DOMAIN,
                status=BarrierVerificationStatus.NOT_EVALUATED,
                description="Inductive coupling",
            ),
        ),
        supply_configurations=(_mains(UUID(int=522), "Charger input"),),
        defaults=_defaults(frequency_hz=CHARGER_FREQUENCY_HZ),
    )


def variable_speed_drive() -> Project:
    """Mains input, DC link and inverter output, all in one domain with no barrier at all."""

    return _project(
        identifier=530,
        title="Variable speed drive",
        nets=(
            circuit(
                DRIVE_INPUT,
                "Mains input",
                DRIVE_DOMAIN,
                CircuitSourceRelationship.MAINS_CONNECTED,
            ),
            circuit(DRIVE_DC_LINK, "DC link", DRIVE_DOMAIN),
            circuit(DRIVE_OUTPUT, "Motor output", DRIVE_DOMAIN),
            reference(DRIVE_ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
        ),
        domains=(domain(DRIVE_DOMAIN, "Power stage", direct_source=True),),
        supply_configurations=(_mains(UUID(int=542), "Drive input"),),
    )


def variable_speed_drive_with_declared_insulation() -> Project:
    """The same drive, with its solid insulation declared so the PD gate can settle."""

    project = variable_speed_drive()
    declared = SolidInsulationTestData(
        present=True,
        minimum_thickness_mm=Decimal("0.5"),
        material_pd_exempt=False,
        layer_count=1,
        material_reference="SYN-DRIVE-MATERIAL-1",
    )
    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"solid_insulation": declared}) for pair in project.pairs
            )
        }
    )


def multi_supply() -> Project:
    """One circuit fed by two enabled arrangements, an AC input and a DC input."""

    return _project(
        identifier=550,
        title="Multi-supply input stage",
        nets=(
            circuit(
                MULTI_INPUT,
                "Common input",
                MULTI_DOMAIN,
                CircuitSourceRelationship.MAINS_CONNECTED,
            ),
            reference(MULTI_ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
        ),
        domains=(domain(MULTI_DOMAIN, "Input", direct_source=True),),
        supply_configurations=(
            _mains(MULTI_AC_SUPPLY, "Three-phase input"),
            _mains(
                MULTI_SECOND_SUPPLY,
                "Single-phase input",
                voltage_v=LOWER_SYSTEM_VOLTAGE_V,
                phase=PhaseSystem.SINGLE_PHASE,
            ),
        ),
    )


def surge_protected_input() -> Project:
    """A mains input whose impulse a device inside the equipment reduces."""

    project = _project(
        identifier=580,
        title="Surge-protected input",
        nets=(
            circuit(
                SPD_INPUT,
                "Protected input",
                SPD_DOMAIN,
                CircuitSourceRelationship.MAINS_CONNECTED,
            ),
            circuit(SPD_DOWNSTREAM, "Downstream stage", SPD_DOMAIN),
            reference(SPD_ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
        ),
        domains=(domain(SPD_DOMAIN, "Input", direct_source=True),),
        supply_configurations=(_mains(SPD_SUPPLY, "Protected mains input"),),
    )
    protected = protected_pair(project)
    override = VerifiedImpulseOverride(
        value_v=Decimal(50),
        basis=ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER,
        verification_method=ReductionVerificationMethod.TEST,
        justification="Synthetic reduction recorded by this fixture.",
        evidence_reference="SYN-SPD-1",
        affected_location="the protected input to enclosure insulation",
        spd_device_placement=SpdDevicePlacement.INTERNAL_TO_EQUIPMENT,
        spd_device_degradable=True,
    )
    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update={"impulse_override": override})
                if pair.id == protected.id
                else pair
                for pair in project.pairs
            )
        }
    )


def protected_pair(project: Project) -> PairCase:
    """The input-to-enclosure pair the surge fixture records its reduction at."""

    return _pair_between(project, SPD_INPUT, SPD_ENCLOSURE)


def accessible_surfaces() -> Project:
    """One circuit against all three reference parts at once, insulating window included."""

    return _project(
        identifier=610,
        title="Accessible surfaces",
        nets=(
            circuit(
                SURFACE_CIRCUIT,
                "Live circuit",
                SURFACE_DOMAIN,
                CircuitSourceRelationship.MAINS_CONNECTED,
            ),
            reference(SURFACE_ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
            reference(SURFACE_HANDLE, "Handle", NetClassType.ACCESSIBLE_CONDUCTIVE_PART),
            reference(SURFACE_WINDOW, "Window", NetClassType.ACCESSIBLE_INSULATING_SURFACE),
        ),
        domains=(domain(SURFACE_DOMAIN, "Live", direct_source=True),),
        supply_configurations=(_mains(UUID(int=622), "Surface example input"),),
    )


def _pair_between(project: Project, first: UUID, second: UUID) -> PairCase:
    return next(pair for pair in project.pairs if {pair.net_a, pair.net_b} == {first, second})


pair_between = _pair_between


__all__ = [
    "CHARGER_FREQUENCY_HZ",
    "CHARGER_HOUSING",
    "CHARGER_RECEIVER",
    "CHARGER_TRANSMITTER",
    "DRIVE_DC_LINK",
    "DRIVE_ENCLOSURE",
    "DRIVE_INPUT",
    "DRIVE_OUTPUT",
    "IN_BAND_RECURRING_PEAK_V",
    "LOWER_SYSTEM_VOLTAGE_V",
    "MULTI_ENCLOSURE",
    "MULTI_INPUT",
    "SPD_DOWNSTREAM",
    "SPD_ENCLOSURE",
    "SPD_INPUT",
    "SURFACE_CIRCUIT",
    "SURFACE_ENCLOSURE",
    "SURFACE_HANDLE",
    "SURFACE_WINDOW",
    "accessible_surfaces",
    "multi_supply",
    "pair_between",
    "protected_pair",
    "surge_protected_input",
    "variable_speed_drive",
    "variable_speed_drive_with_declared_insulation",
    "wireless_charger",
]
