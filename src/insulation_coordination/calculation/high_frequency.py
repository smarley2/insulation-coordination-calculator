from __future__ import annotations

from decimal import Decimal

from insulation_coordination.calculation.clearance import (
    CalculationError,
    DistanceCandidate,
    RequiredStressError,
    RuleMappingError,
    _require_valid_rule_package,
    _select_formula,
)
from insulation_coordination.domain.enums import Applicability, FieldCondition, InsulationType
from insulation_coordination.domain.project import EffectiveCase, FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import Formula, RulePackage, Table
from insulation_coordination.domain.trace import EvaluatedValue, Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula


class HighFrequencyCalculationError(CalculationError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        iterations: tuple[FieldIteration, ...] = (),
    ) -> None:
        self.code = code
        self.iterations = iterations
        super().__init__(message)


class FieldIteration(FrozenModel):
    number: int
    previous_clearance_mm: DecimalValue
    calculated_clearance_mm: DecimalValue
    delta_mm: DecimalValue
    selected_route: str
    steps: tuple[TraceStep, ...]


class IterationResult(FrozenModel):
    candidate: DistanceCandidate
    iterations: tuple[FieldIteration, ...]
    tolerance_mm: DecimalValue
    max_iterations: int
    tolerance_steps: tuple[TraceStep, ...]
    limit_steps: tuple[TraceStep, ...]


class HfCandidates(FrozenModel):
    clearance_candidates: tuple[DistanceCandidate, ...] = ()
    creepage_candidates: tuple[DistanceCandidate, ...] = ()
    iterations: tuple[FieldIteration, ...] = ()
    iteration_tolerance_mm: DecimalValue | None = None
    iteration_max_iterations: int | None = None
    iteration_setting_steps: tuple[TraceStep, ...] = ()
    applicability_steps: tuple[TraceStep, ...] = ()


class AltitudeResult(FrozenModel):
    clearance_mm: DecimalValue
    applied: bool
    steps: tuple[TraceStep, ...] = ()


