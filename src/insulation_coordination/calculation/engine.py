from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import model_validator

from insulation_coordination.calculation.clearance import (
    CalculationError,
    CalculationRangeError,
    CandidateOmission,
    DistanceCandidate,
    RequiredStressError,
    RuleMappingError,
    RulePackageValidationError,
    UnsupportedCaseError,
    _calculate_clearance,
    _require_valid_rule_package,
)
from insulation_coordination.calculation.creepage import _calculate_creepage
from insulation_coordination.calculation.high_frequency import (
    PART4_FREQUENCY_THRESHOLD_HZ,
    FieldIteration,
    _calculate_high_frequency_candidates,
    apply_a2_altitude_correction,
)
from insulation_coordination.calculation.impulse_override import PairImpulseOverride
from insulation_coordination.calculation.stress_propagation import (
    DomainStressMap,
    EffectivePairStressResolution,
    TemporaryOvervoltageSource,
    propagate_impulse_to_domains,
    resolve_pair_stresses,
)
from insulation_coordination.calculation.supply_rules import SupplyRuleSet, read_supply_rules
from insulation_coordination.calculation.supply_stress import SupplyStressService
from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    FrozenModel,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
)
from insulation_coordination.domain.quantities import DecimalValue, PositiveDecimal
from insulation_coordination.domain.rules import Maximum, RulePackage, SourceReference, Variable
from insulation_coordination.domain.supply import GoverningSupplyStress
from insulation_coordination.domain.trace import CalculationWarning, Quantity, TraceStep
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

CALCULATION_ENGINE_VERSION = "pcb-annex-gh-3"

INNER_LAYER_POLLUTION_DEGREE = 1
"""Inner printed-wiring layers are dimensioned in pollution degree 1."""

SUPERSEDED_ENTRY_WARNING = "supply_derived_stress_supersedes_entry"
"""A derived stress replaced a lower value somebody entered. Never silently: this says so."""

ENTRY_EXCEEDS_DERIVED_WARNING = "supply_entry_exceeds_derived_stress"
"""An entered stress is more severe than the derived one, so the entry is what governs."""

__all__ = [
    "CALCULATION_ENGINE_VERSION",
    "ENTRY_EXCEEDS_DERIVED_WARNING",
    "INNER_LAYER_POLLUTION_DEGREE",
    "SUPERSEDED_ENTRY_WARNING",
    "CalculationError",
    "CalculationRangeError",
    "CalculationTrace",
    "CalculationWarning",
    "DistanceCandidate",
    "EffectiveInputSnapshot",
    "PairResult",
    "RequiredStressError",
    "RuleMappingError",
    "RulePackageValidationError",
    "SupplyDerivation",
    "UnsupportedCaseError",
    "VerificationRequirement",
    "calculate_pair",
    "calculate_project_pair",
    "derive_project_supply",
    "resolve_supply_effective_case",
]


class VerificationRequirement(FrozenModel):
    code: str
    message: str
    semantic_rule_id: str | None = None
    source_reference: SourceReference | None = None


class CalculationTrace(FrozenModel):
    insulation_type: InsulationType
    rule_package_id: UUID
    rule_package_version: str
    rule_package_sha256: str
    calculation_engine_version: str
    used_part4: bool
    pre_altitude_clearance_mm: DecimalValue
    altitude_correction_applied: bool
    hf_iterations: tuple[FieldIteration, ...]
    clearance_candidates: tuple[DistanceCandidate, ...]
    creepage_candidates: tuple[DistanceCandidate, ...]
    omissions: tuple[CandidateOmission, ...]
    governing_clearance_candidate_id: str
    governing_clearance_reason: str
    governing_creepage_candidate_id: str
    governing_creepage_reason: str
    steps: tuple[TraceStep, ...]
    warnings: tuple[CalculationWarning, ...] = ()
    verification_requirements: tuple[VerificationRequirement, ...] = ()

    @property
    def semantic_rule_ids(self) -> tuple[str, ...]:
        ordered = (
            *(
                rule_id
                for candidate in (
                    *self.clearance_candidates,
                    *self.creepage_candidates,
                )
                for rule_id in (
                    candidate.semantic_rule_id,
                    candidate.mapping_id,
                    candidate.formula_id,
                )
                if rule_id is not None
            ),
            *(step.semantic_rule_id for step in self.steps),
        )
        return tuple(dict.fromkeys(ordered))


