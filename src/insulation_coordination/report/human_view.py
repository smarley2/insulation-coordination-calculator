"""Human-facing projection of the validated report snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.report.model import (
    MatrixRow,
    PairCalculationReport,
    ReportModel,
    ReportStress,
)


@dataclass(frozen=True)
class HumanValue:
    name: str
    value: str
    provenance: str = ""


@dataclass(frozen=True)
class HumanMatrix:
    name: str
    unit: str
    headers: tuple[str, ...]
    values: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class HumanCandidate:
    name: str
    stress: str
    distance: str
    reason: str
    source_reference: SourceReference | None


@dataclass(frozen=True)
class HumanAdvisory:
    code: str
    message: str
    source_reference: SourceReference | None


@dataclass(frozen=True)
class HumanPairCalculation:
    pair_label: str
    effective_conditions: tuple[HumanValue, ...]
    stresses: tuple[ReportStress, ...]
    clearance_candidates: tuple[HumanCandidate, ...]
    creepage_candidates: tuple[HumanCandidate, ...]
    clearance_explanation: str
    creepage_explanation: str
    pre_altitude_clearance: str
    altitude_correction_applied: bool
    clearance: str
    creepage: str
    warnings: tuple[HumanAdvisory, ...]
    verification_requirements: tuple[HumanAdvisory, ...]


@dataclass(frozen=True)
class HumanGroup:
    name: str
    pair_labels: tuple[str, ...]
    calculations: tuple[HumanPairCalculation, ...]


@dataclass(frozen=True)
class HumanReportView:
    common_values: tuple[HumanValue, ...]
    comparison_matrices: tuple[HumanMatrix, ...]
    groups: tuple[HumanGroup, ...]
    advisories: tuple[HumanAdvisory, ...]
    verification_requirements: tuple[HumanAdvisory, ...]
    rules: object


def build_human_report_view(model: ReportModel) -> HumanReportView:
    """Derive display-only report data without weakening report validation."""
    headers = tuple(net.name for net in model.net_classes)
    common_values: list[HumanValue] = []
    matrices: list[HumanMatrix] = []
    specs: tuple[tuple[str, str, str, Callable[[MatrixRow], str]], ...] = (
        ("Frequency", "Hz", "frequency", lambda row: _effective_text(row.frequency.value, "Hz")),
        ("Impulse", "V", "impulse", lambda row: _effective_text(row.impulse.value, "V")),
        ("Insulation type", "", "insulation", lambda row: row.insulation_type or "—"),
        ("Field condition", "", "field", lambda row: row.field_condition or "—"),
        (
            "Electrode radius",
            "mm",
            "radius",
            lambda row: _effective_text(row.electrode_radius_mm, "mm"),
        ),
        ("Altitude", "m", "altitude", lambda row: _effective_text(row.altitude_m, "m")),
        (
            "Pollution degree",
            "",
            "pollution",
            lambda row: _effective_text(row.pollution_degree, ""),
        ),
        ("Construction", "", "construction", lambda row: row.construction_type or "—"),
        (
            "CTI/material group",
            "",
            "cti",
            lambda row: row.cti_or_material_group or "—",
        ),
        *tuple(
            (
                stress_name,
                "V",
                stress_name,
                lambda row, stress_name=stress_name: _stress_text(row, stress_name),
            )
            for stress_name in (
                "long-term RMS",
                "steady-state peak",
                "recurring peak",
                "temporary overvoltage peak",
            )
        ),
        ("Required clearance", "mm", "clearance", lambda row: _effective_text(row.clearance_mm, "mm")),
        ("Required creepage", "mm", "creepage", lambda row: _effective_text(row.creepage_mm, "mm")),
    )
    for name, unit, _key, value_getter in specs:
        values = tuple(value_getter(row) for row in model.matrix_rows)
        if not values:
            continue
        if len(set(values)) == 1:
            common_values.append(HumanValue(name=name, value=values[0], provenance="common"))
        else:
            matrices.append(
                _matrix_for(name, unit, headers, model.matrix_rows, value_getter)
            )

    row_by_id = {row.pair_id: row for row in model.matrix_rows}
    report_groups: list[HumanGroup] = []
    for group_index, group in enumerate(model.groups, start=1):
        calculations = tuple(
            _human_calculation(row_by_id[calculation.pair_id], calculation)
            for calculation in group.calculations
        )
        report_groups.append(
            HumanGroup(
                name=f"Group {group_index}",
                pair_labels=tuple(calculation.pair_label for calculation in calculations),
                calculations=calculations,
            )
        )

    warnings = _deduplicate_advisories(model.warnings)
    verification_requirements = _deduplicate_advisories(model.verification_requirements)
    warning_codes = {item.code for item in warnings}
    verification_requirements = tuple(
        item for item in verification_requirements if item.code not in warning_codes
    )
    return HumanReportView(
        common_values=tuple(common_values),
        comparison_matrices=tuple(matrices),
        groups=tuple(report_groups),
        advisories=warnings,
        verification_requirements=verification_requirements,
        rules=model.rules,
    )


def _matrix_for(
    name: str,
    unit: str,
    headers: tuple[str, ...],
    rows: tuple[MatrixRow, ...],
    value_getter: Callable[[MatrixRow], str],
) -> HumanMatrix:
    by_pair = {frozenset((row.net_a, row.net_b)): value_getter(row) for row in rows}
    values = tuple(
        tuple(
            "—"
            if row_header == column_header
            else by_pair.get(frozenset((row_header, column_header)), "—")
            for column_header in headers
        )
        for row_header in headers
    )
    return HumanMatrix(name=name, unit=unit, headers=headers, values=values)


def _human_calculation(row: MatrixRow, calculation: PairCalculationReport) -> HumanPairCalculation:
    conditions = (
        HumanValue("Frequency", _effective_text(calculation.effective_inputs.frequency_hz.value, "Hz"), calculation.effective_inputs.frequency_hz.provenance.value),
        HumanValue("Impulse", _effective_text(calculation.effective_inputs.impulse_v.value, "V"), calculation.effective_inputs.impulse_v.provenance.value),
        HumanValue("Insulation type", _value_text(calculation.effective_inputs.insulation_type.value), calculation.effective_inputs.insulation_type.provenance.value),
        HumanValue("Field condition", _value_text(calculation.effective_inputs.field_condition.value), calculation.effective_inputs.field_condition.provenance.value),
        HumanValue("Altitude", _effective_text(calculation.effective_inputs.altitude_m.value, "m"), calculation.effective_inputs.altitude_m.provenance.value),
        HumanValue("Pollution degree", _effective_text(calculation.effective_inputs.pollution_degree.value, ""), calculation.effective_inputs.pollution_degree.provenance.value),
        HumanValue("Construction", _value_text(calculation.effective_inputs.construction_type.value), calculation.effective_inputs.construction_type.provenance.value),
        HumanValue("CTI/material group", _value_text(calculation.effective_inputs.cti_or_material_group.value), calculation.effective_inputs.cti_or_material_group.provenance.value),
    )
    return HumanPairCalculation(
        pair_label=f"{row.net_a} ↔ {row.net_b}",
        effective_conditions=conditions,
        stresses=calculation.stresses,
        clearance_candidates=tuple(_candidate(candidate) for candidate in calculation.clearance_candidates),
        creepage_candidates=tuple(_candidate(candidate) for candidate in calculation.creepage_candidates),
        clearance_explanation=_sentence(calculation.governing_clearance_reason),
        creepage_explanation=_sentence(calculation.governing_creepage_reason),
        pre_altitude_clearance=_effective_text(calculation.pre_altitude_clearance_mm, "mm"),
        altitude_correction_applied=calculation.altitude_correction_applied,
        clearance=_effective_text(calculation.clearance_mm, "mm"),
        creepage=_effective_text(calculation.creepage_mm, "mm"),
        warnings=tuple(_advisory(item) for item in calculation.warnings),
        verification_requirements=tuple(_advisory(item) for item in calculation.verification_requirements),
    )


def _candidate(candidate: object) -> HumanCandidate:
    source_reference = next(
        (
            step.source_reference
            for step in reversed(getattr(candidate, "steps", ()))
            if step.source_reference is not None
        ),
        None,
    )
    return HumanCandidate(
        name=_candidate_name(getattr(candidate, "candidate_id", "candidate")),
        stress=_sentence(getattr(getattr(candidate, "stress", None), "value", "")),
        distance=_effective_text(getattr(candidate, "distance_mm", None), "mm"),
        reason=_sentence(getattr(candidate, "reason", "")),
        source_reference=source_reference,
    )


def _advisory(item: object) -> HumanAdvisory:
    return HumanAdvisory(
        code=getattr(item, "code", ""),
        message=_sentence(getattr(item, "message", "")),
        source_reference=getattr(item, "source_reference", None),
    )


def _deduplicate_advisories(items: tuple[object, ...]) -> tuple[HumanAdvisory, ...]:
    result: list[HumanAdvisory] = []
    seen: set[str] = set()
    for item in items:
        advisory = _advisory(item)
        if advisory.code in seen:
            continue
        seen.add(advisory.code)
        result.append(advisory)
    return tuple(result)


def _candidate_name(value: str) -> str:
    names = {
        "impulse": "Impulse withstand",
        "steady_state_peak": "Steady-state peak",
        "recurring_peak": "Recurring peak",
        "temporary_overvoltage_peak": "Temporary overvoltage peak",
        "long_term_rms_tracking": "Long-term RMS tracking",
        "clearance_floor": "Clearance floor",
    }
    return names.get(value, _sentence(value.replace("_", " ")))


def _stress_text(row: MatrixRow, name: str) -> str:
    stress = next((item for item in row.stresses if item.name == name), None)
    if stress is None or stress.value_v is None:
        return "N/A" if stress is not None and stress.applicability == "not_applicable" else "—"
    return _effective_text(stress.value_v, "V")


def _effective_text(value: object, unit: str) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    else:
        text = str(getattr(value, "value", value))
    return f"{text} {unit}".strip()


def _value_text(value: object) -> str:
    if value is None:
        return "—"
    return str(getattr(value, "value", value)).replace("_", " ")


def _sentence(value: str) -> str:
    text = str(value or "").replace("_", " ").strip()
    if not text:
        return "No additional explanation."
    return text[0].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")
