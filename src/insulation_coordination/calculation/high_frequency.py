from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Final

from insulation_coordination.calculation.clearance import (
    CalculationError,
    CalculationRangeError,
    CandidateOmission,
    DistanceCandidate,
    RequiredStressError,
    RuleMappingError,
    _require_valid_rule_package,
    _select_formula,
    select_f8_periodic_clearance,
)
from insulation_coordination.calculation.creepage import _validate_pcb_scope
from insulation_coordination.domain.enums import Applicability, FieldCondition, InsulationType
from insulation_coordination.domain.project import EffectiveCase, FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import (
    Formula,
    Maximum,
    Multiply,
    RulePackage,
    Table,
    TableSelect,
    Variable,
)
from insulation_coordination.domain.trace import EvaluatedValue, Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula

#: The frequency a pair has to exceed before IEC 60664-4 has anything to say about it, and
#: below which nothing in this module applies. Named once because four places asked the same
#: question of the same figure, and a boundary written four times is one that three of them
#: can drift from. Consumers outside this module read it here rather than restating it.
PART4_FREQUENCY_THRESHOLD_HZ: Final[Decimal] = Decimal(30000)


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
    critical_frequency_hz: DecimalValue
    actual_frequency_hz: DecimalValue
    factor_percent: DecimalValue
    radius_ratio: DecimalValue | None = None
    stable: bool
    steps: tuple[TraceStep, ...]


class IterationResult(FrozenModel):
    candidate: DistanceCandidate
    iterations: tuple[FieldIteration, ...]


class HfCandidates(FrozenModel):
    clearance_candidates: tuple[DistanceCandidate, ...] = ()
    creepage_candidates: tuple[DistanceCandidate, ...] = ()
    iterations: tuple[FieldIteration, ...] = ()
    applicability_steps: tuple[TraceStep, ...] = ()
    periodic_peak_omissions: tuple[CandidateOmission, ...] = ()
    periodic_peak_selected_fields: tuple[str, ...] = ()


class PeriodicPeakSelection(FrozenModel):
    value: DecimalValue
    selected_fields: tuple[str, ...]
    omissions: tuple[CandidateOmission, ...]
    steps: tuple[TraceStep, ...]


class AltitudeResult(FrozenModel):
    clearance_mm: DecimalValue
    applied: bool
    steps: tuple[TraceStep, ...] = ()


class FrequencyFactor(FrozenModel):
    percent: DecimalValue
    branch: str
    critical_frequency_hz: DecimalValue
    minimum_frequency_hz: DecimalValue
    steps: tuple[TraceStep, ...] = ()