class EffectiveInputSnapshot(FrozenModel):
    """Immutable calculation inputs, excluding pair identity and display metadata."""

    voltages: PairVoltages
    frequency_hz: EffectiveValue[Decimal | None]
    impulse_v: EffectiveValue[Decimal | None]
    insulation_type: EffectiveValue[InsulationType | None]
    field_condition: EffectiveValue[FieldCondition | None]
    electrode_radius_mm: EffectiveValue[Decimal | None]
    altitude_m: EffectiveValue[Decimal | None]
    pollution_degree: EffectiveValue[int | None]
    construction_type: EffectiveValue[ConstructionType | None]
    cti_or_material_group: EffectiveValue[str | None]
    conventional_construction_assumptions: EffectiveValue[tuple[str, ...] | None]


class PairResult(FrozenModel):
    pair_id: UUID
    pair_key: str
    rule_package_id: UUID
    rule_package_version: str
    rule_package_sha256: str
    calculation_engine_version: str
    clearance_mm: DecimalValue
    creepage_mm: DecimalValue
    inner_clearance_mm: DecimalValue
    inner_creepage_mm: DecimalValue
    effective_inputs: EffectiveInputSnapshot
    trace: CalculationTrace
    warnings: tuple[CalculationWarning, ...] = ()
    verification_requirements: tuple[VerificationRequirement, ...] = ()

    @model_validator(mode="after")
    def _matches_trace_advisories(self) -> Self:
        if self.warnings != self.trace.warnings:
            raise ValueError("result warnings must match trace warnings")
        if self.verification_requirements != self.trace.verification_requirements:
            raise ValueError(
                "result verification requirements must match trace verification requirements"
            )
        return self


class SupplyDerivation(FrozenModel):
    """One project's supply stresses, derived once and read by every pair of it.

    Held apart from the pair calculation because deriving each enabled arrangement's scenario
    and carrying it across the galvanic domains are questions about the project, asked once.
    Only the last stage is per pair: which of those stresses reaches this insulation, and what
    a verified override recorded at it makes of them.
    """

    rules: SupplyRuleSet
    governing: GoverningSupplyStress
    domain_stresses: DomainStressMap


def derive_project_supply(project: Project, rules: RulePackage) -> SupplyDerivation | None:
    """``project``'s derived supply stresses, or ``None`` when it enables no arrangement.

    ``None`` is the state every project saved before this feature existed is in, and it is the
    whole of the guarantee that they are unaffected: no supply rule is read at all, so a
    package carrying none cannot block them, and every pair is dimensioned from exactly the
    stresses it was entered with.

    A project that does enable one is derived against the active package, which raises
    :class:`~insulation_coordination.calculation.supply_rules.SupplyRulesUnavailable` if it
    cannot answer. That refusal is deliberate: a project asking for a derivation and getting a
    guess instead is the one outcome worse than being told it cannot have one.
    """

    if not any(item.enabled for item in project.supply_configurations):
        return None
    supply_rules = read_supply_rules(rules)
    governing = SupplyStressService().derive_all(project.supply_configurations, supply_rules)
    return SupplyDerivation(
        rules=supply_rules,
        governing=governing,
        domain_stresses=propagate_impulse_to_domains(project, governing.scenarios, supply_rules),
    )


def resolve_supply_effective_case(
    project: Project,
    pair: PairCase,
    supply: SupplyDerivation | None,
) -> tuple[EffectiveCase, EffectivePairStressResolution | None]:
    """The inputs one pair is dimensioned from, and the supply resolution behind them.

    With no derivation this is exactly ``resolve_effective_case``, which is what makes an
    existing project's numbers unchanged rather than merely unlikely to change.
    """

    effective = resolve_effective_case(project.defaults, pair)
    if supply is None:
        return effective, None
    override = (
        None
        if pair.impulse_override is None
        else PairImpulseOverride(pair_id=pair.id, override=pair.impulse_override)
    )
    resolution = resolve_pair_stresses(
        project, pair, supply.domain_stresses, supply.rules, override=override
    )
    return _with_supply_stresses(effective, resolution)


