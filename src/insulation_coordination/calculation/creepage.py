from __future__ import annotations

from decimal import Decimal

from insulation_coordination.calculation.clearance import (
    CalculationError,
    CandidateCalculation,
    CandidateOmission,
    DistanceCandidate,
    RequiredStressError,
    _evaluate_candidate,
    _require_valid_rule_package,
    _required,
    _select_formula,
)
from insulation_coordination.domain.enums import Applicability, InsulationType
from insulation_coordination.domain.project import EffectiveCase
from insulation_coordination.domain.rules import RulePackage, Variable
from insulation_coordination.domain.trace import Quantity
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula


def calculate_creepage_candidates(
    effective: EffectiveCase,
    final_clearance_mm: Decimal,
    rules: RulePackage,
) -> tuple[DistanceCandidate, ...]:
    _require_valid_rule_package(rules)
    return _calculate_creepage(effective, final_clearance_mm, rules).candidates


def _calculate_creepage(
    effective: EffectiveCase,
    final_clearance_mm: Decimal,
    rules: RulePackage,
) -> CandidateCalculation:
    floor = _clearance_floor_candidate(final_clearance_mm)
    tracking = effective.voltages.long_term_rms_v
    if tracking.applicability is Applicability.BLANK:
        raise RequiredStressError(
            "long_term_rms_v is blank; enter a canonical V value or mark it "
            "not applicable with a justification"
        )
    if tracking.applicability is Applicability.NOT_APPLICABLE:
        assert tracking.justification is not None
        return CandidateCalculation(
            candidates=(floor,),
            omissions=(
                CandidateOmission(
                    candidate_id="long_term_rms_tracking",
                    stress_field="long_term_rms_v",
                    applicability=tracking.applicability,
                    justification=tracking.justification,
                ),
            ),
        )
    if tracking.value is None:
        raise RequiredStressError("long_term_rms_v is applicable but has no canonical V value")

    kind = _required(effective.insulation_type.value, "insulation_type")
    construction = _required(effective.construction_type.value, "construction_type")
    pollution = _required(effective.pollution_degree.value, "pollution_degree")
    material = _required(
        effective.cti_or_material_group.value,
        "cti_or_material_group",
    )
    clause = "5.3.4" if kind is InsulationType.FUNCTIONAL else "5.3.5"
    semantic_rule_id = (
        f"iec60664-1:{clause}:{kind.value}_creepage:"
        f"construction={construction.value}:pollution={pollution}:material={material}"
    )
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=f"{kind.value}_creepage",
    )
    calculated = _evaluate_candidate(
        candidate_id="long_term_rms_tracking",
        stress_field="long_term_rms_v",
        stress=tracking.value,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula=formula,
        rules=rules,
    )
    return CandidateCalculation(candidates=(calculated, floor), omissions=())


def _clearance_floor_candidate(final_clearance_mm: Decimal) -> DistanceCandidate:
    stress = Quantity(value=final_clearance_mm, unit="mm")
    try:
        evaluated = evaluate_formula(
            Variable(name="final_clearance_mm"),
            {"final_clearance_mm": stress},
            {},
        )
    except EvaluationError as error:
        raise CalculationError(f"clearance-floor candidate evaluation failed: {error}") from error
    step = evaluated.steps[-1].model_copy(
        update={
            "semantic_rule_id": "part1.creepage.clearance_floor.candidate",
            "reason": "final clearance retained as the creepage floor candidate",
        }
    )
    return DistanceCandidate(
        candidate_id="clearance_floor",
        stress_field="final_clearance_mm",
        stress=stress,
        distance_mm=evaluated.value,
        semantic_rule_id="part1.creepage.clearance_floor.candidate",
        steps=(step,),
        reason=step.reason,
    )