def select_part4_table2_creepage(
    effective: EffectiveCase,
    rules: RulePackage,
) -> DistanceCandidate | None:
    """Select IEC 60664-4 Table 2 and apply its pollution multiplier."""
    frequency = effective.frequency_hz.value
    if frequency is None:
        raise RequiredStressError("frequency_hz is required for Part 4 creepage")
    if frequency <= PART4_FREQUENCY_THRESHOLD_HZ:
        return None
    _require_valid_rule_package(rules)
    _validate_pcb_scope(effective)
    kind = effective.insulation_type.value
    pollution = effective.pollution_degree.value
    if kind is None or pollution is None:
        raise RequiredStressError("insulation_type and pollution_degree are required")
    periodic_peak = _periodic_peak(effective)
    route = _creepage_route(kind, effective)
    mapping, formula = _select_formula(rules, route, route_label="part4_frequency_creepage")
    if not isinstance(formula.expression, TableSelect):
        raise CalculationError("Table 2 creepage formula must use semantic table selection")
    table = next(
        (item for item in rules.tables if item.id == formula.expression.table_id),
        None,
    )
    if table is None:
        raise CalculationError("Table 2 creepage formula references a missing table")
    selected_frequency = max(frequency, table.column_axis.values[0])
    try:
        evaluated = evaluate_formula(
            formula,
            {
                "peak_voltage_kv": Quantity(value=periodic_peak.value / Decimal(1000), unit="kV"),
                "frequency_hz": Quantity(value=selected_frequency, unit="Hz"),
            },
            {item.id: item for item in rules.tables},
        )
    except EvaluationError as error:
        message = f"Table 2 creepage selection failed: {error}"
        if "outside" in str(error) or "has no cell" in str(error):
            raise CalculationRangeError(message) from error
        raise CalculationError(message) from error
    multiplier = Decimal(1) if pollution == 1 else Decimal("1.2")
    distance = evaluated.value * multiplier
    multiplier_step = TraceStep(
        semantic_rule_id=f"iec60664-4:table-2:pollution-degree-{pollution}-factor",
        operation="pollution_multiplier",
        symbolic="d=d_{Table2}k_{pollution}",
        substituted=f"{evaluated.value} mm * {multiplier} = {distance} mm",
        inputs=(
            Quantity(value=evaluated.value, unit="mm"),
            Quantity(value=multiplier, unit="1"),
        ),
        source_reference=table.source,
        output=Quantity(value=distance, unit="mm"),
        unrounded_value=distance,
        reason=f"Table 2 pollution degree {pollution} multiplier applied",
    )
    steps = (*periodic_peak.steps, *evaluated.steps, multiplier_step)
    return DistanceCandidate(
        candidate_id="part4_frequency_creepage",
        stress_field="periodic_peak_v",
        stress=Quantity(value=periodic_peak.value, unit="V"),
        distance_mm=distance,
        semantic_rule_id=route,
        mapping_id=mapping.id,
        formula_id=formula.id,
        selection_mode=f"{formula.expression.row_mode}/{formula.expression.column_mode}",
        steps=steps,
        reason=multiplier_step.reason,
    )


def calculate_critical_frequency(
    clearance_mm: Decimal,
    rules: RulePackage,
) -> EvaluatedValue:
    """Evaluate IEC 60664-4 Equation (1) for one pair's clearance."""
    if clearance_mm <= 0:
        raise HighFrequencyCalculationError(
            "HF_CLEARANCE_INVALID",
            "critical-frequency clearance must be greater than zero",
        )
    formula = _formula_by_id(rules, "iec60664-4-equation-1-critical-frequency")
    evaluated = _evaluate_scalar_formula(
        formula,
        {"clearance_mm": clearance_mm},
        expected_unit="MHz",
    )
    value_hz = evaluated.value * Decimal(1_000_000)
    final = evaluated.steps[-1].model_copy(
        update={
            "semantic_rule_id": formula.id,
            "operation": "critical_frequency",
            "symbolic": formula.latex or "f_crit = 0.2 / (d / mm) MHz",
            "substituted": f"{evaluated.value} MHz = {value_hz} Hz",
            "output": Quantity(value=value_hz, unit="Hz"),
            "unrounded_value": value_hz,
            "reason": "pair-specific critical frequency from IEC 60664-4 Equation (1)",
        }
    )
    return EvaluatedValue(value=value_hz, unit="Hz", steps=(*evaluated.steps[:-1], final))