def calculate_project_pair(
    project: Project,
    pair: PairCase,
    rules: RulePackage,
    *,
    supply: SupplyDerivation | None = None,
) -> PairResult:
    """One pair of ``project``, dimensioned from its derived supply stresses where it has any."""

    effective, resolution = resolve_supply_effective_case(project, pair, supply)
    return calculate_pair(effective, rules, supply=resolution)


def _with_supply_stresses(
    effective: EffectiveCase,
    resolution: EffectivePairStressResolution,
) -> tuple[EffectiveCase, EffectivePairStressResolution]:
    """Combine the resolved supply stresses with one pair's entered inputs, most severe first.

    A derived stress and an entered one are two answers to the same question, and the pair is
    dimensioned from whichever is worse - the arithmetic IEC 62477-1:2022 4.4.7.1.6, 4.4.7.2.1,
    4.4.7.2.3, 4.4.7.2.4 and 4.4.7.2.5 b) each ask for. So the derived figure governs only
    where it is the more severe of the two, and an entry above it stands: nothing here may
    lower a pair below what the engineer asked for. The pipeline determines the derived
    stresses after the entered ones, which is an order of processing and not of precedence.

    The impulse handed over is :attr:`verified_effective_impulse_v`, which is untreated: the
    reinforced treatment is the clearance engine's and is applied there, once, immediately
    before the table is read. It also already carries any reduction recorded as a verified
    override, which is why an engineer who wants that benefit has to clear a stale entry
    sitting above it - and why the warning below says so. The temporary overvoltage is
    considered only where the derivation is what governs it; where the pair's own entry does,
    the entry is already in these inputs and nothing needs combining.

    Either outcome is reported whenever the two disagree. A derived figure quietly displacing
    something a user typed is indistinguishable, from the outside, from the application losing
    it, and an entry quietly holding a derived figure down is no better.
    """

    updates: dict[str, object] = {}
    warnings: list[CalculationWarning] = []
    impulse = resolution.verified_effective_impulse_v
    if impulse is not None:
        entered = effective.impulse_v
        warning = _disagreement(entered.provenance.value, "impulse", entered.value, impulse)
        if warning is not None:
            warnings.append(warning)
        if entered.value is None or entered.value < impulse:
            updates["impulse_v"] = EffectiveValue[PositiveDecimal | None](
                value=impulse, provenance=Provenance.DERIVED_SUPPLY
            )

    temporary = resolution.temporary_overvoltage
    if (
        temporary.source is TemporaryOvervoltageSource.DERIVED_MAINS
        and temporary.peak_v is not None
    ):
        entry = effective.voltages.temporary_overvoltage_peak_v
        stated = entry.value if entry.applicability is Applicability.APPLICABLE else None
        warning = _disagreement(
            "pair entry", "temporary overvoltage peak", stated, temporary.peak_v
        )
        if warning is not None:
            warnings.append(warning)
        if stated is None or stated < temporary.peak_v:
            updates["voltages"] = effective.voltages.model_copy(
                update={"temporary_overvoltage_peak_v": PairVoltage.applicable(temporary.peak_v)}
            )

    if not updates and not warnings:
        return effective, resolution
    return (
        effective.model_copy(update=updates),
        resolution.model_copy(update={"warnings": (*resolution.warnings, *tuple(warnings))}),
    )


def _disagreement(
    source: str, quantity: str, entered: Decimal | None, derived: Decimal
) -> CalculationWarning | None:
    """What to say about the two figures, or ``None`` where there is nothing to say.

    An absent entry and an agreeing one both leave the derived value governing unremarked.
    """

    if entered is None or entered == derived:
        return None
    if entered < derived:
        return CalculationWarning(
            code=SUPERSEDED_ENTRY_WARNING,
            message=(
                f"The {source} {quantity} of {entered} V is superseded by the {derived} V "
                "this project's supply configurations derive for this pair. A different value "
                "belongs in a verified override, where its evidence is recorded with it."
            ),
        )
    return CalculationWarning(
        code=ENTRY_EXCEEDS_DERIVED_WARNING,
        message=(
            f"The {source} {quantity} of {entered} V exceeds the {derived} V this project's "
            "supply configurations derive for this pair, so the entered value is what this "
            "pair is dimensioned from: the more severe of the two governs. Clear the entry to "
            "be dimensioned from the derived figure instead, including any reduction recorded "
            "against it as a verified override."
        ),
    )


