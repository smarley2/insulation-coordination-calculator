from __future__ import annotations

from decimal import Decimal

from pydantic import field_validator

from insulation_coordination.domain.enums import Applicability, InsulationType, Provenance
from insulation_coordination.domain.project import EffectiveCase, FrozenModel, PairVoltage
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import CompatibilityMapping, Formula, RulePackage
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import EvaluationError, evaluate_formula
from insulation_coordination.rules.validation import ValidationResult, validate_rule_package


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
    distance_mm: DecimalValue
    semantic_rule_id: str
    mapping_id: str | None = None
    formula_id: str | None = None
    provenance: Provenance | None = None
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
    kind = _required(effective.insulation_type.value, "insulation_type")
    field = _required(effective.field_condition.value, "field_condition")
    pollution = _required(effective.pollution_degree.value, "pollution_degree")
    impulse = _required_stress(effective.impulse_v.value, "impulse_v")
    manual, omissions = _manual_stresses(effective)
    clause = "5.2.4" if kind is InsulationType.FUNCTIONAL else "5.2.5"
    candidates = (
        _evaluate_clearance_candidate(
            candidate_id="impulse",
            stress_field="impulse_v",
            stress=impulse,
            treatment="impulse",
            clause=clause,
            kind=kind,
            field=field.value,
            pollution=pollution,
            rules=rules,
            provenance=effective.impulse_v.provenance,
        ),
        *(
            _evaluate_clearance_candidate(
                candidate_id=candidate_id,
                stress_field=stress_field,
                stress=stress,
                treatment="periodic",
                clause=clause,
                kind=kind,
                field=field.value,
                pollution=pollution,
                rules=rules,
            )
            for candidate_id, stress_field, stress in manual
        ),
    )
    return CandidateCalculation(candidates=candidates, omissions=omissions)


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
        distance_mm=evaluated.value,
        semantic_rule_id=semantic_rule_id,
        mapping_id=mapping_id,
        formula_id=formula.id,
        provenance=provenance,
        steps=evaluated.steps,
        reason=evaluated.steps[-1].reason,
    )