def calculate_high_frequency_candidates(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> HfCandidates:
    _require_valid_rule_package(rules)
    return _calculate_high_frequency_candidates(effective, base, rules)


def _calculate_high_frequency_candidates(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> HfCandidates:
    frequency = effective.frequency_hz.value
    if frequency is None:
        raise RequiredStressError("frequency_hz is required in canonical Hz")
    if frequency <= Decimal(30000):
        return HfCandidates()
    kind = effective.insulation_type.value
    if kind is None:
        raise RequiredStressError("insulation_type is required for a Part 4 calculation")
    applicability_steps = (
        _require_functional_applicability(rules) if kind is InsulationType.FUNCTIONAL else ()
    )
    field = effective.field_condition.value
    if field is None:
        raise RequiredStressError("field_condition is required for a Part 4 calculation")
    periodic_peak = _periodic_peak(effective)
    iterations: tuple[FieldIteration, ...]
    iteration_setting_steps: tuple[TraceStep, ...]
    if field is FieldCondition.INHOMOGENEOUS:
        clearance = _distance_candidate(
            candidate_id="part4_periodic_clearance",
            stress_field="periodic_peak_v",
            stress=periodic_peak,
            semantic_rule_id=_clearance_route(kind, field, effective),
            variables={
                "periodic_peak_v": Quantity(value=periodic_peak, unit="V"),
                "frequency_hz": Quantity(value=frequency, unit="Hz"),
            },
            rules=rules,
        )
        iterations = ()
        iteration_tolerance = None
        iteration_limit = None
        iteration_setting_steps = ()
    else:
        iteration = _iterate_field_clearance(effective, base, rules)
        clearance = iteration.candidate
        iterations = iteration.iterations
        iteration_tolerance = iteration.tolerance_mm
        iteration_limit = iteration.max_iterations
        iteration_setting_steps = (
            *iteration.tolerance_steps,
            *iteration.limit_steps,
        )
    creepage = _optional_distance_candidate(
        candidate_id="part4_deterioration",
        stress_field="periodic_peak_v",
        stress=periodic_peak,
        semantic_rule_id=_creepage_route(kind, effective),
        variables={
            "periodic_peak_v": Quantity(value=periodic_peak, unit="V"),
            "frequency_hz": Quantity(value=frequency, unit="Hz"),
        },
        rules=rules,
    )
    return HfCandidates(
        clearance_candidates=(clearance,),
        creepage_candidates=(() if creepage is None else (creepage,)),
        iterations=iterations,
        iteration_tolerance_mm=iteration_tolerance,
        iteration_max_iterations=iteration_limit,
        iteration_setting_steps=iteration_setting_steps,
        applicability_steps=applicability_steps,
    )


def iterate_field_clearance(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> IterationResult:
    _require_valid_rule_package(rules)
    return _iterate_field_clearance(effective, base, rules)


def _iterate_field_clearance(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> IterationResult:
    field = effective.field_condition.value
    if field not in (
        FieldCondition.HOMOGENEOUS,
        FieldCondition.APPROXIMATELY_HOMOGENEOUS,
    ):
        raise HighFrequencyCalculationError(
            "HF_GEOMETRY_REQUIRED",
            "bounded field iteration requires a homogeneous field selection",
        )
    radius = effective.electrode_radius_mm.value
    if radius is None:
        raise HighFrequencyCalculationError(
            "HF_GEOMETRY_REQUIRED",
            f"{field.value} Part 4 routing requires electrode_radius_mm",
        )
    frequency = effective.frequency_hz.value
    kind = effective.insulation_type.value
    if frequency is None or kind is None:
        raise RequiredStressError(
            "frequency_hz and insulation_type are required for field iteration"
        )
    periodic_peak = _periodic_peak(effective)
    tolerance, tolerance_steps = _iteration_setting(
        rules,
        "iec60664-4:field_iteration:tolerance",
        "mm",
    )
    limit, limit_steps = _iteration_setting(
        rules,
        "iec60664-4:field_iteration:max_iterations",
        "iterations",
    )
    if tolerance <= 0:
        raise CalculationError("field-iteration tolerance must be greater than zero")
    if limit <= 0 or limit != limit.to_integral_value():
        raise CalculationError("field-iteration limit must be a positive integer")
    max_iterations = int(limit)
    homogeneous_route = _clearance_route(kind, field, effective)
    homogeneous_mapping, homogeneous_formula = _select_formula(
        rules,
        homogeneous_route,
        route_label="part4_periodic_clearance",
    )
    current = base.distance_mm
    iterations: list[FieldIteration] = []
    for number in range(1, max_iterations + 1):
        common = {
            "radius_mm": Quantity(value=radius, unit="mm"),
            "clearance_mm": Quantity(value=current, unit="mm"),
        }
        critical, critical_steps = _mapped_value(
            rules,
            f"iec60664-4:critical_frequency:field={field.value}",
            common,
            "Hz",
            "critical-frequency",
        )
        radius_matched, radius_steps = _mapped_value(
            rules,
            f"iec60664-4:radius_criterion:field={field.value}",
            common,
            "bool",
            "radius criterion",
        )
        if radius_matched not in (Decimal(0), Decimal(1)):
            raise CalculationError("radius criterion must return canonical bool zero or one")
        if radius_matched == 0:
            direct = _distance_candidate(
                candidate_id="part4_periodic_clearance",
                stress_field="periodic_peak_v",
                stress=periodic_peak,
                semantic_rule_id=_clearance_route(
                    kind,
                    FieldCondition.INHOMOGENEOUS,
                    effective,
                ),
                variables={
                    "periodic_peak_v": Quantity(value=periodic_peak, unit="V"),
                    "frequency_hz": Quantity(value=frequency, unit="Hz"),
                },
                rules=rules,
            )
            steps = (*critical_steps, *radius_steps, *direct.steps)
            record = FieldIteration(
                number=number,
                previous_clearance_mm=current,
                calculated_clearance_mm=direct.distance_mm,
                delta_mm=abs(direct.distance_mm - current),
                selected_route="inhomogeneous",
                steps=steps,
            )
            return IterationResult(
                candidate=direct.model_copy(update={"steps": steps}),
                iterations=(*iterations, record),
                tolerance_mm=tolerance,
                max_iterations=max_iterations,
                tolerance_steps=tolerance_steps,
                limit_steps=limit_steps,
            )

        evaluated = _evaluate(
            homogeneous_formula,
            {
                "periodic_peak_v": Quantity(value=periodic_peak, unit="V"),
                "frequency_hz": Quantity(value=frequency, unit="Hz"),
                "critical_frequency_hz": Quantity(value=critical, unit="Hz"),
                "clearance_mm": Quantity(value=current, unit="mm"),
            },
            rules,
            "part4_periodic_clearance",
        )
        delta = abs(evaluated.value - current)
        steps = (*critical_steps, *radius_steps, *evaluated.steps)
        iterations.append(
            FieldIteration(
                number=number,
                previous_clearance_mm=current,
                calculated_clearance_mm=evaluated.value,
                delta_mm=delta,
                selected_route=field.value,
                steps=steps,
            )
        )
        current = evaluated.value
        if delta <= tolerance:
            candidate = _candidate_from_evaluated(
                candidate_id="part4_periodic_clearance",
                stress_field="periodic_peak_v",
                stress=periodic_peak,
                semantic_rule_id=homogeneous_route,
                mapping_id=homogeneous_mapping.id,
                formula=homogeneous_formula,
                evaluated=evaluated,
                steps=tuple(step for iteration in iterations for step in iteration.steps),
            )
            return IterationResult(
                candidate=candidate,
                iterations=tuple(iterations),
                tolerance_mm=tolerance,
                max_iterations=max_iterations,
                tolerance_steps=tolerance_steps,
                limit_steps=limit_steps,
            )
    raise HighFrequencyCalculationError(
        "HF_ITERATION_DID_NOT_CONVERGE",
        f"field iteration did not converge within {max_iterations} iterations",
        iterations=tuple(iterations),
    )


def _apply_altitude_correction(
    effective: EffectiveCase,
    clearance_mm: Decimal,
    rules: RulePackage,
) -> AltitudeResult:
    altitude = effective.altitude_m.value
    if altitude is None:
        altitude = Decimal(0)
    if altitude < 0:
        raise HighFrequencyCalculationError(
            "ALTITUDE_OUT_OF_RANGE",
            f"altitude {altitude} m is outside the supported range",
        )
    if altitude <= Decimal(2000):
        return AltitudeResult(clearance_mm=clearance_mm, applied=False)
    route = "iec60664-1:altitude_correction:base=2000m"
    try:
        corrected, steps = _mapped_value(
            rules,
            route,
            {
                "clearance_mm": Quantity(value=clearance_mm, unit="mm"),
                "altitude_m": Quantity(value=altitude, unit="m"),
            },
            "mm",
            "altitude correction",
        )
    except CalculationError as error:
        raise HighFrequencyCalculationError(
            "ALTITUDE_OUT_OF_RANGE",
            f"altitude {altitude} m is outside the supported altitude rule: {error}",
        ) from error
    if corrected < clearance_mm:
        raise HighFrequencyCalculationError(
            "ALTITUDE_NON_MONOTONIC",
            "approved altitude correction reduced the governing clearance",
        )
    return AltitudeResult(clearance_mm=corrected, applied=True, steps=steps)


def _require_functional_applicability(rules: RulePackage) -> tuple[TraceStep, ...]:
    semantic_rule_id = (
        "iec60664-4:functional_applicability:stress=periodic_peak_v:frequency=frequency_hz"
    )
    try:
        mapping, formula = _select_formula(
            rules,
            semantic_rule_id,
            route_label="functional_hf_applicability",
        )
        evaluated = evaluate_formula(formula, {}, _tables(rules))
    except (RuleMappingError, EvaluationError) as error:
        raise HighFrequencyCalculationError(
            "FUNCTIONAL_HF_MAPPING_MISSING",
            "functional insulation above 30 kHz requires one approved "
            "functional-applicability mapping",
        ) from error
    if evaluated.unit != "bool" or evaluated.value != Decimal(1):
        raise HighFrequencyCalculationError(
            "FUNCTIONAL_HF_MAPPING_MISSING",
            "the approved functional high-frequency applicability rule does not accept this case",
        )
    return evaluated.steps[:-1] + (
        evaluated.steps[-1].model_copy(
            update={
                "semantic_rule_id": semantic_rule_id,
                "reason": (
                    "functional high-frequency applicability accepted by approved "
                    f"mapping {mapping.id}"
                ),
            }
        ),
    )


def _periodic_peak(effective: EffectiveCase) -> Decimal:
    values: list[Decimal] = []
    for field in (
        "steady_state_peak_v",
        "temporary_overvoltage_peak_v",
        "recurring_peak_v",
    ):
        voltage = getattr(effective.voltages, field)
        if voltage.applicability is Applicability.BLANK:
            raise RequiredStressError(
                f"{field} is blank; enter a canonical V value or mark it not applicable"
            )
        if voltage.applicability is Applicability.APPLICABLE:
            if voltage.value is None:
                raise RequiredStressError(f"{field} is applicable but has no canonical V value")
            values.append(voltage.value)
    if not values:
        raise RequiredStressError("at least one periodic peak stress must be applicable")
    return max(values)


def _clearance_route(
    kind: InsulationType,
    field: FieldCondition,
    effective: EffectiveCase,
) -> str:
    pollution = effective.pollution_degree.value
    if pollution is None:
        raise RequiredStressError("pollution_degree is required for a Part 4 calculation")
    return (
        f"iec60664-4:clearance:{kind.value}:stress=periodic_peak_v:"
        f"frequency=frequency_hz:field={field.value}:pollution={pollution}"
    )


def _creepage_route(kind: InsulationType, effective: EffectiveCase) -> str:
    construction = effective.construction_type.value
    pollution = effective.pollution_degree.value
    material = effective.cti_or_material_group.value
    if construction is None or pollution is None or material is None:
        raise RequiredStressError(
            "construction_type, pollution_degree, and cti_or_material_group "
            "are required for Part 4 creepage"
        )
    return (
        f"iec60664-4:creepage:{kind.value}:stress=periodic_peak_v:"
        f"frequency=frequency_hz:construction={construction.value}:"
        f"pollution={pollution}:material={material}"
    )


def _distance_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    variables: dict[str, Quantity],
    rules: RulePackage,
) -> DistanceCandidate:
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=candidate_id,
    )
    evaluated = _evaluate(formula, variables, rules, candidate_id)
    if evaluated.value < 0:
        raise CalculationError(f"{candidate_id} formula returned a negative distance")
    return _candidate_from_evaluated(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=stress,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula=formula,
        evaluated=evaluated,
        steps=evaluated.steps,
    )


def _optional_distance_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    variables: dict[str, Quantity],
    rules: RulePackage,
) -> DistanceCandidate | None:
    if not any(mapping.source_rule_id == semantic_rule_id for mapping in rules.mappings):
        return None
    return _distance_candidate(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=stress,
        semantic_rule_id=semantic_rule_id,
        variables=variables,
        rules=rules,
    )


def _candidate_from_evaluated(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    mapping_id: str,
    formula: Formula,
    evaluated: EvaluatedValue,
    steps: tuple[TraceStep, ...],
) -> DistanceCandidate:
    return DistanceCandidate(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=Quantity(value=stress, unit="V"),
        distance_mm=evaluated.value,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping_id,
        formula_id=formula.id,
        steps=steps,
        reason=steps[-1].reason,
    )


def _iteration_setting(
    rules: RulePackage,
    route: str,
    unit: str,
) -> tuple[Decimal, tuple[TraceStep, ...]]:
    return _mapped_value(rules, route, {}, unit, route.rsplit(":", 1)[-1])


def _mapped_value(
    rules: RulePackage,
    route: str,
    variables: dict[str, Quantity],
    expected_unit: str,
    label: str,
) -> tuple[Decimal, tuple[TraceStep, ...]]:
    mapping, formula = _select_formula(rules, route, route_label=label)
    evaluated = _evaluate(formula, variables, rules, label)
    if evaluated.unit != expected_unit:
        raise CalculationError(
            f"{label} mapping {mapping.id!r} returned {evaluated.unit!r}, "
            f"expected {expected_unit!r}"
        )
    steps = evaluated.steps[:-1] + (
        evaluated.steps[-1].model_copy(
            update={
                "semantic_rule_id": route,
                "reason": f"{label} evaluated from approved mapping {mapping.id}",
            }
        ),
    )
    return evaluated.value, steps


def _evaluate(
    formula: Formula,
    variables: dict[str, Quantity],
    rules: RulePackage,
    label: str,
) -> EvaluatedValue:
    try:
        evaluated = evaluate_formula(formula, variables, _tables(rules))
    except EvaluationError as error:
        raise CalculationError(f"{label} using formula {formula.id!r} failed: {error}") from error
    if evaluated.unit != formula.unit:
        raise CalculationError(
            f"{label} formula {formula.id!r} returned {evaluated.unit!r}, expected {formula.unit!r}"
        )
    return evaluated


def _tables(rules: RulePackage) -> dict[str, Table]:
    return {table.id: table for table in rules.tables}
