from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import field_validator

from insulation_coordination.domain.enums import (
    Applicability,
    FieldCondition,
    InsulationType,
    Provenance,
)
from insulation_coordination.domain.project import EffectiveCase, FrozenModel, PairVoltage
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import (
    CompatibilityMapping,
    Formula,
    RulePackage,
    SourceReference,
    TableSelect,
)
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula
from insulation_coordination.rules.validation import ValidationResult, validate_rule_package

if TYPE_CHECKING:
    from insulation_coordination.calculation.reinforced_rules import ReinforcedRuleSet


class CalculationError(ValueError):
    """An effective case cannot be calculated from the approved rules."""


class RequiredStressError(CalculationError):
    """A required stress input is blank."""


class UnsupportedCaseError(CalculationError):
    """The case requires behavior outside the Part 1 engine."""


class RuleMappingError(CalculationError):
    """No single approved semantic route exists for the case."""


class CalculationRangeError(CalculationError):
    """An input is outside the range supported by its selected rule."""


class RulePackageValidationError(CalculationError):
    """The complete rules package failed its calculation trust gate."""

    def __init__(self, issues: tuple[ValidationResult, ...]) -> None:
        self.issues = issues
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        super().__init__(f"rule package validation failed: {detail}")

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


class DistanceCandidate(FrozenModel):
    candidate_id: str
    stress_field: str
    stress: Quantity
    treated_stress: Quantity | None = None
    distance_mm: DecimalValue
    semantic_rule_id: str
    mapping_id: str | None = None
    formula_id: str | None = None
    provenance: Provenance | None = None
    selection_mode: str = ""
    branch_label: str | None = None
    steps: tuple[TraceStep, ...] = ()
    reason: str

    @field_validator("distance_mm")
    @classmethod
    def _nonnegative_distance(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("Distance must be a nonnegative finite Decimal")
        return value


class CandidateOmission(FrozenModel):
    candidate_id: str
    stress_field: str
    applicability: Applicability
    justification: str


class CandidateCalculation(FrozenModel):
    candidates: tuple[DistanceCandidate, ...]
    omissions: tuple[CandidateOmission, ...]


_CLEARANCE_STRESSES = (
    ("steady_state_peak", "steady_state_peak_v"),
    ("temporary_overvoltage_peak", "temporary_overvoltage_peak_v"),
    ("recurring_peak", "recurring_peak_v"),
)


def calculate_clearance_candidates(
    effective: EffectiveCase,
    rules: RulePackage,
) -> tuple[DistanceCandidate, ...]:
    _require_valid_rule_package(rules)
    return _calculate_clearance(effective, rules).candidates


def _calculate_clearance(
    effective: EffectiveCase,
    rules: RulePackage,
) -> CandidateCalculation:
    manual, omissions = _manual_stresses(effective)
    candidates = (
        select_f2_impulse_clearance(effective, rules),
        *(
            select_f8_periodic_clearance(
                effective,
                rules,
                candidate_id=candidate_id,
                stress_field=stress_field,
                stress=stress,
            )
            for candidate_id, stress_field, stress in manual
        ),
    )
    return CandidateCalculation(candidates=candidates, omissions=omissions)


#: Which quantity of the treatment rule's own vocabulary each candidate's stress is. Structural:
#: it says what this application is asking about, never what the answer is.
TREATED_QUANTITY_BY_STRESS_FIELD: dict[str, str] = {
    "impulse_v": "impulse_withstand_voltage",
    "temporary_overvoltage_peak_v": "temporary_overvoltage_peak",
    "steady_state_peak_v": "working_voltage_peak",
    "recurring_peak_v": "working_voltage_peak",
}

#: The operation token the trace and the report key the clearance treatment on.
REINFORCED_STRESS_OPERATION = "reinforced_stress_treatment"


def apply_reinforced_stress_treatment(
    stress_v: Decimal,
    *,
    kind: InsulationType,
    stress_field: str,
    reinforced: ReinforcedRuleSet | None,
    source: SourceReference | None = None,
) -> tuple[Decimal, TraceStep | None]:
    """Dimension one clearance stress for the stronger insulation, if its class calls for one.

    A class this application applies no treatment to is answered unchanged and reads no rule at
    all, which is what keeps a package carrying no treatment route from blocking every
    functional and basic pair in an existing project.

    A reinforced pair reads the route. ``reinforced`` is the resolved rule set, and ``None``
    means no package could supply one - which blocks, because there is nothing here to
    dimension from instead.
    """

    # Imported inside the function: ``reinforced_rules`` takes its exception base from this
    # module, so a module-scope import back would close the cycle. The annotation above is
    # deferred by ``from __future__ import annotations`` and resolved from the guarded import.
    from insulation_coordination.calculation.reinforced_rules import (
        CLEARANCE_ROUTE,
        apply_reinforced_treatment,
        read_reinforced_rules,
    )

    if kind is not InsulationType.REINFORCED:
        return stress_v, None
    quantity = TREATED_QUANTITY_BY_STRESS_FIELD.get(stress_field)
    if quantity is None:
        raise UnsupportedCaseError(
            f"{stress_field} is not a quantity the reinforced treatment rule is asked about"
        )
    return apply_reinforced_treatment(
        stress_v,
        # ``read_reinforced_rules(None)`` raises the no-package block rather than returning
        # one, which is the whole of what an absent package earns here.
        rules=reinforced if reinforced is not None else read_reinforced_rules(None),
        unit="V",
        route=CLEARANCE_ROUTE,
        insulation_class=kind.value,
        treated_quantity=quantity,
        source=source,
        operation=REINFORCED_STRESS_OPERATION,
    )


def reinforced_stress_floor(
    stress_v: Decimal,
    *,
    kind: InsulationType,
    stress_field: str,
    reinforced: ReinforcedRuleSet | None,
) -> Decimal:
    """The lowest stress whose reinforced treatment still reaches ``stress_v``.

    The inverse of :func:`apply_reinforced_stress_treatment`, and the seam a caller holding a
    floor under a *treated* figure uses to express it as a floor under the untreated stress
    this engine is handed. Going through this function rather than restating the inverse is
    what keeps the two directions reading the same rule and mapping the same quantity.

    A class this application applies no treatment to is its own floor, and reads no rule -
    the same answer, for the same reason, that the forward direction gives.
    """

    from insulation_coordination.calculation.reinforced_rules import (
        CLEARANCE_ROUTE,
        read_reinforced_rules,
        untreated_floor,
    )

    if kind is not InsulationType.REINFORCED:
        return stress_v
    quantity = TREATED_QUANTITY_BY_STRESS_FIELD.get(stress_field)
    if quantity is None:
        raise UnsupportedCaseError(
            f"{stress_field} is not a quantity the reinforced treatment rule is asked about"
        )
    return untreated_floor(
        stress_v,
        rules=reinforced if reinforced is not None else read_reinforced_rules(None),
        route=CLEARANCE_ROUTE,
        insulation_class=kind.value,
        treated_quantity=quantity,
    )


def select_f2_impulse_clearance(
    effective: EffectiveCase,
    rules: RulePackage,
) -> DistanceCandidate:
    kind = _required(effective.insulation_type.value, "insulation_type")
    field = _required(effective.field_condition.value, "field_condition")
    pollution = _required(effective.pollution_degree.value, "pollution_degree")
    stress = _required_stress(effective.impulse_v.value, "impulse_v")
    return _select_part1_clearance(
        candidate_id="impulse",
        stress_field="impulse_v",
        stress=stress,
        treatment="impulse",
        kind=kind,
        field=field,
        pollution=pollution,
        rules=rules,
        provenance=effective.impulse_v.provenance,
    )


def select_f8_periodic_clearance(
    effective: EffectiveCase,
    rules: RulePackage,
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
) -> DistanceCandidate:
    kind = _required(effective.insulation_type.value, "insulation_type")
    field = _required(effective.field_condition.value, "field_condition")
    pollution = _required(effective.pollution_degree.value, "pollution_degree")
    return _select_part1_clearance(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=stress,
        treatment="periodic",
        kind=kind,
        field=field,
        pollution=pollution,
        rules=rules,
    )


def _select_part1_clearance(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    treatment: str,
    kind: InsulationType,
    field: FieldCondition,
    pollution: int,
    rules: RulePackage,
    provenance: Provenance | None = None,
) -> DistanceCandidate:
    clause = "5.2.4" if kind is InsulationType.FUNCTIONAL else "5.2.5"
    semantic_rule_id = (
        f"iec60664-1:{clause}:{kind.value}_clearance:"
        f"candidate={treatment}:field={field.value}:pollution={pollution}"
    )
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=f"{kind.value}_clearance_{treatment}",
    )
    if not isinstance(formula.expression, TableSelect):
        return _evaluate_candidate(
            candidate_id=candidate_id,
            stress_field=stress_field,
            stress=stress,
            semantic_rule_id=semantic_rule_id,
            mapping_id=mapping.id,
            formula=formula,
            rules=rules,
            provenance=provenance,
        )
    treated, treatment_step = apply_reinforced_stress_treatment(
        stress,
        kind=kind,
        stress_field=stress_field,
        reinforced=_reinforced_rules(rules, kind),
        source=mapping.source,
    )
    branch_label = _clearance_branch_label(
        treatment=treatment,
        field=field,
        pollution=pollution,
    )
    table = next(
        (item for item in rules.tables if item.id == formula.expression.table_id),
        None,
    )
    if table is None:
        raise RuleMappingError(f"formula {formula.id!r} references a missing clearance table")
    if table.row_axis.unit != "kV":
        raise RuleMappingError(f"clearance table {table.id!r} row axis must use canonical 'kV'")
    try:
        column_index = table.column_axis.labels.index(branch_label)
    except ValueError as error:
        raise RuleMappingError(
            f"clearance table {table.id!r} has no semantic branch {branch_label!r}"
        ) from error
    variables = {
        table.row_axis.id: Quantity(value=treated / Decimal(1000), unit="kV"),
        table.column_axis.id: Quantity(
            value=table.column_axis.values[column_index],
            unit=table.column_axis.unit,
        ),
    }
    try:
        evaluated = evaluate_formula(
            formula,
            variables,
            {item.id: item for item in rules.tables},
        )
    except EvaluationError as error:
        message = f"{candidate_id} candidate using formula {formula.id!r} failed: {error}"
        if "outside" in str(error) or "has no cell" in str(error):
            raise CalculationRangeError(message) from error
        raise CalculationError(message) from error
    if evaluated.value < 0:
        raise CalculationError(
            f"{candidate_id} formula {formula.id!r} returned a negative distance"
        )
    steps = (
        *((treatment_step,) if treatment_step is not None else ()),
        *evaluated.steps,
    )
    return DistanceCandidate(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=Quantity(value=stress, unit="V"),
        treated_stress=Quantity(value=treated, unit="V"),
        distance_mm=evaluated.value,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula_id=formula.id,
        provenance=provenance,
        selection_mode=f"{formula.expression.row_mode}/{formula.expression.column_mode}",
        branch_label=branch_label,
        steps=steps,
        reason=steps[-1].reason,
    )