def select_frequency_factor(
    frequency_hz: Decimal,
    critical_frequency_hz: Decimal,
    rules: RulePackage,
) -> FrequencyFactor:
    """Select 100 %, Equation (2), or 125 % at IEC boundary values."""
    minimum_formula = _formula_by_id(rules, "iec60664-4-minimum-frequency")
    minimum = _evaluate_scalar_formula(minimum_formula, {}, expected_unit="MHz")
    minimum_hz = minimum.value * Decimal(1_000_000)
    if frequency_hz < critical_frequency_hz:
        percent = Decimal(100)
        branch = "below_critical"
        steps = minimum.steps
    elif frequency_hz >= minimum_hz:
        percent = Decimal(125)
        branch = "at_or_above_minimum"
        steps = minimum.steps
    else:
        factor_formula = _formula_by_id(rules, "iec60664-4-equation-2-frequency-factor")
        factor = _evaluate_scalar_formula(
            factor_formula,
            {
                "frequency_mhz": frequency_hz / Decimal(1_000_000),
                "critical_frequency_mhz": critical_frequency_hz / Decimal(1_000_000),
                "minimum_frequency_mhz": minimum.value,
            },
            expected_unit="percent",
        )
        percent = factor.value
        branch = "critical_to_minimum"
        steps = (*minimum.steps, *factor.steps)
    return FrequencyFactor(
        percent=percent,
        branch=branch,
        critical_frequency_hz=critical_frequency_hz,
        minimum_frequency_hz=minimum_hz,
        steps=steps,
    )


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
    if frequency <= PART4_FREQUENCY_THRESHOLD_HZ:
        return HfCandidates()
    kind, applicability_steps = _require_part4_scope(effective, rules)
    periodic_peak = _periodic_peak(effective)
    assessment = _assess_part4_clearance(
        effective,
        base,
        rules,
        periodic_peak=periodic_peak,
    )
    if any(formula.id == "iec60664-4:hf-creepage-table" for formula in rules.formulas):
        creepage = select_part4_table2_creepage(effective, rules)
    else:
        creepage = _optional_distance_candidate(
            candidate_id="part4_deterioration",
            stress_field="periodic_peak_v",
            stress=periodic_peak.value,
            semantic_rule_id=_creepage_route(kind, effective),
            variables={
                "periodic_peak_v": Quantity(value=periodic_peak.value, unit="V"),
                "frequency_hz": Quantity(value=frequency, unit="Hz"),
            },
            rules=rules,
            prefix_steps=periodic_peak.steps,
        )
    return HfCandidates(
        clearance_candidates=(assessment.candidate,),
        creepage_candidates=(() if creepage is None else (creepage,)),
        iterations=assessment.iterations,
        applicability_steps=applicability_steps,
        periodic_peak_omissions=periodic_peak.omissions,
        periodic_peak_selected_fields=periodic_peak.selected_fields,
    )


