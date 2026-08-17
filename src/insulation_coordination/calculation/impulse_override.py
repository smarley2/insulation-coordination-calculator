"""Resolves one verified impulse override against the pair it was recorded on.

An override is a user taking responsibility for a value that differs from the one derivation
and propagation produced. Three things follow from that, and this module is where all three
are enforced.

*It applies to one location and to nothing else.* An override arrives bound to a pair - see
:class:`PairImpulseOverride` - so an override that identifies no location cannot be
constructed, and one presented against a different pair is refused rather than applied. It
never reaches the nets upstream of that pair, and never the barrier whose attenuation is
being claimed.

*A claim the active package will not support is refused, not weakened.* A high-frequency
transformer attenuation is a specific permission the package either states for the circuit,
the frequency and the evidence in hand or does not. It is not the ordinary one-level transfer
a verified barrier already gives, and verified isolation on its own buys nothing extra here.
A refusal is typed and the derived value stands.

*A reduction claimed on a surge-protective device carries obligations that outlive it.* The
warning naming them is recomputed from the override, so it is present exactly while the
override is, and there is nothing to dismiss. Where the device sits inside the equipment, the
dedicated monitoring type test it depends on is recorded as a
:class:`SpdMonitoringDependency` for issue #37 to generate - recorded here, never generated
here.

No IEC value appears in this module. The identifiers below are the neutral vocabulary the
package declares for these rules' inputs and outputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from insulation_coordination.calculation.supply_rules import SupplyRuleSet
from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    DecisiveVoltageClass,
    InsulationType,
    NetClassType,
)
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.project import NetClass, PairCase, Project
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import DecisionRule, DecisionValue, SourceReference
from insulation_coordination.domain.supply import (
    ImpulseOverrideBasis,
    ReductionVerificationMethod,
    SpdDevicePlacement,
    VerifiedImpulseOverride,
)
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    barrier_between,
    domain_for_net,
)
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.rules.evaluator import (
    DecisionResult,
    EvaluationError,
    evaluate_decision,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_VOLTAGE_UNIT: Final = "V"

#: The trace identifier of this application's own override arithmetic. Not a semantic rule id:
#: substituting a user's verified value for a derived one is this application's bookkeeping,
#: and labelling it with a package identifier would credit the package with a decision no
#: clause made.
OVERRIDE_TRACE_ID: Final = "supply.verified_override"

#: The warning every surge-protective-device reduction carries, and the one the transformer
#: attenuation carries when it is granted. Codes rather than prose at the call sites, so a
#: report can group them and issue #29 can hang guidance off them without matching a message.
SPD_REDUCTION_WARNING: Final = "supply_spd_reduction_obligations"
SPD_MONITORING_UNSTATED_WARNING: Final = "supply_spd_monitoring_unstated"
HF_TRANSFORMER_WARNING: Final = "supply_hf_transformer_attenuation"
OVERRIDE_ABOVE_DERIVED_WARNING: Final = "supply_override_above_derived"

#: This application's device placements in the package's own words.
_PLACEMENTS: Final[Mapping[SpdDevicePlacement, str]] = {
    SpdDevicePlacement.INTERNAL_TO_EQUIPMENT: "internal_to_pecs",
    SpdDevicePlacement.EXTERNAL_TO_EQUIPMENT: "external_to_pecs",
    SpdDevicePlacement.BUNDLED_WITH_EQUIPMENT: "bundled_external_to_pecs",
}

#: How a recorded verification method is offered to the attenuation rule. A method the rule
#: does not declare is refused by the evaluator, which is the answer being looked for: the
#: package states which showings it accepts and this application does not widen the list.
_EVIDENCE_KINDS: Final[Mapping[ReductionVerificationMethod, str]] = {
    ReductionVerificationMethod.TEST: "test",
    ReductionVerificationMethod.SIMULATION: "simulation",
    ReductionVerificationMethod.CALCULATION: "calculation",
}

#: Decisive voltage classes in increasing severity, used to pick the side of a pair the
#: attenuation permission has to hold for. Designations only.
_DVC_SEVERITY: Final[tuple[DecisiveVoltageClass, ...]] = (
    DecisiveVoltageClass.DVC_AS,
    DecisiveVoltageClass.DVC_B,
    DecisiveVoltageClass.DVC_C,
)


class PairImpulseOverride(FrozenModel):
    """One verified override, bound to the pair it was recorded against.

    The binding is structural rather than a convention a caller is trusted to follow: there is
    no way to hold an override without holding the pair it belongs to, so an override that
    applies to everything cannot be expressed. :attr:`VerifiedImpulseOverride.affected_location`
    stays the human description of *where at that pair*; this is the identity the resolution
    checks.
    """

    pair_id: UUID
    override: VerifiedImpulseOverride


class OverrideRefusalCode(StrEnum):
    """Why a recorded override was not applied. The derived value stands in every case."""

    #: The override belongs to another pair. It is never applied here, and never silently.
    WRONG_LOCATION = "wrong_location"
    #: A transformer attenuation was claimed where no verified galvanic barrier separates the
    #: two sides, or where one side is not a circuit at all.
    NO_VERIFIED_BARRIER = "no_verified_barrier"
    #: The decisive voltage class the attenuation rule is asked about has not been evaluated.
    CIRCUIT_CLASS_UNEVALUATED = "circuit_class_unevaluated"
    #: The pair's insulation class is not resolved, so the device rules cannot be asked.
    INSULATION_CLASS_UNRESOLVED = "insulation_class_unresolved"
    #: The recorded verification method is not a showing the active package accepts.
    EVIDENCE_KIND_UNSUPPORTED = "evidence_kind_unsupported"
    #: The package states nothing for this attenuation claim, so nothing permits it.
    ATTENUATION_UNSTATED = "attenuation_unstated"
    #: The package was asked and did not permit the claim.
    ATTENUATION_REFUSED = "attenuation_refused"
    #: The monitoring a device inside the equipment owes is not stated by the active package,
    #: so the dependency issue #37 has to consume cannot be recorded.
    MONITORING_UNSTATED = "monitoring_unstated"


class OverrideRefusal(FrozenModel):
    code: OverrideRefusalCode
    message: str
    semantic_rule_id: str | None = None


class SpdMonitoringDependency(FrozenModel):
    """The dedicated monitoring type test one reduction depends on.

    Recorded, never generated: issue #37 owns the test schedule and consumes this. The
    identifier in :attr:`required_type_test_semantic_id` is the one the package publishes for
    that test, so the two ends of the dependency name the same thing.
    """

    pair_id: UUID
    affected_location: str
    device_placement: SpdDevicePlacement
    device_degradable: bool
    monitoring_required: bool
    status_indication_required: bool
    #: What the monitoring route states a showing is accepted against, verbatim from the
    #: package's own output vocabulary. ``None`` where the route states nothing.
    verification_reference: str | None = None
    required_type_test_semantic_id: str = ids.TEST_INTERNAL_SPD_MONITORING
    monitoring_rule_ids: tuple[str, ...] = ()


class OverrideOutcome(FrozenModel):
    """What one recorded override did to a pair's impulse, and everything that followed.

    ``applied`` false with a populated ``refusals`` is the whole of the failure behaviour:
    there is no partially applied override and no weakened value. Clearing the override
    removes this object; the derived and propagated value is recomputed, never copied out of
    here into an input.
    """

    override: VerifiedImpulseOverride
    applied: bool
    effective_impulse_v: DecimalValue | None = None
    refusals: tuple[OverrideRefusal, ...] = ()
    spd_monitoring_dependency: SpdMonitoringDependency | None = None
    warnings: tuple[CalculationWarning, ...] = ()
    trace_steps: tuple[TraceStep, ...] = ()
    source_rule_ids: tuple[str, ...] = ()


def resolve_impulse_override(
    project: Project,
    pair: PairCase,
    bound: PairImpulseOverride,
    rules: SupplyRuleSet,
    *,
    derived_impulse_v: Decimal | None,
    insulation_type: InsulationType | None,
    mains_supplied: bool,
) -> OverrideOutcome:
    """Apply ``bound`` to ``pair``, or return the typed reasons it was not applied.

    ``derived_impulse_v`` is the governing pre-override value, kept only to say whether the
    override raises or lowers it; nothing here reads it to decide anything. ``insulation_type``
    is the pair's effective class and ``mains_supplied`` says which of the two reduction routes
    the pair's supply falls under - both are the caller's to resolve, because both are known to
    the propagation this module deliberately does not import.
    """

    resolution = _Resolution(project, pair, bound, rules, mains_supplied=mains_supplied)
    if bound.pair_id != pair.id:
        resolution.refuse(
            OverrideRefusalCode.WRONG_LOCATION,
            f"This override was recorded against another location "
            f"({bound.override.affected_location!r}) and does not apply to this pair.",
        )
        return resolution.outcome()

    basis = bound.override.basis
    if basis is ImpulseOverrideBasis.SPD_OR_TRANSIENT_LIMITER:
        resolution.resolve_device_reduction(insulation_type)
    elif basis is ImpulseOverrideBasis.HIGH_FREQUENCY_ISOLATION_TRANSFORMER:
        resolution.resolve_transformer_attenuation()

    if resolution.refusals:
        return resolution.outcome()
    resolution.apply(derived_impulse_v)
    return resolution.outcome()


class _Resolution:
    """One override's resolution in progress, collecting refusals, warnings and steps."""

    def __init__(
        self,
        project: Project,
        pair: PairCase,
        bound: PairImpulseOverride,
        rules: SupplyRuleSet,
        *,
        mains_supplied: bool,
    ) -> None:
        self.project = project
        self.pair = pair
        self.bound = bound
        self.override = bound.override
        self.rules = rules
        self.mains_supplied = mains_supplied
        self.refusals: list[OverrideRefusal] = []
        self.warnings: list[CalculationWarning] = []
        self.steps: list[TraceStep] = []
        self.rule_ids: list[str] = []
        self.dependency: SpdMonitoringDependency | None = None
        self.applied_value: Decimal | None = None
        #: Where the package stated the permission an applied override rests on, so the one
        #: numeric step this module produces cites a clause rather than nothing.
        self.permission_source: SourceReference | None = None

    # --- collection -------------------------------------------------------------------

    def refuse(
        self, code: OverrideRefusalCode, message: str, *, semantic_rule_id: str | None = None
    ) -> None:
        self.refusals.append(
            OverrideRefusal(code=code, message=message, semantic_rule_id=semantic_rule_id)
        )

    def warn(self, code: str, message: str, *, semantic_rule_id: str | None = None) -> None:
        self.warnings.append(
            CalculationWarning(code=code, message=message, semantic_rule_id=semantic_rule_id)
        )

    def note_rule(self, rule_id: str) -> None:
        if rule_id not in self.rule_ids:
            self.rule_ids.append(rule_id)

    def ask(
        self, rule: DecisionRule, inputs: dict[str, Decimal | str | bool]
    ) -> DecisionResult | None:
        """One decision, with an input the rule does not declare treated as no answer.

        The evaluator raises for a categorical value outside a declared vocabulary, which is
        exactly the case of a verification method the package does not accept. Turning it into
        ``None`` here keeps every "the package will not answer this" on one path.
        """

        self.note_rule(rule.id)
        try:
            return evaluate_decision(rule, inputs)
        except EvaluationError:
            return None

    def outcome(self) -> OverrideOutcome:
        return OverrideOutcome(
            override=self.override,
            applied=self.applied_value is not None,
            effective_impulse_v=self.applied_value,
            refusals=tuple(self.refusals),
            spd_monitoring_dependency=self.dependency,
            warnings=tuple(self.warnings),
            trace_steps=tuple(self.steps),
            source_rule_ids=tuple(self.rule_ids),
        )

    def apply(self, derived_impulse_v: Decimal | None) -> None:
        value = self.override.value_v
        self.applied_value = value
        substituted = f"{value} {_VOLTAGE_UNIT}"
        if derived_impulse_v is not None:
            substituted = f"{derived_impulse_v} {_VOLTAGE_UNIT} -> {substituted}"
            if self.override.is_reduction and value > derived_impulse_v:
                self.warn(
                    OVERRIDE_ABOVE_DERIVED_WARNING,
                    f"This override is recorded on a reduction basis but states "
                    f"{value} {_VOLTAGE_UNIT}, above the {derived_impulse_v} "
                    f"{_VOLTAGE_UNIT} derived for this pair.",
                )
        self.steps.append(
            TraceStep(
                semantic_rule_id=OVERRIDE_TRACE_ID,
                operation="verified_override",
                symbolic="U_imp(effective)",
                substituted=substituted,
                inputs=(),
                source_reference=self.permission_source,
                output=Quantity(value=value, unit=_VOLTAGE_UNIT),
                unrounded_value=value,
                reason=(
                    f"a verified {self.override.basis.value} override applies at "
                    f"{self.override.affected_location}, shown by "
                    f"{self.override.verification_method.value}"
                ),
            )
        )

    # --- surge-protective device ------------------------------------------------------

    def resolve_device_reduction(self, insulation_type: InsulationType | None) -> None:
        """The obligations a reduction claimed on a limiting device carries.

        The warning is unconditional, because all three obligations follow from the basis
        alone. What the package is asked for is the monitoring that follows from *this*
        device: where it sits and whether it degrades. Inside the equipment those answers are
        load bearing - they are the dependency issue #37 consumes - so a package that states
        nothing there refuses the override rather than leaving the obligation unrecorded.
        """

        placement = self.override.spd_device_placement
        degradable = self.override.spd_device_degradable
        assert placement is not None and degradable is not None  # the model requires both
        internal = placement is SpdDevicePlacement.INTERNAL_TO_EQUIPMENT
        self.warn(
            SPD_REDUCTION_WARNING,
            (
                f"This reduction rests on a {placement.value} transient limiter. It must be "
                "verified by the impulse withstand test; a limiter that degrades in service "
                "must be monitored and must indicate its own failure; and a limiter inside "
                "the equipment used for an overvoltage-category or clearance reduction needs "
                f"the dedicated monitoring type test recorded under "
                f"{ids.TEST_INTERNAL_SPD_MONITORING}. The warning stands while the override "
                "does."
            ),
            semantic_rule_id=ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
        )
        if insulation_type is None:
            self.refuse(
                OverrideRefusalCode.INSULATION_CLASS_UNRESOLVED,
                "The monitoring rules are asked about the insulation class of the pair, and "
                "neither the pair nor the project defaults resolve one.",
            )
            return

        monitoring = self.ask(
            self.rules.spd_reduction.monitoring,
            {
                "device_placement": _PLACEMENTS[placement],
                "insulation_class": insulation_type.value,
                "device_degradable": degradable,
                "part_of_category_reduction": True,
            },
        )
        route_id = self.rules.spd_reduction.monitoring.id
        if monitoring is None or monitoring.status != "matched":
            if internal:
                self.refuse(
                    OverrideRefusalCode.MONITORING_UNSTATED,
                    "The active package states no monitoring obligation for a limiter inside "
                    "the equipment, so the type test this reduction depends on cannot be "
                    "recorded.",
                    semantic_rule_id=route_id,
                )
            else:
                self.warn(
                    SPD_MONITORING_UNSTATED_WARNING,
                    "The active package states no monitoring obligation for a limiter in this "
                    "placement. Nothing here concludes that none is owed.",
                    semantic_rule_id=route_id,
                )
            return

        required = _boolean(monitoring.values, "monitoring_required") or False
        indication = _boolean(monitoring.values, "status_indication_required") or False
        reference = _categorical(monitoring.values, "verification_reference")
        rule_ids = [route_id]

        if degradable:
            device_route = (
                self.rules.spd_reduction.mains_device_monitoring
                if self.mains_supplied
                else self.rules.spd_reduction.non_mains_device_monitoring
            )
            if device_route is None:
                self.refuse(
                    OverrideRefusalCode.MONITORING_UNSTATED,
                    "This limiter degrades in service and the active package's reduction "
                    "clause states nothing about what such a device owes. Nothing here "
                    "concludes that nothing is owed.",
                    semantic_rule_id=ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
                )
                return
            device = self.ask(device_route, {"device_degradable": True})
            if device is None or device.status != "matched":
                self.refuse(
                    OverrideRefusalCode.MONITORING_UNSTATED,
                    "The active package's reduction clause was asked about a limiter that "
                    "degrades in service and stated nothing.",
                    semantic_rule_id=device_route.id,
                )
                return
            required = required or (_boolean(device.values, "monitoring_required") or False)
            indication = indication or (
                _boolean(device.values, "status_indication_required") or False
            )
            rule_ids.append(device_route.id)

        if internal:
            self.dependency = SpdMonitoringDependency(
                pair_id=self.pair.id,
                affected_location=self.override.affected_location,
                device_placement=placement,
                device_degradable=degradable,
                monitoring_required=required,
                status_indication_required=indication,
                verification_reference=reference,
                monitoring_rule_ids=tuple(rule_ids),
            )

    # --- high-frequency isolation transformer -----------------------------------------

    def resolve_transformer_attenuation(self) -> None:
        """The attenuation permission, or the typed reason there is none.

        Every gate the issue names is here and every one of them refuses: a verified galvanic
        barrier between the two sides, a circuit class the rule permits, a frequency it
        accepts, an evidence kind it declares, and the reference the model already required.
        This is deliberately not the ordinary one-level transfer a verified barrier gives on
        its own - that has already been applied by propagation, and verified isolation buys
        nothing further without this permission.
        """

        circuits = self._pair_circuits()
        barrier = self._verified_barrier()
        if barrier is None:
            self.refuse(
                OverrideRefusalCode.NO_VERIFIED_BARRIER,
                "A high-frequency transformer attenuation is claimed across a verified "
                "galvanic barrier, and no verified barrier separates this pair's domains.",
                semantic_rule_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
            )
            return
        severest = _severest_class(circuits)
        if severest is None:
            self.refuse(
                OverrideRefusalCode.CIRCUIT_CLASS_UNEVALUATED,
                "The attenuation rule is asked about the decisive voltage class of the "
                "circuits either side, and this pair has one that is not evaluated.",
                semantic_rule_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
            )
            return

        frequency = self.override.transformer_frequency_hz
        assert frequency is not None  # the model requires it for this basis
        result = self.ask(
            self.rules.hf_transformer_attenuation,
            {
                "circuit_dvc": severest.value,
                "transformer_frequency_hz": frequency,
                "isolation_provided": True,
                "attenuation_evidence_kind": _EVIDENCE_KINDS[self.override.verification_method],
            },
        )
        rule_id = self.rules.hf_transformer_attenuation.id
        if result is None:
            self.refuse(
                OverrideRefusalCode.EVIDENCE_KIND_UNSUPPORTED,
                f"The active package does not accept a "
                f"{self.override.verification_method.value} showing for this attenuation.",
                semantic_rule_id=rule_id,
            )
            return
        if result.status != "matched":
            self.refuse(
                OverrideRefusalCode.ATTENUATION_UNSTATED,
                f"The active package states nothing about a {frequency} Hz transformer "
                f"attenuating for a {severest.value} circuit.",
                semantic_rule_id=rule_id,
            )
            return
        if _boolean(result.values, "working_voltage_basis_permitted") is not True:
            self.refuse(
                OverrideRefusalCode.ATTENUATION_REFUSED,
                "The active package does not permit this attenuation claim.",
                semantic_rule_id=rule_id,
            )
            return

        evidence = _categorical(result.values, "required_evidence_kinds")
        self.warn(
            HF_TRANSFORMER_WARNING,
            (
                f"This value rests on a {frequency} Hz isolation transformer across the "
                f"verified barrier {barrier.id}, not on the one-level transfer that barrier "
                f"already gives. The claim holds only while the recorded evidence "
                f"({self.override.evidence_reference}) does"
                + (f", and the package requires {evidence}." if evidence else ".")
            ),
            semantic_rule_id=rule_id,
        )
        self.permission_source = result.source

    def _pair_circuits(self) -> tuple[NetClass, ...]:
        by_id = {net.id: net for net in self.project.net_classes}
        return tuple(
            net
            for net_id in (self.pair.net_a, self.pair.net_b)
            if (net := by_id.get(net_id)) is not None and net.net_type is NetClassType.CIRCUIT
        )

    def _verified_barrier(self) -> GalvanicBarrier | None:
        first = domain_for_net(self.project, self.pair.net_a)
        second = domain_for_net(self.project, self.pair.net_b)
        if first is None or second is None or first.id == second.id:
            return None
        barrier = barrier_between(self.project, first.id, second.id)
        verified = BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION
        return barrier if barrier is not None and barrier.status is verified else None