def calculate_pair(
    effective: EffectiveCase,
    rules: RulePackage,
    *,
    supply: EffectivePairStressResolution | None = None,
) -> PairResult:
    """Dimension one pair from ``effective``, unchanged by anything ``supply`` says.

    ``supply`` is the resolution the stresses in ``effective`` already came from, and is read
    only for what it has to report: its trace steps and its warnings. Nothing in it is
    substituted here - by the time this is called the substitution has happened - so a caller
    that passes none gets exactly the calculation this function always performed.
    """

    _require_valid_rule_package(rules)
    kind = effective.insulation_type.value
    if kind is None:
        raise RequiredStressError("insulation_type is required for a Part 1 calculation")
    frequency = _validate_calculation_scope(effective)

    clearance = _calculate_clearance(effective, rules)
    base_periodic_governing = _governing(
        tuple(
            candidate for candidate in clearance.candidates if candidate.candidate_id != "impulse"
        )
    )
    used_part4 = frequency > PART4_FREQUENCY_THRESHOLD_HZ
    high_frequency = (
        _calculate_high_frequency_candidates(
            effective,
            base_periodic_governing,
            rules,
        )
        if used_part4
        else None
    )
    clearance_candidates = (
        clearance.candidates
        if high_frequency is None
        else clearance.candidates + high_frequency.clearance_candidates
    )
    clearance_governing = _governing(clearance_candidates)
    pre_altitude_clearance = clearance_governing.distance_mm
    clearance_step = _maximum_step(
        semantic_rule_id="clearance.maximum",
        candidates=clearance_candidates,
        reason=f"{clearance_governing.candidate_id} governs clearance",
    )
    altitude = apply_a2_altitude_correction(
        effective,
        pre_altitude_clearance,
        rules,
    )
    final_clearance = altitude.clearance_mm

    creepage = _calculate_creepage(effective, final_clearance, rules)
    creepage_candidates = (
        creepage.candidates
        if high_frequency is None
        else creepage.candidates + high_frequency.creepage_candidates
    )
    creepage_governing = _governing(creepage_candidates)
    final_creepage = creepage_governing.distance_mm
    creepage_reason = (
        "final clearance governs creepage"
        if creepage_governing.candidate_id == "clearance_floor"
        else "calculated creepage governs"
    )
    creepage_step = _maximum_step(
        semantic_rule_id="part1.creepage.clearance_floor",
        candidates=creepage_candidates,
        reason=creepage_reason,
    )

    steps = (
        # First, because the supply derivation is what produced the stresses everything after
        # it reads. A reader following the trace top to bottom meets the source before the
        # dimension it led to.
        *(() if supply is None else supply.trace_steps),
        *(() if high_frequency is None else high_frequency.applicability_steps),
        *(step for candidate in clearance.candidates for step in candidate.steps),
        *(
            step
            for candidate in (() if high_frequency is None else high_frequency.clearance_candidates)
            for step in candidate.steps
        ),
        clearance_step,
        *altitude.steps,
        *(step for candidate in creepage_candidates for step in candidate.steps),
        creepage_step,
    )
    rule_package_sha256 = rules.package_sha256
    if rule_package_sha256 is None:
        raise CalculationError("validated rule package unexpectedly has no SHA-256 identity")
    warnings, verification_requirements = _advisories(
        effective,
        clearance_candidates,
        creepage_candidates,
        steps,
        rules,
    )
    if supply is not None:
        warnings = (*supply.warnings, *warnings)
    inner = _inner_layer_result(effective, rules)
    return PairResult(
        pair_id=effective.id,
        pair_key=effective.key,
        rule_package_id=rules.manifest.package_id,
        rule_package_version=rules.manifest.version,
        rule_package_sha256=rule_package_sha256,
        calculation_engine_version=CALCULATION_ENGINE_VERSION,
        clearance_mm=final_clearance,
        creepage_mm=final_creepage,
        inner_clearance_mm=final_clearance if inner is None else inner.clearance_mm,
        inner_creepage_mm=final_creepage if inner is None else inner.creepage_mm,
        effective_inputs=_snapshot_effective_inputs(effective),
        warnings=warnings,
        verification_requirements=verification_requirements,
        trace=CalculationTrace(
            insulation_type=kind,
            rule_package_id=rules.manifest.package_id,
            rule_package_version=rules.manifest.version,
            rule_package_sha256=rule_package_sha256,
            calculation_engine_version=CALCULATION_ENGINE_VERSION,
            used_part4=used_part4,
            pre_altitude_clearance_mm=pre_altitude_clearance,
            altitude_correction_applied=altitude.applied,
            hf_iterations=(() if high_frequency is None else high_frequency.iterations),
            clearance_candidates=clearance_candidates,
            creepage_candidates=creepage_candidates,
            omissions=clearance.omissions + creepage.omissions,
            governing_clearance_candidate_id=clearance_governing.candidate_id,
            governing_clearance_reason=clearance_step.reason,
            governing_creepage_candidate_id=creepage_governing.candidate_id,
            governing_creepage_reason=creepage_step.reason,
            steps=steps,
            warnings=warnings,
            verification_requirements=verification_requirements,
        ),
    )