def iterate_field_clearance(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> IterationResult:
    _require_valid_rule_package(rules)
    _require_part4_scope(effective, rules)
    return _assess_part4_clearance(effective, base, rules)


def assess_part4_clearance(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
) -> IterationResult:
    _require_valid_rule_package(rules)
    _require_part4_scope(effective, rules)
    return _assess_part4_clearance(effective, base, rules)


def _assess_part4_clearance(
    effective: EffectiveCase,
    base: DistanceCandidate,
    rules: RulePackage,
    *,
    periodic_peak: PeriodicPeakSelection | None = None,
) -> IterationResult:
    field = effective.field_condition.value
    if field is None:
        raise RequiredStressError("field_condition is required for a Part 4 calculation")
    frequency = effective.frequency_hz.value
    kind = effective.insulation_type.value
    if frequency is None or kind is None:
        raise RequiredStressError("frequency_hz and insulation_type are required for Part 4")
    periodic_peak = periodic_peak or _periodic_peak(effective)
    current = base.distance_mm
    iterations: list[FieldIteration] = []
    previous_signature: tuple[str, str, Decimal] | None = None
    for number in (1, 2):
        candidate, selected_route, factor, radius_ratio, steps = _part4_pass(
            effective,
            base,
            current,
            rules,
            periodic_peak,
        )
        signature = (selected_route, candidate.branch_label or "", candidate.distance_mm)
        stable = (
            candidate.distance_mm == current if number == 1 else signature == previous_signature
        )
        critical = calculate_critical_frequency(current, rules)
        iterations.append(
            FieldIteration(
                number=number,
                previous_clearance_mm=current,
                calculated_clearance_mm=candidate.distance_mm,
                delta_mm=abs(candidate.distance_mm - current),
                selected_route=selected_route,
                critical_frequency_hz=critical.value,
                actual_frequency_hz=frequency,
                factor_percent=factor,
                radius_ratio=radius_ratio,
                stable=stable,
                steps=steps,
            )
        )
        if stable:
            return IterationResult(candidate=candidate, iterations=tuple(iterations))
        previous_signature = signature
        current = candidate.distance_mm
    raise HighFrequencyCalculationError(
        "HF_SECOND_PASS_UNSTABLE",
        "Part 4 branch, field classification, or source-rounded distance changed after the second pass",
        iterations=tuple(iterations),
    )


def _part4_pass(
    effective: EffectiveCase,
    base: DistanceCandidate,
    current_clearance_mm: Decimal,
    rules: RulePackage,
    periodic_peak: PeriodicPeakSelection,
) -> tuple[DistanceCandidate, str, Decimal, Decimal | None, tuple[TraceStep, ...]]:
    frequency = effective.frequency_hz.value
    kind = effective.insulation_type.value
    field = effective.field_condition.value
    assert frequency is not None and kind is not None and field is not None
    critical = calculate_critical_frequency(current_clearance_mm, rules)
    radius_ratio: Decimal | None = None
    radius_steps: tuple[TraceStep, ...] = ()
    selected_field = field
    if field is not FieldCondition.INHOMOGENEOUS:
        radius = effective.electrode_radius_mm.value
        if radius is None:
            raise HighFrequencyCalculationError(
                "HF_GEOMETRY_REQUIRED",
                f"{field.value} Part 4 routing requires electrode_radius_mm",
            )
        radius_ratio = radius / current_clearance_mm
        radius_formula = _formula_by_id(rules, "iec60664-4-radius-criterion")
        radius_result = _evaluate_scalar_formula(
            radius_formula,
            {"radius_mm": radius, "clearance_mm": current_clearance_mm},
            expected_unit="bool",
        )
        radius_steps = radius_result.steps
        if radius_result.value == 0:
            selected_field = FieldCondition.INHOMOGENEOUS

    prefix = (*periodic_peak.steps, *critical.steps, *radius_steps)
    if selected_field is FieldCondition.INHOMOGENEOUS:
        if frequency < critical.value:
            candidate = base.model_copy(
                update={
                    "candidate_id": "part4_periodic_clearance",
                    "steps": prefix,
                    "reason": "frequency below pair-specific critical frequency; Part 1 clearance retained",
                }
            )
            return candidate, "below_critical", Decimal(100), radius_ratio, prefix
        route = _clearance_route(kind, effective)
        candidate = _distance_candidate(
            candidate_id="part4_periodic_clearance",
            stress_field="periodic_peak_v",
            stress=periodic_peak.value,
            semantic_rule_id=route,
            variables={
                "peak_voltage_kv": Quantity(value=periodic_peak.value / Decimal(1000), unit="kV"),
                "clearance_branch": Quantity(value=Decimal(1), unit="1"),
            },
            rules=rules,
            prefix_steps=prefix,
        )
        return candidate, "inhomogeneous_table_1", Decimal(100), radius_ratio, candidate.steps

    factor = select_frequency_factor(frequency, critical.value, rules)
    treated_stress = periodic_peak.value * factor.percent / Decimal(100)
    candidate = select_f8_periodic_clearance(
        effective,
        rules,
        candidate_id="part4_periodic_clearance",
        stress_field="periodic_peak_v",
        stress=treated_stress,
    )
    steps = (*prefix, *factor.steps, *candidate.steps)
    candidate = candidate.model_copy(
        update={
            "stress": Quantity(value=periodic_peak.value, unit="V"),
            "treated_stress": Quantity(value=treated_stress, unit="V"),
            "steps": steps,
            "reason": f"{factor.percent}% periodic withstand-voltage treatment selected",
        }
    )
    return candidate, factor.branch, factor.percent, radius_ratio, steps


def apply_a2_altitude_correction(
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
        source = next(
            (
                mapping.source
                for mapping in rules.mappings
                if mapping.source_rule_id == "iec60664-1:altitude_correction:base=2000m"
            ),
            None,
        )
        if source is None:
            return AltitudeResult(clearance_mm=clearance_mm, applied=False)
        step = TraceStep(
            semantic_rule_id="iec60664-1:a2-altitude-not-applied",
            operation="altitude_boundary",
            symbolic="k_{A2}=1",
            substituted=f"h={altitude} m <= 2000 m",
            inputs=(Quantity(value=altitude, unit="m"),),
            source_reference=source,
            output=Quantity(value=clearance_mm, unit="mm"),
            unrounded_value=clearance_mm,
            reason="altitude is at or below 2000 m; no A.2 factor applies",
        )
        return AltitudeResult(clearance_mm=clearance_mm, applied=False, steps=(step,))
    route = "iec60664-1:altitude_correction:base=2000m"
    try:
        mapping, formula = _select_formula(
            rules,
            route,
            route_label="altitude correction",
        )
        _, column_value = _validate_a2_altitude_rule(formula, rules)
        evaluated_factor = _evaluate(
            formula,
            {
                "altitude_m": Quantity(value=altitude, unit="m"),
                "clearance_factor": Quantity(value=column_value, unit="1"),
            },
            rules,
            "altitude correction factor",
        )
        if evaluated_factor.unit != "1":
            raise HighFrequencyCalculationError(
                "ALTITUDE_RULE_INVALID",
                f"altitude factor formula {formula.id!r} returned "
                f"{evaluated_factor.unit!r}, expected canonical '1'",
            )
        factor_steps = _mapped_steps(
            evaluated_factor,
            route,
            f"altitude correction factor evaluated from approved mapping {mapping.id}",
        )
        evaluated_clearance = evaluate_formula(
            Multiply(
                operands=(
                    Variable(name="clearance_mm"),
                    Variable(name="altitude_factor"),
                )
            ),
            {
                "clearance_mm": Quantity(value=clearance_mm, unit="mm"),
                "altitude_factor": Quantity(value=evaluated_factor.value, unit="1"),
            },
            {},
        )
        if evaluated_clearance.unit != "mm" or evaluated_clearance.value < 0:
            raise HighFrequencyCalculationError(
                "ALTITUDE_RULE_INVALID",
                "altitude-corrected clearance must be a nonnegative canonical mm value",
            )
        correction_steps = evaluated_clearance.steps[:-1] + (
            evaluated_clearance.steps[-1].model_copy(
                update={
                    "semantic_rule_id": f"{route}:corrected_clearance",
                    "reason": "governing clearance multiplied by the approved altitude factor",
                }
            ),
        )
        corrected = evaluated_clearance.value
        steps = (*factor_steps, *correction_steps)
    except HighFrequencyCalculationError:
        raise
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


def _apply_altitude_correction(
    effective: EffectiveCase,
    clearance_mm: Decimal,
    rules: RulePackage,
) -> AltitudeResult:
    return apply_a2_altitude_correction(effective, clearance_mm, rules)


def _validate_a2_altitude_rule(
    formula: Formula,
    rules: RulePackage,
) -> tuple[Table, Decimal]:
    expression = formula.expression
    if (
        formula.unit != "1"
        or not isinstance(expression, TableSelect)
        or expression.row_mode != "linear"
        or expression.column_mode != "exact"
        or not isinstance(expression.row, Variable)
        or expression.row.name != "altitude_m"
        or not isinstance(expression.column, Variable)
        or expression.column.name != "clearance_factor"
    ):
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "A.2 altitude factor must be a linear/exact semantic table selection",
        )
    tables = tuple(table for table in rules.tables if table.id == expression.table_id)
    if len(tables) != 1:
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "altitude factor must reference exactly one declared table",
        )
    table = tables[0]
    row_values = table.row_axis.values
    if (
        table.interpolation != "linear"
        or table.unit != "1"
        or table.row_axis.id != "altitude_m"
        or table.row_axis.unit != "m"
        or table.column_axis.id != "clearance_factor"
        or table.column_axis.unit != "1"
        or len(table.column_axis.values) != 1
        or len(row_values) < 2
        or any(left >= right for left, right in pairwise(row_values))
        or row_values[0] != Decimal(2000)
    ):
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "altitude table must be dimensionless with a strictly increasing canonical-m "
            "altitude row axis covering the supported formula range",
        )
    table_ranges = tuple(item for item in table.supported_ranges if item.variable == "altitude_m")
    if len(table_ranges) != 1 or not (
        table_ranges[0].unit == "m"
        and table_ranges[0].minimum == row_values[0]
        and table_ranges[0].maximum == row_values[-1]
    ):
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "A.2 table must declare its complete canonical-m altitude range",
        )
    factors = []
    for row_index in range(len(row_values)):
        cell_matches = tuple(
            cell for cell in table.cells if cell.row == row_index and cell.column == 0
        )
        if len(cell_matches) != 1 or cell_matches[0].unit != "1":
            raise HighFrequencyCalculationError(
                "ALTITUDE_RULE_INVALID",
                "altitude factor column must contain one dimensionless cell per altitude row",
            )
        factors.append(cell_matches[0].value)
    if factors[0] != Decimal(1):
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "altitude factor must equal one at the 2000 m boundary",
        )
    if any(right < left for left, right in pairwise(factors)):
        raise HighFrequencyCalculationError(
            "ALTITUDE_RULE_INVALID",
            "altitude factor cells must not decrease with altitude",
        )
    return table, table.column_axis.values[0]


