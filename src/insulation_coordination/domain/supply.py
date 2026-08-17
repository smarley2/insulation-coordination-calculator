"""The supply arrangements a project declares, and the stresses derived from them.

A :class:`SupplyConfiguration` is what a user enters: one supported supply arrangement of the
equipment, carrying no reading of the standard at all. Everything normative about it - which
system voltage measure applies, which impulse withstand it selects, whether a temporary
overvoltage applies to a given pair - is resolved later against the approved rule package and
lands in a :class:`DerivedSupplyScenario`. The two never share a field: a derived value is a
runtime result recomputed before every report, and is never written back into the
configuration a user edits.

Validation is split the way the project page presents it.

*Contradictions* are refused at construction, because no editor should be able to persist a
value that cannot mean anything - a phase system on a DC supply, or a rectifier bridge voltage
on a topology that has no bridges.

*Incompleteness* is reported by :func:`validate_supply_configurations` rather than raised. An
enabled mains row with no overvoltage category is incomplete, not impossible, and the project
page shows every incomplete row at once instead of stopping at the first. A disabled row is
allowed to stay half-filled: it is persisted and takes no part in any calculation.

No value in this module comes from IEC 62477-1:2022. The enum members are neutral names for
the arrangements a user chooses between, and the numbers a configuration carries are the
user's own equipment data.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue, PositiveDecimal
from insulation_coordination.domain.trace import CalculationWarning, TraceStep


class SupplyKind(StrEnum):
    AC_MAINS = "ac_mains"
    RECTIFIED_DC_FROM_AC_MAINS = "rectified_dc_from_ac_mains"
    NON_MAINS_AC = "non_mains_ac"
    NON_MAINS_DC = "non_mains_dc"


class PhaseSystem(StrEnum):
    SINGLE_PHASE = "single_phase"
    THREE_PHASE = "three_phase"


class EarthingArrangement(StrEnum):
    TN_STAR_POINT_EARTHED = "tn_star_point_earthed"
    TT_STAR_POINT_EARTHED = "tt_star_point_earthed"
    IT_THREE_PHASE = "it_three_phase"
    IT_SINGLE_PHASE = "it_single_phase"
    TN_TT_CORNER_EARTHED_DELTA = "tn_tt_corner_earthed_delta"
    TN_TT_HIGH_LEG_DELTA = "tn_tt_high_leg_delta"
    NOT_APPLICABLE = "not_applicable"


class InputTopology(StrEnum):
    DIRECT_INPUT = "direct_input"
    RECTIFIED_FROM_AC = "rectified_from_ac"
    SERIES_CONNECTED_RECTIFIER_BRIDGES = "series_connected_rectifier_bridges"
    CUSTOM_REVIEWED_CONFIGURATION = "custom_reviewed_configuration"


class OvervoltageCategory(StrEnum):
    #: The designation is the member name throughout: renaming ``I`` to spell it out would
    #: invent a token nothing else in the application uses.
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"


#: The kinds whose stresses are resolved from a mains system voltage, and which therefore
#: need the phase, earthing and overvoltage category that resolution asks about. A rectified
#: DC input belongs here: its own terminals are DC, but the arrangement it is derived from is
#: the AC mains before the rectifier, and that is what the resolution reads.
MAINS_SUPPLY_KINDS: frozenset[SupplyKind] = frozenset(
    {SupplyKind.AC_MAINS, SupplyKind.RECTIFIED_DC_FROM_AC_MAINS}
)

#: The kinds that carry no AC phase system anywhere in their arrangement. Only a supply that
#: is DC all the way back to its source qualifies, which is why a rectified mains input is not
#: in this set.
PHASELESS_SUPPLY_KINDS: frozenset[SupplyKind] = frozenset({SupplyKind.NON_MAINS_DC})

#: The one measure of the package's own vocabulary this model names, because it is the one
#: whose value a configuration field already carries - see
#: :attr:`SupplyConfiguration.rectifier_bridge_rms_v`, which exists for exactly this reading
#: and which nothing would otherwise read.
BRIDGE_SYSTEM_VOLTAGE_MEASURE = "highest_pre_rectifier_ac_rms_at_bridge"


class DeclaredSystemVoltage(FrozenModel):
    """One voltage of a supply arrangement, named by the measure it is a measure of.

    The approved rule package answers "which voltage of this arrangement is the system
    voltage" with the *name* of a measure, deliberately never with a calculation, so a
    configuration has to be able to state that measure's value rather than have it computed
    from another one. A three-phase IT arrangement is the case that makes this unavoidable:
    the impulse and temporary-overvoltage questions resolve to two different measures of the
    same supply, and the source relates them only in a note the package carries as guidance.

    ``measure`` is left as free text on purpose. The vocabulary belongs to the active package,
    which declares it on the resolution rule's own output, and a copy of it here would be a
    second list to keep in step. A measure nothing resolves to is simply never read.
    """

    measure: str = Field(min_length=1)
    value_v: PositiveDecimal


def normalized_configuration_name(name: str) -> str:
    """One configuration name reduced to the form two names are compared as.

    Case and runs of whitespace are the differences a user does not intend, so ``"Main  AC"``
    and ``"main ac"`` are the same name. Everything else is kept: two names that differ by a
    character are two configurations.
    """

    return " ".join(name.split()).casefold()


class SupplyConfiguration(FrozenModel):
    """One supported supply arrangement of the equipment, exactly as a user entered it."""

    id: UUID
    enabled: bool
    name: str = Field(min_length=1)
    supply_kind: SupplyKind
    nominal_voltage_v: PositiveDecimal
    phase_system: PhaseSystem | None
    earthing_arrangement: EarthingArrangement
    overvoltage_category: OvervoltageCategory | None
    input_topology: InputTopology
    rectifier_bridge_rms_v: PositiveDecimal | None = None
    #: The arrangement's voltages, one per measure the rules may ask for. ``nominal_voltage_v``
    #: is what the row is called - "the 400 V supply" - and stays the user's own headline
    #: figure; this is what a derivation reads, because which measure a lookup needs is
    #: decided by the package and not by the row.
    declared_system_voltages: tuple[DeclaredSystemVoltage, ...] = ()
    notes: str = ""

    @property
    def is_mains(self) -> bool:
        return self.supply_kind in MAINS_SUPPLY_KINDS

    def declared_voltage(self, measure: str) -> Decimal | None:
        """The voltage this configuration declares for ``measure``, or ``None`` if it does not.

        The bridge measure reads :attr:`rectifier_bridge_rms_v`, which is the field this model
        already collects it in and already requires for that topology. Everything else is read
        from :attr:`declared_system_voltages`, which may still override the bridge field if a
        user states it there instead.
        """

        for declared in self.declared_system_voltages:
            if declared.measure == measure:
                return declared.value_v
        if measure == BRIDGE_SYSTEM_VOLTAGE_MEASURE:
            return self.rectifier_bridge_rms_v
        return None

    @model_validator(mode="after")
    def _refuses_contradictions(self) -> Self:
        if not self.name.strip():
            raise ValueError("A supply configuration needs a name")
        measures = tuple(declared.measure for declared in self.declared_system_voltages)
        if len(set(measures)) != len(measures):
            raise ValueError("A supply configuration states each system voltage measure once")
        if self.supply_kind in PHASELESS_SUPPLY_KINDS and self.phase_system is not None:
            raise ValueError("A DC supply has no phase system")
        bridges = self.input_topology is InputTopology.SERIES_CONNECTED_RECTIFIER_BRIDGES
        if self.rectifier_bridge_rms_v is not None and not bridges:
            # The missing half of this pair is incompleteness, not a contradiction, and is
            # reported rather than raised: a user changing topology has to be able to save.
            raise ValueError(
                "Only series-connected rectifier bridges carry a bridge RMS AC voltage"
            )
        return self


class SupplyConfigurationProblemCode(StrEnum):
    """Why one enabled configuration cannot yet be derived from.

    Typed rather than left as prose, so the project page can highlight the field a problem is
    about and a report can group problems without parsing a message.
    """

    MISSING_PHASE_SYSTEM = "missing_phase_system"
    MISSING_EARTHING_ARRANGEMENT = "missing_earthing_arrangement"
    MISSING_OVERVOLTAGE_CATEGORY = "missing_overvoltage_category"
    MISSING_BRIDGE_RMS_VOLTAGE = "missing_bridge_rms_voltage"
    DUPLICATE_NAME = "duplicate_name"


class SupplyConfigurationProblem(FrozenModel):
    configuration_id: UUID
    code: SupplyConfigurationProblemCode
    message: str


def validate_supply_configurations(
    configurations: tuple[SupplyConfiguration, ...],
) -> tuple[SupplyConfigurationProblem, ...]:
    """Every problem across the whole set, in project order, never only the first.

    An empty result means every enabled row can be derived from. It does not mean any row is
    enabled: a project with no enabled supply configuration is a supported state, in which the
    manual stress fields stay in charge.

    A name collision is reported against the later of the two rows, so re-running this after a
    rename cannot make an untouched row change status. Names are compared across the whole
    set, disabled rows included: a disabled row is persisted and can be enabled again, and two
    rows that would then collide are a collision now.
    """

    problems: list[SupplyConfigurationProblem] = []
    seen: set[str] = set()
    for configuration in configurations:
        name = normalized_configuration_name(configuration.name)
        if name in seen:
            problems.append(
                SupplyConfigurationProblem(
                    configuration_id=configuration.id,
                    code=SupplyConfigurationProblemCode.DUPLICATE_NAME,
                    message=f"Another supply configuration is already named {configuration.name!r}",
                )
            )
        seen.add(name)
        problems.extend(_completeness_problems(configuration))
    return tuple(problems)


def _completeness_problems(
    configuration: SupplyConfiguration,
) -> tuple[SupplyConfigurationProblem, ...]:
    """What one enabled row is still missing.

    A disabled row is skipped entirely rather than reported as complete: it takes no part in
    any calculation, so there is nothing about it to be incomplete for.

    A non-mains row is not checked here because the model already requires everything it
    needs: the AC or DC kind and the nominal voltage are non-optional fields. Whether its
    overvoltage category may be resolved by the rule package or must be chosen by hand is a
    question for the package, not for this function.
    """

    if not configuration.enabled:
        return ()
    problems: list[SupplyConfigurationProblem] = []

    def add(code: SupplyConfigurationProblemCode, message: str) -> None:
        problems.append(
            SupplyConfigurationProblem(
                configuration_id=configuration.id, code=code, message=message
            )
        )

    if configuration.is_mains:
        if configuration.phase_system is None:
            add(
                SupplyConfigurationProblemCode.MISSING_PHASE_SYSTEM,
                "An enabled mains supply configuration needs a phase system",
            )
        if configuration.earthing_arrangement is EarthingArrangement.NOT_APPLICABLE:
            add(
                SupplyConfigurationProblemCode.MISSING_EARTHING_ARRANGEMENT,
                "An enabled mains supply configuration needs an earthing arrangement",
            )
        if configuration.overvoltage_category is None:
            add(
                SupplyConfigurationProblemCode.MISSING_OVERVOLTAGE_CATEGORY,
                "An enabled mains supply configuration needs an overvoltage category",
            )
    if (
        configuration.input_topology is InputTopology.SERIES_CONNECTED_RECTIFIER_BRIDGES
        and configuration.rectifier_bridge_rms_v is None
    ):
        add(
            SupplyConfigurationProblemCode.MISSING_BRIDGE_RMS_VOLTAGE,
            "Series-connected rectifier bridges need the highest applicable RMS AC voltage "
            "before rectification at the relevant bridge",
        )
    return tuple(problems)


class DerivedSupplyScenario(FrozenModel):
    """What one enabled configuration resolves to against the approved rule package.

    Read-only, and recomputed rather than stored: nothing here is a user input, and nothing
    here may be copied into one. A configuration switched off stops producing a scenario and
    the manual fields take over unchanged - the last derived numbers are not left behind in
    them.
    """

    configuration_id: UUID
    configuration_name: str
    system_voltage_for_impulse_v: DecimalValue
    system_voltage_for_tov_v: DecimalValue | None
    source_ovc: OvervoltageCategory | None
    rated_impulse_v: DecimalValue
    temporary_overvoltage_rms_v: DecimalValue | None
    temporary_overvoltage_peak_v: DecimalValue | None
    warnings: tuple[CalculationWarning, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()
    source_rule_ids: tuple[str, ...] = ()


class SupplyDerivationBlockCode(StrEnum):
    """Why one enabled configuration produced no scenario.

    Every member names something that was missing or could not be resolved. None of them is a
    reason to substitute a value: a blocked configuration contributes nothing to the governing
    stress and says so, rather than contributing a guess that would look derived.
    """

    #: The row is not complete enough to derive from - see
    #: :func:`validate_supply_configurations`, whose problem is quoted in the message.
    CONFIGURATION_INCOMPLETE = "configuration_incomplete"
    #: The arrangement has no counterpart in the vocabulary the active package's resolution
    #: rule declares, so the question cannot even be asked of it.
    UNSUPPORTED_ARRANGEMENT = "unsupported_arrangement"
    #: The rule was asked and stated nothing for this arrangement.
    SYSTEM_VOLTAGE_UNRESOLVED = "system_voltage_unresolved"
    #: The arrangement covers several states the rule distinguishes, and they do not agree.
    AMBIGUOUS_ARRANGEMENT = "ambiguous_arrangement"
    #: The rule named the measure that applies and the configuration states no voltage for it.
    MISSING_DECLARED_VOLTAGE = "missing_declared_voltage"
    #: The lookup's own table carries no column for the category or basis being asked about.
    MISSING_LOOKUP_COLUMN = "missing_lookup_column"
    #: The lookup was attempted and the package refused it - an out-of-range system voltage,
    #: an absent cell, or an axis the reviewed table does not carry.
    LOOKUP_REFUSED = "lookup_refused"


class SupplyDerivationBlock(FrozenModel):
    """One reason a configuration produced no derived scenario."""

    configuration_id: UUID
    code: SupplyDerivationBlockCode
    message: str
    semantic_rule_id: str | None = None


class UnresolvedSupplyScenario(FrozenModel):
    """An enabled configuration that could not be derived, and everything that stopped it.

    Kept beside the derived scenarios rather than raised, so one bad row does not hide the
    others and a reader sees the whole set at once. ``trace_steps`` holds whatever was resolved
    before the derivation stopped, which is what makes a partial failure diagnosable.
    """

    configuration_id: UUID
    configuration_name: str
    blocks: tuple[SupplyDerivationBlock, ...]
    trace_steps: tuple[TraceStep, ...] = ()


class GoverningSupplyStress(FrozenModel):
    """The worst impulse and the worst temporary overvoltage across every enabled scenario.

    The three governing values are selected independently and may be governed by different
    configurations, which is why each carries its own governing id. Every non-governing
    scenario is kept: a reader checking the result has to be able to see what it was worse
    than. So is every configuration that produced no scenario at all.

    The temporary overvoltage keeps its RMS and peak values separately, because they are two
    measures of one quantity that the package states independently, and a consumer downstream
    needs whichever its own verification rule asks for.
    """

    impulse_v: DecimalValue | None = None
    impulse_configuration_id: UUID | None = None
    tov_peak_v: DecimalValue | None = None
    tov_configuration_id: UUID | None = None
    tov_rms_v: DecimalValue | None = None
    tov_rms_configuration_id: UUID | None = None
    scenarios: tuple[DerivedSupplyScenario, ...] = ()
    unresolved: tuple[UnresolvedSupplyScenario, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()

    @model_validator(mode="after")
    def _requires_an_owner_for_each_governing_value(self) -> Self:
        derived = {scenario.configuration_id for scenario in self.scenarios}
        for value, owner, label in (
            (self.impulse_v, self.impulse_configuration_id, "impulse"),
            (self.tov_peak_v, self.tov_configuration_id, "temporary overvoltage"),
            (self.tov_rms_v, self.tov_rms_configuration_id, "temporary overvoltage rms"),
        ):
            if (value is None) != (owner is None):
                raise ValueError(f"A governing {label} and its configuration are recorded together")
            if owner is not None and owner not in derived:
                raise ValueError(f"The governing {label} names a configuration with no scenario")
        return self


class ImpulseOverrideBasis(StrEnum):
    """Why a pair's impulse stress differs from the value derived and propagated to it.

    There is deliberately no generic member: an override whose basis nobody can name is not
    traceable, and the reduction routes the rule package carries are each named here.
    """

    SPD_OR_TRANSIENT_LIMITER = "spd_or_transient_limiter"
    HIGH_FREQUENCY_ISOLATION_TRANSFORMER = "high_frequency_isolation_transformer"
    VERIFIED_CIRCUIT_CHARACTERISTIC = "verified_circuit_characteristic"
    CONSERVATIVE_INCREASE = "conservative_increase"


class ReductionVerificationMethod(StrEnum):
    """How the claim behind an override was shown. No generic member, for the same reason."""

    TEST = "test"
    SIMULATION = "simulation"
    CALCULATION = "calculation"


class VerifiedImpulseOverride(FrozenModel):
    """One location-specific impulse value a user takes responsibility for.

    It applies to the pair or location it names and to nothing else - never to the nets
    upstream of it, and never to the barrier whose attenuation is being claimed. Clearing it
    restores the derived and propagated value; it is never copied into a manual field on the
    way out.
    """

    value_v: PositiveDecimal
    basis: ImpulseOverrideBasis
    verification_method: ReductionVerificationMethod
    justification: str
    evidence_reference: str
    affected_location: str
    transformer_frequency_hz: PositiveDecimal | None = None

    @property
    def is_reduction(self) -> bool:
        """Whether this override claims less stress than was derived.

        A conservative increase is the one basis that does not, which is why it is the one
        basis that needs no reduction evidence.
        """

        return self.basis is not ImpulseOverrideBasis.CONSERVATIVE_INCREASE

    @model_validator(mode="after")
    def _requires_evidence_for_a_reduction(self) -> Self:
        if not self.justification.strip():
            raise ValueError("An impulse override records why it applies")
        if not self.affected_location.strip():
            # Unconditional, including for an increase: an override that identifies no
            # location applies to everything, which is the one thing it must never do.
            raise ValueError("An impulse override names the pair or location it applies to")
        if self.is_reduction and not self.evidence_reference.strip():
            raise ValueError("A verified reduction needs an evidence reference")
        transformer = self.basis is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER
        if transformer and self.transformer_frequency_hz is None:
            raise ValueError("A high-frequency isolation transformer basis needs its frequency")
        if not transformer and self.transformer_frequency_hz is not None:
            raise ValueError(
                "Only a high-frequency isolation transformer basis carries a transformer frequency"
            )
        return self


__all__ = [
    "BRIDGE_SYSTEM_VOLTAGE_MEASURE",
    "MAINS_SUPPLY_KINDS",
    "PHASELESS_SUPPLY_KINDS",
    "DeclaredSystemVoltage",
    "DerivedSupplyScenario",
    "EarthingArrangement",
    "GoverningSupplyStress",
    "ImpulseOverrideBasis",
    "InputTopology",
    "OvervoltageCategory",
    "PhaseSystem",
    "ReductionVerificationMethod",
    "SupplyConfiguration",
    "SupplyConfigurationProblem",
    "SupplyConfigurationProblemCode",
    "SupplyDerivationBlock",
    "SupplyDerivationBlockCode",
    "SupplyKind",
    "UnresolvedSupplyScenario",
    "VerifiedImpulseOverride",
    "normalized_configuration_name",
    "validate_supply_configurations",
]
