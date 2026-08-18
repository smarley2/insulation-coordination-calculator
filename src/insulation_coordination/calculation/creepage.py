from __future__ import annotations

from decimal import Decimal

from insulation_coordination.calculation.clearance import (
    CalculationError,
    CalculationRangeError,
    CandidateCalculation,
    CandidateOmission,
    DistanceCandidate,
    RequiredStressError,
    UnsupportedCaseError,
    _evaluate_candidate,
    _require_valid_rule_package,
    _required,
    _select_formula,
)
from insulation_coordination.calculation.reinforced_rules import (
    CREEPAGE_ROUTE,
    apply_reinforced_treatment,
    read_reinforced_rules,
)
from insulation_coordination.domain.enums import Applicability, ConstructionType, InsulationType
from insulation_coordination.domain.project import EffectiveCase
from insulation_coordination.domain.rules import RulePackage, TableSelect, Variable
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

#: The operation token the trace and the report key the creepage treatment on.
REINFORCED_CREEPAGE_OPERATION = "reinforced_creepage_double"


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

    if any(formula.id == "iec60664-1:f5-pcb-creepage" for formula in rules.formulas):
        calculated = select_f5_pcb_creepage(effective, rules)
        return CandidateCalculation(candidates=(calculated, floor), omissions=())

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


def select_f5_pcb_creepage(
    effective: EffectiveCase,
    rules: RulePackage,
) -> DistanceCandidate:
    """Select joined IEC 60664-1 F.5 printed-wiring creepage data."""
    _require_valid_rule_package(rules)
    _validate_pcb_scope(effective)
    tracking = effective.voltages.long_term_rms_v
    if tracking.applicability is not Applicability.APPLICABLE or tracking.value is None:
        raise RequiredStressError("long_term_rms_v must be applicable for F.5 selection")
    kind = _required(effective.insulation_type.value, "insulation_type")
    pollution = _required(effective.pollution_degree.value, "pollution_degree")
    clause = "5.3.4" if kind is InsulationType.FUNCTIONAL else "5.3.5"
    semantic_rule_id = (
        f"iec60664-1:{clause}:{kind.value}_creepage:"
        f"construction=printed_wiring:pollution={pollution}"
    )
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=f"{kind.value}_pcb_creepage",
    )
    if not isinstance(formula.expression, TableSelect):
        raise CalculationError("F.5 creepage formula must use semantic table selection")
    table = next(
        (item for item in rules.tables if item.id == formula.expression.table_id),
        None,
    )
    if table is None:
        raise CalculationError("F.5 creepage formula references a missing table")
    branch_label = f"pcb_pollution_{pollution}"
    try:
        column = table.column_axis.labels.index(branch_label)
        evaluated = evaluate_formula(
            formula,
            {
                "rms_voltage_v": Quantity(value=tracking.value, unit="V"),
                "pcb_pollution_branch": Quantity(value=table.column_axis.values[column], unit="1"),
            },
            {item.id: item for item in rules.tables},
        )
    except (ValueError, EvaluationError) as error:
        message = f"F.5 PCB creepage selection failed: {error}"
        if "outside" in str(error) or "has no cell" in str(error):
            raise CalculationRangeError(message) from error
        raise CalculationError(message) from error
    distance = evaluated.value
    steps: tuple[TraceStep, ...] = evaluated.steps
    if kind is InsulationType.REINFORCED:
        # The treatment is stated over the selected requirement rather than over the stress,
        # which is why the quantity asked about is the basic insulation requirement and the
        # unit is a distance. The factor itself belongs to the approved package.
        distance, treated = apply_reinforced_treatment(
            evaluated.value,
            unit="mm",
            route=CREEPAGE_ROUTE,
            insulation_class=kind.value,
            treated_quantity="basic_insulation_requirement",
            rules=read_reinforced_rules(rules),
            source=mapping.source,
            operation=REINFORCED_CREEPAGE_OPERATION,
        )
        steps = (*steps, treated)
    return DistanceCandidate(
        candidate_id="long_term_rms_tracking",
        stress_field="long_term_rms_v",
        stress=Quantity(value=tracking.value, unit="V"),
        distance_mm=distance,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula_id=formula.id,
        selection_mode=f"{formula.expression.row_mode}/{formula.expression.column_mode}",
        branch_label=branch_label,
        steps=steps,
        reason=steps[-1].reason,
    )


def _validate_pcb_scope(effective: EffectiveCase) -> None:
    if effective.construction_type.value is not ConstructionType.PRINTED_WIRING:
        raise UnsupportedCaseError("Annex H engine supports printed-wiring construction only")
    pollution = effective.pollution_degree.value
    if pollution not in (1, 2):
        raise UnsupportedCaseError("PCB F.5 supports pollution degree 1 or 2 only")
    material = effective.cti_or_material_group.value
    if material not in {"I", "II", "III", "IIIa", "IIIb"}:
        raise UnsupportedCaseError(f"unsupported CTI/material classification: {material!r}")
    assumptions = effective.conventional_construction_assumptions.value or ()
    if assumptions:
        raise UnsupportedCaseError(
            "unsupported PCB construction condition: " + ", ".join(assumptions)
        )


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