def _require_part4_scope(
    effective: EffectiveCase,
    rules: RulePackage,
) -> tuple[InsulationType, tuple[TraceStep, ...]]:
    frequency = effective.frequency_hz.value
    if frequency is None:
        raise RequiredStressError("frequency_hz is required in canonical Hz")
    if frequency <= PART4_FREQUENCY_THRESHOLD_HZ:
        raise HighFrequencyCalculationError(
            "HF_FREQUENCY_NOT_APPLICABLE",
            f"frequency {frequency} Hz does not exceed the "
            f"{PART4_FREQUENCY_THRESHOLD_HZ} Hz Part 4 threshold",
        )
    kind = effective.insulation_type.value
    if kind is None:
        raise RequiredStressError("insulation_type is required for a Part 4 calculation")
    return kind, ()


def _periodic_peak(effective: EffectiveCase) -> PeriodicPeakSelection:
    values: dict[str, Quantity] = {}
    omissions: list[CandidateOmission] = []
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
            values[field] = Quantity(value=voltage.value, unit="V")
        elif voltage.applicability is Applicability.NOT_APPLICABLE:
            assert voltage.justification is not None
            omissions.append(
                CandidateOmission(
                    candidate_id=field.removesuffix("_v"),
                    stress_field=field,
                    applicability=voltage.applicability,
                    justification=voltage.justification,
                )
            )
    if not values:
        raise RequiredStressError("at least one periodic peak stress must be applicable")
    try:
        evaluated = evaluate_formula(
            Maximum(operands=tuple(Variable(name=field) for field in values)),
            values,
            {},
        )
    except EvaluationError as error:
        raise CalculationError(f"periodic peak selection failed: {error}") from error
    selected = tuple(
        field for field, quantity in values.items() if quantity.value == evaluated.value
    )
    reason = (
        f"{selected[0]} governs the periodic peak"
        if len(selected) == 1
        else f"periodic peak tie between {', '.join(selected)}; {selected[0]} selected"
    )
    steps = evaluated.steps[:-1] + (
        evaluated.steps[-1].model_copy(
            update={
                "semantic_rule_id": "iec60664-4:periodic_peak.maximum",
                "reason": reason,
            }
        ),
    )
    return PeriodicPeakSelection(
        value=evaluated.value,
        selected_fields=selected,
        omissions=tuple(omissions),
        steps=steps,
    )