def _inner_layer_result(effective: EffectiveCase, rules: RulePackage) -> PairResult | None:
    """Recalculate the pair in pollution degree 1 for its inner printed-wiring layers.

    Inner layers are sealed inside the board, so their creepage distances are
    dimensioned as creepage in pollution degree 1 and their clearances as
    clearances in air for that same condition. A pair already in pollution
    degree 1 needs no second calculation; ``None`` reports that its outer
    distances also apply to its inner layers.
    """
    if effective.pollution_degree.value == INNER_LAYER_POLLUTION_DEGREE:
        return None
    inner_case = effective.model_copy(
        update={
            "pollution_degree": EffectiveValue[int | None](
                value=INNER_LAYER_POLLUTION_DEGREE,
                provenance=effective.pollution_degree.provenance,
            )
        }
    )
    # The recursion stops at one level: inner_case is already pollution degree 1.
    return calculate_pair(inner_case, rules)


def _snapshot_effective_inputs(effective: EffectiveCase) -> EffectiveInputSnapshot:
    return EffectiveInputSnapshot(
        voltages=effective.voltages,
        frequency_hz=effective.frequency_hz,
        impulse_v=effective.impulse_v,
        insulation_type=effective.insulation_type,
        field_condition=effective.field_condition,
        electrode_radius_mm=effective.electrode_radius_mm,
        altitude_m=effective.altitude_m,
        pollution_degree=effective.pollution_degree,
        construction_type=effective.construction_type,
        cti_or_material_group=effective.cti_or_material_group,
        conventional_construction_assumptions=effective.conventional_construction_assumptions,
    )


