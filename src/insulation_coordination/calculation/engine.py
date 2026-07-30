from __future__ import annotations

from decimal import Decimal
from uuid import UUID

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
from insulation_coordination.domain.enums import InsulationType
from insulation_coordination.domain.project import EffectiveCase, FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import Maximum, RulePackage, Variable
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

CALCULATION_ENGINE_VERSION = "part1-1"

__all__ = [
    "CALCULATION_ENGINE_VERSION",
    "CalculationError",
    "CalculationRangeError",
    "CalculationTrace",
    "DistanceCandidate",
    "PairResult",
    "RequiredStressError",
    "RuleMappingError",
    "RulePackageValidationError",
    "UnsupportedCaseError",
    "calculate_pair",
]


class CalculationTrace(FrozenModel):
    insulation_type: InsulationType
    rule_package_id: UUID
    rule_package_version: str
    rule_package_sha256: str
    calculation_engine_version: str
    clearance_candidates: tuple[DistanceCandidate, ...]
    creepage_candidates: tuple[DistanceCandidate, ...]
    omissions: tuple[CandidateOmission, ...]
    governing_clearance_candidate_id: str
    governing_clearance_reason: str
    governing_creepage_candidate_id: str
    governing_creepage_reason: str
    steps: tuple[TraceStep, ...]

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


class PairResult(FrozenModel):
    pair_id: UUID
    pair_key: str
    rule_package_id: UUID
    rule_package_version: str
    rule_package_sha256: str
    calculation_engine_version: str
    clearance_mm: DecimalValue
    creepage_mm: DecimalValue
    trace: CalculationTrace


def calculate_pair(effective: EffectiveCase, rules: RulePackage) -> PairResult:
    _require_valid_rule_package(rules)
    kind = effective.insulation_type.value
    if kind is None:
        raise RequiredStressError("insulation_type is required for a Part 1 calculation")
    _validate_part1_scope(effective)

    clearance = _calculate_clearance(effective, rules)
    clearance_governing = _governing(clearance.candidates)
    final_clearance = clearance_governing.distance_mm
    clearance_step = _maximum_step(
        semantic_rule_id="part1.clearance.maximum",
        candidates=clearance.candidates,
        reason=f"{clearance_governing.candidate_id} governs clearance",
    )

    creepage = _calculate_creepage(effective, final_clearance, rules)
    creepage_governing = _governing(creepage.candidates)
    final_creepage = creepage_governing.distance_mm
    creepage_reason = (
        "final clearance governs creepage"
        if creepage_governing.candidate_id == "clearance_floor"
        else "calculated creepage governs"
    )
    creepage_step = _maximum_step(
        semantic_rule_id="part1.creepage.clearance_floor",
        candidates=creepage.candidates,
        reason=creepage_reason,
    )

    steps = (
        *(step for candidate in clearance.candidates for step in candidate.steps),
        clearance_step,
        *(step for candidate in creepage.candidates for step in candidate.steps),
        creepage_step,
    )
    rule_package_sha256 = rules.package_sha256
    if rule_package_sha256 is None:
        raise CalculationError("validated rule package unexpectedly has no SHA-256 identity")
    return PairResult(
        pair_id=effective.id,
        pair_key=effective.key,
        rule_package_id=rules.manifest.package_id,
        rule_package_version=rules.manifest.version,
        rule_package_sha256=rule_package_sha256,
        calculation_engine_version=CALCULATION_ENGINE_VERSION,
        clearance_mm=final_clearance,
        creepage_mm=final_creepage,
        trace=CalculationTrace(
            insulation_type=kind,
            rule_package_id=rules.manifest.package_id,
            rule_package_version=rules.manifest.version,
            rule_package_sha256=rule_package_sha256,
            calculation_engine_version=CALCULATION_ENGINE_VERSION,
            clearance_candidates=clearance.candidates,
            creepage_candidates=creepage.candidates,
            omissions=clearance.omissions + creepage.omissions,
            governing_clearance_candidate_id=clearance_governing.candidate_id,
            governing_clearance_reason=clearance_step.reason,
            governing_creepage_candidate_id=creepage_governing.candidate_id,
            governing_creepage_reason=creepage_step.reason,
            steps=steps,
        ),
    )


def _validate_part1_scope(effective: EffectiveCase) -> None:
    frequency = effective.frequency_hz.value
    if frequency is None:
        raise RequiredStressError(
            "frequency_hz is required in canonical Hz for a Part 1 calculation"
        )
    if frequency > Decimal(30000):
        raise UnsupportedCaseError(
            f"frequency {frequency} Hz is outside the Part 1 scope through 30000 Hz; "
            "route it through the Task 7 high-frequency extension"
        )
    assumptions = effective.conventional_construction_assumptions.value
    if assumptions:
        raise UnsupportedCaseError(
            "conventional construction assumption flags are unsupported until an "
            "approved semantic mapping is provided: " + ", ".join(assumptions)
        )
    if effective.electrode_radius_mm.value is not None:
        raise UnsupportedCaseError(
            "electrode-radius field iteration is owned by the Task 7 extension"
        )
    altitude = effective.altitude_m.value
    if altitude not in (None, Decimal(0)):
        raise UnsupportedCaseError(
            "altitude correction is owned by the Task 7 extension; the Part 1 "
            "synthetic engine accepts only the 0 m baseline"
        )


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