def _clearance_route(
    kind: InsulationType,
    effective: EffectiveCase,
) -> str:
    pollution = effective.pollution_degree.value
    if pollution is None:
        raise RequiredStressError("pollution_degree is required for a Part 4 calculation")
    return (
        f"iec60664-4:clearance:{kind.value}:stress=periodic_peak_v:"
        f"frequency=frequency_hz:pollution={pollution}"
    )


def _creepage_route(kind: InsulationType, effective: EffectiveCase) -> str:
    construction = effective.construction_type.value
    pollution = effective.pollution_degree.value
    if construction is None or pollution is None:
        raise RequiredStressError(
            "construction_type and pollution_degree are required for Part 4 creepage"
        )
    return (
        f"iec60664-4:creepage:{kind.value}:stress=periodic_peak_v:"
        f"frequency=frequency_hz:construction={construction.value}:"
        f"pollution={pollution}"
    )


def _distance_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    variables: dict[str, Quantity],
    rules: RulePackage,
    prefix_steps: tuple[TraceStep, ...] = (),
) -> DistanceCandidate:
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=candidate_id,
    )
    evaluated = _evaluate_distance(formula, variables, rules, candidate_id)
    return _candidate_from_evaluated(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=stress,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula=formula,
        evaluated=evaluated,
        steps=(*prefix_steps, *evaluated.steps),
    )