def _reinforced_rules(rules: RulePackage, kind: InsulationType) -> ReinforcedRuleSet | None:
    """The treatment routes of ``rules``, resolved only for a class that reads them.

    A functional or basic pair never asks, so a package that cannot answer never blocks one.
    """

    from insulation_coordination.calculation.reinforced_rules import read_reinforced_rules

    if kind is not InsulationType.REINFORCED:
        return None
    return read_reinforced_rules(rules)


def _clearance_branch_label(
    *,
    treatment: str,
    field: FieldCondition,
    pollution: int,
) -> str:
    case = "case_a" if field is FieldCondition.INHOMOGENEOUS else "case_b"
    if treatment == "impulse":
        return f"{case}_pd{pollution}_mm"
    return f"{case}_mm"


def _evaluate_clearance_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    treatment: str,
    clause: str,
    kind: InsulationType,
    field: str,
    pollution: int,
    rules: RulePackage,
    provenance: Provenance | None = None,
) -> DistanceCandidate:
    semantic_rule_id = (
        f"iec60664-1:{clause}:{kind.value}_clearance:"
        f"candidate={treatment}:field={field}:pollution={pollution}"
    )
    mapping, formula = _select_formula(
        rules,
        semantic_rule_id,
        route_label=f"{kind.value}_clearance_{treatment}",
    )
    return _evaluate_candidate(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=stress,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping.id,
        formula=formula,
        rules=rules,
        provenance=provenance,
    )