def _severest_class(circuits: tuple[NetClass, ...]) -> DecisiveVoltageClass | None:
    """The most severe evaluated class across a pair's circuits, or ``None`` if any is not.

    The most severe rather than either one: a permission that has to hold for this pair has to
    hold for the harder side of it. A pair with no circuit at all also answers ``None`` - there
    is no circuit for the permission to be about.
    """

    classes = tuple(net.decisive_voltage_class for net in circuits)
    if not classes or any(item is None or item not in _DVC_SEVERITY for item in classes):
        return None
    return max((item for item in classes if item is not None), key=_DVC_SEVERITY.index)


def _boolean(values: tuple[DecisionValue, ...], name: str) -> bool | None:
    return next((value.boolean for value in values if value.name == name), None)


def _categorical(values: tuple[DecisionValue, ...], name: str) -> str | None:
    return next((value.categorical for value in values if value.name == name), None)


__all__ = [
    "HF_TRANSFORMER_WARNING",
    "OVERRIDE_ABOVE_DERIVED_WARNING",
    "OVERRIDE_TRACE_ID",
    "SPD_MONITORING_UNSTATED_WARNING",
    "SPD_REDUCTION_WARNING",
    "OverrideOutcome",
    "OverrideRefusal",
    "OverrideRefusalCode",
    "PairImpulseOverride",
    "SpdMonitoringDependency",
    "resolve_impulse_override",
]