def _optional_distance_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    variables: dict[str, Quantity],
    rules: RulePackage,
    prefix_steps: tuple[TraceStep, ...] = (),
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
        prefix_steps=prefix_steps,
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


def _mapped_steps(
    evaluated: EvaluatedValue,
    semantic_rule_id: str,
    reason: str,
) -> tuple[TraceStep, ...]:
    return evaluated.steps[:-1] + (
        evaluated.steps[-1].model_copy(
            update={"semantic_rule_id": semantic_rule_id, "reason": reason}
        ),
    )


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


def _formula_by_id(rules: RulePackage, formula_id: str) -> Formula:
    matches = tuple(formula for formula in rules.formulas if formula.id == formula_id)
    if len(matches) != 1:
        raise RuleMappingError(f"required IEC formula {formula_id!r} must exist exactly once")
    return matches[0]


def _evaluate_scalar_formula(
    formula: Formula,
    variables: dict[str, Decimal],
    *,
    expected_unit: str,
) -> EvaluatedValue:
    """Evaluate imported normalized equations, then apply their declared IEC unit."""
    if formula.unit != expected_unit:
        raise RuleMappingError(
            f"formula {formula.id!r} declares {formula.unit!r}, expected {expected_unit!r}"
        )
    try:
        raw = evaluate_formula(
            formula.expression,
            {name: Quantity(value=value, unit="1") for name, value in variables.items()},
            {},
        )
    except EvaluationError as error:
        raise CalculationError(f"formula {formula.id!r} failed: {error}") from error
    if raw.unit not in ("1", "bool"):
        raise RuleMappingError(
            f"normalized formula {formula.id!r} produced invalid scalar unit {raw.unit!r}"
        )
    output_unit = "bool" if expected_unit == "bool" else expected_unit
    final = raw.steps[-1].model_copy(
        update={
            "semantic_rule_id": formula.id,
            "source_reference": formula.source,
            "formula_source_reference": formula.source,
            "applicability": formula.applicability,
            "output": Quantity(value=raw.value, unit=output_unit),
            "reason": f"normalized IEC expression evaluated as {expected_unit}",
        }
    )
    return EvaluatedValue(
        value=raw.value,
        unit=output_unit,
        steps=(*raw.steps[:-1], final),
    )


def _evaluate_distance(
    formula: Formula,
    variables: dict[str, Quantity],
    rules: RulePackage,
    label: str,
) -> EvaluatedValue:
    evaluated = _evaluate(formula, variables, rules, label)
    if evaluated.unit != "mm":
        raise HighFrequencyCalculationError(
            "HF_DISTANCE_UNIT_INVALID",
            f"{label} formula {formula.id!r} returned {evaluated.unit!r}, expected canonical 'mm'",
        )
    if evaluated.value < 0:
        raise HighFrequencyCalculationError(
            "HF_DISTANCE_NEGATIVE",
            f"{label} formula {formula.id!r} returned a negative distance",
        )
    return evaluated


def _tables(rules: RulePackage) -> dict[str, Table]:
    return {table.id: table for table in rules.tables}
