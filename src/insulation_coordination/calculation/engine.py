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
    FieldIteration,
    _calculate_high_frequency_candidates,
    apply_a2_altitude_correction,
)
from insulation_coordination.domain.enums import (
    Applicability,
    ConstructionType,
    FieldCondition,
    InsulationType,
)
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    FrozenModel,
    PairVoltages,
)
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import Maximum, RulePackage, SourceReference, Variable
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

CALCULATION_ENGINE_VERSION = "pcb-annex-gh-2"

__all__ = [
    "CALCULATION_ENGINE_VERSION",
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
    "UnsupportedCaseError",
    "VerificationRequirement",
    "calculate_pair",
]


class CalculationWarning(FrozenModel):
    code: str
    message: str
    semantic_rule_id: str | None = None
    source_reference: SourceReference | None = None


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


def calculate_pair(effective: EffectiveCase, rules: RulePackage) -> PairResult:
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
    used_part4 = frequency > Decimal(30000)
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
    return PairResult(
        pair_id=effective.id,
        pair_key=effective.key,
        rule_package_id=rules.manifest.package_id,
        rule_package_version=rules.manifest.version,
        rule_package_sha256=rule_package_sha256,
        calculation_engine_version=CALCULATION_ENGINE_VERSION,
        clearance_mm=final_clearance,
        creepage_mm=final_creepage,
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