def _advisories(
    effective: EffectiveCase,
    clearance_candidates: tuple[DistanceCandidate, ...],
    creepage_candidates: tuple[DistanceCandidate, ...],
    steps: tuple[TraceStep, ...],
    rules: RulePackage,
) -> tuple[tuple[CalculationWarning, ...], tuple[VerificationRequirement, ...]]:
    warnings: list[CalculationWarning] = []
    requirements: list[VerificationRequirement] = []
    candidates = (*clearance_candidates, *creepage_candidates)

    field = effective.field_condition.value
    if field in (FieldCondition.HOMOGENEOUS, FieldCondition.APPROXIMATELY_HOMOGENEOUS):
        semantic_rule_id, source_reference = _advisory_context(
            candidates,
            steps,
            f"field={field.value}",
        )
        requirements.append(
            VerificationRequirement(
                code="FIELD_CONDITION_CONFIRMATION",
                message="Confirm field classification.",
                semantic_rule_id=semantic_rule_id,
                source_reference=source_reference,
            )
        )

    if field is FieldCondition.HOMOGENEOUS:
        f8_candidate = next(
            (
                candidate
                for candidate in clearance_candidates
                if candidate.formula_id == "iec60664-1:f8-clearance"
            ),
            None,
        )
        requirements.append(
            VerificationRequirement(
                code="WITHSTAND_TEST_REQUIRED",
                message="Case B homogeneous-field clearance requires withstand-test verification.",
                semantic_rule_id="iec60664-1:f8-withstand-test",
                source_reference=(
                    None if f8_candidate is None else _source_reference(f8_candidate.steps)
                ),
            )
        )

    periodic_pd_stresses = tuple(
        voltage.value
        for voltage in (
            effective.voltages.steady_state_peak_v,
            effective.voltages.recurring_peak_v,
        )
        if voltage.applicability is Applicability.APPLICABLE and voltage.value is not None
    )
    if (
        field is FieldCondition.INHOMOGENEOUS
        and periodic_pd_stresses
        and max(periodic_pd_stresses) >= Decimal(2500)
    ):
        f9 = next((table for table in rules.tables if table.id == "iec60664-1-f9"), None)
        warning = CalculationWarning(
            code="PARTIAL_DISCHARGE_REVIEW",
            message=(
                "At 2.5 kV peak and above, F.8 may not provide corona-free operation; "
                "review F.9 clearance or improve field distribution."
            ),
            semantic_rule_id="iec60664-1:f9-partial-discharge-advice",
            source_reference=None if f9 is None else f9.source,
        )
        warnings.append(warning)
        requirements.append(
            VerificationRequirement(
                code=warning.code,
                message=warning.message,
                semantic_rule_id=warning.semantic_rule_id,
                source_reference=warning.source_reference,
            )
        )

    return tuple(warnings), tuple(requirements)


def _advisory_context(
    candidates: tuple[DistanceCandidate, ...],
    steps: tuple[TraceStep, ...],
    marker: str,
) -> tuple[str | None, SourceReference | None]:
    for candidate in candidates:
        if marker in candidate.semantic_rule_id:
            return candidate.semantic_rule_id, _source_reference(candidate.steps)
    for step in steps:
        if marker in step.semantic_rule_id:
            return step.semantic_rule_id, _source_reference((step,))
    return None, None


def _source_reference(steps: tuple[TraceStep, ...]) -> SourceReference | None:
    for step in steps:
        if step.source_reference is not None:
            return step.source_reference
        if step.formula_source_reference is not None:
            return step.formula_source_reference
    return None


def _validate_calculation_scope(effective: EffectiveCase) -> Decimal:
    frequency = effective.frequency_hz.value
    if frequency is None:
        raise RequiredStressError(
            "frequency_hz is required in canonical Hz for a Part 1 calculation"
        )
    assumptions = effective.conventional_construction_assumptions.value
    if assumptions:
        raise UnsupportedCaseError(
            "conventional construction assumption flags are unsupported until an "
            "approved semantic mapping is provided: " + ", ".join(assumptions)
        )
    return frequency


def _governing(
    candidates: tuple[DistanceCandidate, ...],
) -> DistanceCandidate:
    if not candidates:
        raise CalculationError("calculation produced no distance candidates")
    return max(candidates, key=lambda candidate: candidate.distance_mm)


def _maximum_step(
    *,
    semantic_rule_id: str,
    candidates: tuple[DistanceCandidate, ...],
    reason: str,
) -> TraceStep:
    variables = {
        candidate.candidate_id: Quantity(value=candidate.distance_mm, unit="mm")
        for candidate in candidates
    }
    try:
        selected = evaluate_formula(
            Maximum(
                operands=tuple(Variable(name=candidate.candidate_id) for candidate in candidates)
            ),
            variables,
            {},
        )
    except EvaluationError as error:
        raise CalculationError(f"distance maximum selection failed: {error}") from error
    return selected.steps[-1].model_copy(
        update={"semantic_rule_id": semantic_rule_id, "reason": reason}
    )