def _manual_stresses(
    effective: EffectiveCase,
) -> tuple[tuple[tuple[str, str, Decimal], ...], tuple[CandidateOmission, ...]]:
    stresses: list[tuple[str, str, Decimal]] = []
    omissions: list[CandidateOmission] = []
    for candidate_id, stress_field in _CLEARANCE_STRESSES:
        voltage = getattr(effective.voltages, stress_field)
        if voltage.applicability is Applicability.BLANK:
            raise RequiredStressError(
                f"{stress_field} is blank; enter a canonical V value or mark it "
                "not applicable with a justification"
            )
        if voltage.applicability is Applicability.NOT_APPLICABLE:
            assert voltage.justification is not None
            omissions.append(
                CandidateOmission(
                    candidate_id=candidate_id,
                    stress_field=stress_field,
                    applicability=voltage.applicability,
                    justification=voltage.justification,
                )
            )
            continue
        stresses.append((candidate_id, stress_field, _applicable_stress(voltage, stress_field)))
    return tuple(stresses), tuple(omissions)


def _applicable_stress(voltage: PairVoltage, stress_field: str) -> Decimal:
    if voltage.value is None:
        raise RequiredStressError(f"{stress_field} is applicable but has no V value")
    return voltage.value


def _required_stress(value: Decimal | None, field: str) -> Decimal:
    if value is None:
        raise RequiredStressError(f"{field} is blank; enter a canonical V value")
    return value


def _required[T](value: T | None, field: str) -> T:
    if value is None:
        raise RequiredStressError(f"{field} is required for a Part 1 calculation")
    return value


def _require_valid_rule_package(rules: RulePackage) -> None:
    report = validate_rule_package(rules)
    issues = tuple(result for result in report.results if not result.passed)
    if issues:
        raise RulePackageValidationError(issues)


def _select_formula(
    rules: RulePackage,
    semantic_rule_id: str,
    *,
    route_label: str,
) -> tuple[CompatibilityMapping, Formula]:
    if not rules.manifest.approved or not rules.manifest.compatible:
        raise RuleMappingError("rule package must be approved and compatible before calculation")
    mappings = tuple(
        mapping for mapping in rules.mappings if mapping.source_rule_id == semantic_rule_id
    )
    if len(mappings) != 1:
        state = "missing" if not mappings else "ambiguous"
        raise RuleMappingError(
            f"{route_label} mapping is {state} for semantic route {semantic_rule_id!r}; "
            "add exactly one approved compatibility mapping"
        )
    mapping = mappings[0]
    if not mapping.approved:
        raise RuleMappingError(f"mapping {mapping.id!r} for {semantic_rule_id!r} is not approved")
    formulas = tuple(formula for formula in rules.formulas if formula.id == mapping.target_rule_id)
    if len(formulas) != 1:
        state = "missing" if not formulas else "ambiguous"
        raise RuleMappingError(
            f"target formula {mapping.target_rule_id!r} is {state} for mapping {mapping.id!r}"
        )
    return mapping, formulas[0]


def _evaluate_candidate(
    *,
    candidate_id: str,
    stress_field: str,
    stress: Decimal,
    semantic_rule_id: str,
    mapping_id: str,
    formula: Formula,
    rules: RulePackage,
    provenance: Provenance | None = None,
) -> DistanceCandidate:
    try:
        evaluated = evaluate_formula(
            formula,
            {"stress_v": Quantity(value=stress, unit="V")},
            {table.id: table for table in rules.tables},
        )
    except EvaluationError as error:
        message = f"{candidate_id} candidate using formula {formula.id!r} failed: {error}"
        if "outside" in str(error) and "range" in str(error):
            raise CalculationRangeError(message) from error
        raise CalculationError(message) from error
    if evaluated.unit != "mm":
        raise CalculationError(
            f"{candidate_id} formula {formula.id!r} returned {evaluated.unit!r}, "
            "expected canonical 'mm'"
        )
    if evaluated.value < 0:
        raise CalculationError(
            f"{candidate_id} formula {formula.id!r} returned a negative distance"
        )
    return DistanceCandidate(
        candidate_id=candidate_id,
        stress_field=stress_field,
        stress=Quantity(value=stress, unit="V"),
        treated_stress=Quantity(value=stress, unit="V"),
        distance_mm=evaluated.value,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping_id,
        formula_id=formula.id,
        provenance=provenance,
        steps=evaluated.steps,
        reason=evaluated.steps[-1].reason,
    )
