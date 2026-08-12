"""Validated frozen snapshot consumed by report renderers."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError, field_validator

from insulation_coordination.calculation.clearance import CandidateOmission, DistanceCandidate
from insulation_coordination.calculation.engine import (
    CALCULATION_ENGINE_VERSION,
    CalculationError,
    CalculationWarning,
    EffectiveInputSnapshot,
    PairResult,
    VerificationRequirement,
    calculate_pair,
)
from insulation_coordination.calculation.grouping import CalculationGroup, calculation_signature
from insulation_coordination.calculation.high_frequency import FieldIteration
from insulation_coordination.domain.enums import ReviewState
from insulation_coordination.domain.project import (
    EffectiveCase,
    EffectiveValue,
    FrozenModel,
    NetClass,
    PairCase,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.rules import (
    ApprovalRecord,
    RulePackage,
    SourceDocument,
    SourceReference,
)
from insulation_coordination.domain.topology import (
    GalvanicBarrier,
    GalvanicDomain,
    TopologyCompletion,
    topology_completion,
)
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.project.image_attachments import (
    ImageAttachmentError,
    stage_report_image,
)
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.rules.validation import validate_rule_package


class ReportBuildError(ValueError):
    """Project, result, grouping, and rules snapshots do not reconcile."""


class ReportEffectiveValue(FrozenModel):
    value: Decimal | int | str | tuple[str, ...] | None
    provenance: str


class ReportStress(FrozenModel):
    name: str
    applicability: str
    value_v: Decimal | None
    justification: str | None
    provenance: Literal["pair_input"]


class TrustedFormulaLatex(FrozenModel):
    latex: str
    origin: Literal["engine", "approved_rules"]

    @field_validator("latex")
    @classmethod
    def _safe_math_latex(cls, value: str) -> str:
        _validate_math_latex(value)
        return value


class ReportStep(FrozenModel):
    semantic_rule_id: str
    operation: str
    symbolic_latex: TrustedFormulaLatex
    substituted_latex: TrustedFormulaLatex
    inputs: tuple[Quantity, ...]
    source_reference: SourceReference | None
    formula_source_reference: SourceReference | None
    source_cells: tuple[str, ...]
    cell_references: tuple[SourceReference, ...]
    applicability: str
    output: Quantity
    unrounded_value: Decimal
    rounded_value: Decimal | None
    reason: str


class MatrixRow(FrozenModel):
    pair_id: str
    pair_key: str
    result_sha256: str
    net_a: str
    net_b: str
    stresses: tuple[ReportStress, ...]
    frequency: ReportEffectiveValue
    impulse: ReportEffectiveValue
    insulation_type: str
    insulation_type_provenance: str
    field_condition: str
    field_condition_provenance: str
    electrode_radius_mm: Decimal | None
    electrode_radius_provenance: str
    construction_type: str
    construction_type_provenance: str
    cti_or_material_group: str | None
    cti_or_material_group_provenance: str
    pollution_degree: int | None
    pollution_degree_provenance: str
    altitude_m: Decimal | None
    altitude_provenance: str
    clearance_mm: Decimal
    creepage_mm: Decimal
    inner_clearance_mm: Decimal
    inner_creepage_mm: Decimal
    governing_clearance_path: str
    governing_creepage_path: str
    group_id: str


class PairCalculationReport(FrozenModel):
    pair_id: str
    pair_key: str
    result_sha256: str
    effective_inputs: EffectiveInputSnapshot
    stresses: tuple[ReportStress, ...]
    clearance_candidates: tuple[DistanceCandidate, ...]
    creepage_candidates: tuple[DistanceCandidate, ...]
    omissions: tuple[CandidateOmission, ...]
    hf_iterations: tuple[FieldIteration, ...]
    pre_altitude_clearance_mm: Decimal
    altitude_correction_applied: bool
    governing_clearance_candidate_id: str
    governing_clearance_reason: str
    governing_creepage_candidate_id: str
    governing_creepage_reason: str
    clearance_mm: Decimal
    creepage_mm: Decimal
    inner_clearance_mm: Decimal
    inner_creepage_mm: Decimal
    steps: tuple[ReportStep, ...]
    warnings: tuple[CalculationWarning, ...]
    verification_requirements: tuple[VerificationRequirement, ...]


class ReportGroup(FrozenModel):
    group_id: str
    signature: str
    pair_ids: tuple[str, ...]
    calculations: tuple[PairCalculationReport, ...]


class RulesProvenance(FrozenModel):
    package_id: str
    version: str
    package_sha256: str
    schema_version: int
    decision_count: int
    procedure_count: int
    guidance_count: int
    curve_count: int
    importer_version: str
    created_at: str
    approved: bool
    compatible: bool
    source_documents: tuple[SourceDocument, ...]
    approval_records: tuple[ApprovalRecord, ...]
    notes: str


class ExcludedPair(FrozenModel):
    """A pair left out of the analysis because every stress is not applicable."""

    pair_id: str
    pair_key: str
    net_a: str
    net_b: str
    notes: str | None


class ReportImage(FrozenModel):
    """One image already staged next to the document that will include it.

    The renderer never sees a user path: ``staged_filename`` is derived from the
    content hash and constrained to characters that are safe in a LaTeX
    ``\\includegraphics`` argument.
    """

    role: str
    staged_filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    caption: str
    source_note: str
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportModel(FrozenModel):
    project_id: str
    project_sha256: str
    project_title: str
    project_metadata: ProjectMetadata
    application_version: str
    calculation_engine_version: str
    defaults: ProjectDefaults
    net_classes: tuple[NetClass, ...]
    galvanic_domains: tuple[GalvanicDomain, ...] = ()
    galvanic_barriers: tuple[GalvanicBarrier, ...] = ()
    topology: TopologyCompletion
    # `topology_completion` never reads `GalvanicDomain.review_state` (only
    # `NetClass.classification_review_state`; see domain/topology.py). This report is the
    # first consumer that discloses a domain still awaiting review, so it is read directly
    # from the domain models here rather than reshaping that helper's contract.
    domains_needing_review: tuple[UUID, ...] = ()
    matrix_rows: tuple[MatrixRow, ...]
    excluded_pairs: tuple[ExcludedPair, ...] = ()
    circuit_diagram: ReportImage | None = None
    groups: tuple[ReportGroup, ...]
    warnings: tuple[CalculationWarning, ...]
    verification_requirements: tuple[VerificationRequirement, ...]
    rules: RulesProvenance


def build_report_model(
    project: Project,
    results: tuple[PairResult, ...],
    groups: tuple[CalculationGroup, ...],
    rules: RulePackage,
    *,
    image_directory: Path | None = None,
) -> ReportModel:
    """Build a detached, deterministic report snapshot or reject stale inputs.

    ``image_directory`` is the directory the document will be written to. A
    project carrying a circuit diagram needs one: the image is staged there
    before rendering so the template only ever names a local file.
    """
    package_sha256 = rules.package_sha256
    if package_sha256 is None:
        raise ReportBuildError("rules package has no validated SHA-256 identity")
    validation = validate_rule_package(rules)
    if not validation.is_valid:
        codes = ", ".join(result.code for result in validation.results if not result.passed)
        raise ReportBuildError(f"rules package failed validation: {codes}")
    rules_identity = (
        str(rules.manifest.package_id),
        rules.manifest.version,
        package_sha256,
    )
    if project.required_rules is None:
        raise ReportBuildError("project has no rules package pin")
    project_rules_identity = (
        project.required_rules.package_id,
        project.required_rules.version,
        project.required_rules.sha256,
    )
    if project_rules_identity != rules_identity:
        raise ReportBuildError(
            "project rules package pin does not match the supplied rules package"
        )

    all_pair_ids = tuple(str(pair.id) for pair in project.pairs)
    if len(all_pair_ids) != len(set(all_pair_ids)):
        raise ReportBuildError("duplicate pair ID in project")
    # Excluded pairs carry no result: they are reported under their own heading.
    net_names = {str(net.id): net.name for net in project.net_classes}
    excluded_pairs = tuple(
        _excluded_pair(pair, net_names) for pair in project.pairs if pair.is_excluded
    )
    project_pair_ids = tuple(str(pair.id) for pair in project.pairs if not pair.is_excluded)
    if not project_pair_ids:
        raise ReportBuildError(
            "every pair is excluded from the analysis; there is nothing to report"
        )
    result_pair_ids = tuple(str(result.pair_id) for result in results)
    if len(result_pair_ids) != len(set(result_pair_ids)):
        raise ReportBuildError("duplicate pair result")
    missing = set(project_pair_ids) - set(result_pair_ids)
    extra = set(result_pair_ids) - set(project_pair_ids)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing pair results: " + ", ".join(sorted(missing)))
        if extra:
            detail.append("extra pair results: " + ", ".join(sorted(extra)))
        raise ReportBuildError("; ".join(detail))

    supplied_by_pair = {str(result.pair_id): result for result in results}
    pair_by_id = {str(pair.id): pair for pair in project.pairs}
    authoritative_by_pair: dict[str, PairResult] = {}
    for pair_id in project_pair_ids:
        pair = pair_by_id[pair_id]
        expected_effective = resolve_effective_case(project.defaults, pair)
        supplied = supplied_by_pair[pair_id]
        if supplied.effective_inputs != _effective_snapshot(expected_effective):
            raise ReportBuildError(f"pair {pair_id} effective input snapshot is stale")
        _validate_result(supplied, rules_identity)
        try:
            authoritative = calculate_pair(expected_effective, rules)
        except CalculationError as error:
            raise ReportBuildError(f"pair {pair_id} is blocked: {error}") from error
        if supplied != authoritative:
            raise ReportBuildError(
                f"pair {pair_id} result does not match authoritative recalculation"
            )
        _validate_result(authoritative, rules_identity)
        authoritative_by_pair[pair_id] = authoritative

    group_by_pair = _validate_groups(groups, authoritative_by_pair, project_pair_ids)
    matrix_rows = tuple(
        _matrix_row(
            pair_by_id[pair_id],
            authoritative_by_pair[pair_id],
            group_by_pair[pair_id],
            net_names,
        )
        for pair_id in project_pair_ids
    )
    report_groups = tuple(
        ReportGroup(
            group_id=group.group_id,
            signature=group.signature,
            pair_ids=tuple(
                pair_id for pair_id in project_pair_ids if pair_id in set(group.pair_ids)
            ),
            calculations=tuple(
                _calculation(authoritative_by_pair[pair_id])
                for pair_id in project_pair_ids
                if pair_id in set(group.pair_ids)
            ),
        )
        for group in sorted(
            groups,
            key=lambda item: min(project_pair_ids.index(pair_id) for pair_id in item.pair_ids),
        )
    )
    ordered_results = tuple(authoritative_by_pair[pair_id] for pair_id in project_pair_ids)
    return ReportModel(
        circuit_diagram=_staged_circuit_diagram(project, image_directory),
        project_id=str(project.id),
        project_sha256=_project_hash(project),
        project_title=project.metadata.title,
        project_metadata=project.metadata.model_copy(deep=True),
        application_version=project.application_version,
        calculation_engine_version=CALCULATION_ENGINE_VERSION,
        defaults=project.defaults.model_copy(deep=True),
        net_classes=tuple(net.model_copy(deep=True) for net in project.net_classes),
        galvanic_domains=tuple(domain.model_copy(deep=True) for domain in project.galvanic_domains),
        galvanic_barriers=tuple(
            barrier.model_copy(deep=True) for barrier in project.galvanic_barriers
        ),
        topology=topology_completion(project),
        domains_needing_review=tuple(
            domain.id
            for domain in project.galvanic_domains
            if domain.review_state is ReviewState.NEEDS_REVIEW
        ),
        matrix_rows=matrix_rows,
        excluded_pairs=excluded_pairs,
        groups=report_groups,
        warnings=tuple(warning for result in ordered_results for warning in result.warnings),
        verification_requirements=tuple(
            requirement
            for result in ordered_results
            for requirement in result.verification_requirements
        ),
        rules=RulesProvenance(
            package_id=str(rules.manifest.package_id),
            version=rules.manifest.version,
            package_sha256=package_sha256,
            schema_version=rules.manifest.schema_version,
            decision_count=len(rules.decisions),
            procedure_count=len(rules.procedures),
            guidance_count=len(rules.guidance),
            curve_count=len(rules.curves),
            importer_version=rules.manifest.importer_version,
            created_at=rules.manifest.created_at.isoformat(),
            approved=rules.manifest.approved,
            compatible=rules.manifest.compatible,
            source_documents=tuple(
                document.model_copy(deep=True) for document in rules.manifest.source_documents
            ),
            approval_records=tuple(
                record.model_copy(deep=True) for record in rules.manifest.approval_records
            ),
            notes=rules.manifest.notes,
        ),
    )


def _staged_circuit_diagram(project: Project, directory: Path | None) -> ReportImage | None:
    """Write the attached diagram next to the document, or block the report.

    An attached image is never silently dropped: a report that cannot carry it
    is not a report of this project.
    """
    attachment = project.circuit_diagram
    if attachment is None:
        return None
    if directory is None:
        raise ReportBuildError("the project circuit diagram needs a directory to stage into")
    try:
        staged = stage_report_image(attachment, directory)
    except ImageAttachmentError as error:
        raise ReportBuildError(f"the circuit diagram could not be staged: {error}") from error
    return ReportImage(
        role=attachment.role,
        staged_filename=staged.name,
        caption=attachment.caption,
        source_note=attachment.source_note,
        width_px=attachment.width_px,
        height_px=attachment.height_px,
        sha256=attachment.sha256,
    )


def _validate_result(result: PairResult, rules_identity: tuple[str, str, str]) -> None:
    result_rules_identity = (
        str(result.rule_package_id),
        result.rule_package_version,
        result.rule_package_sha256,
    )
    trace_rules_identity = (
        str(result.trace.rule_package_id),
        result.trace.rule_package_version,
        result.trace.rule_package_sha256,
    )
    if result_rules_identity != rules_identity or trace_rules_identity != rules_identity:
        raise ReportBuildError(f"pair {result.pair_id} rules package identity mismatch")
    if (
        result.calculation_engine_version != CALCULATION_ENGINE_VERSION
        or result.trace.calculation_engine_version != CALCULATION_ENGINE_VERSION
    ):
        raise ReportBuildError(f"pair {result.pair_id} calculation engine version mismatch")
    if (
        not result.trace.clearance_candidates
        or not result.trace.creepage_candidates
        or not result.trace.steps
    ):
        raise ReportBuildError(f"pair {result.pair_id} is blocked or incomplete")
    clearance_ids = {candidate.candidate_id for candidate in result.trace.clearance_candidates}
    creepage_ids = {candidate.candidate_id for candidate in result.trace.creepage_candidates}
    if result.trace.governing_clearance_candidate_id not in clearance_ids:
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete clearance result")
    if result.trace.governing_creepage_candidate_id not in creepage_ids:
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete creepage result")
    if any(not candidate.steps for candidate in result.trace.clearance_candidates):
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete clearance trace")
    if any(not candidate.steps for candidate in result.trace.creepage_candidates):
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete creepage trace")
    if any(
        not step.symbolic.strip() or not step.substituted.strip() for step in result.trace.steps
    ):
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete formula trace")
    if result.warnings != result.trace.warnings or (
        result.verification_requirements != result.trace.verification_requirements
    ):
        raise ReportBuildError(f"pair {result.pair_id} has mismatched advisories")
    clearance = next(
        candidate
        for candidate in result.trace.clearance_candidates
        if candidate.candidate_id == result.trace.governing_clearance_candidate_id
    )
    creepage = next(
        candidate
        for candidate in result.trace.creepage_candidates
        if candidate.candidate_id == result.trace.governing_creepage_candidate_id
    )
    if clearance.distance_mm != result.trace.pre_altitude_clearance_mm:
        raise ReportBuildError(f"pair {result.pair_id} has a mismatched clearance result")
    if creepage.distance_mm != result.creepage_mm:
        raise ReportBuildError(f"pair {result.pair_id} has a mismatched creepage result")
    if not result.trace.altitude_correction_applied:
        if result.clearance_mm != result.trace.pre_altitude_clearance_mm:
            raise ReportBuildError(f"pair {result.pair_id} has a mismatched clearance result")
    elif not any(
        "altitude" in step.semantic_rule_id
        and step.output.unit == "mm"
        and step.output.value == result.clearance_mm
        for step in result.trace.steps
    ):
        raise ReportBuildError(f"pair {result.pair_id} has an incomplete altitude correction")


def _validate_groups(
    groups: tuple[CalculationGroup, ...],
    result_by_pair: dict[str, PairResult],
    project_pair_ids: tuple[str, ...],
) -> dict[str, str]:
    if len({group.group_id for group in groups}) != len(groups):
        raise ReportBuildError("duplicate calculation group ID")
    grouped_pair_ids = tuple(pair_id for group in groups for pair_id in group.pair_ids)
    if len(grouped_pair_ids) != len(set(grouped_pair_ids)):
        raise ReportBuildError("duplicate pair result in calculation groups")
    missing = set(project_pair_ids) - set(grouped_pair_ids)
    extra = set(grouped_pair_ids) - set(project_pair_ids)
    if missing or extra:
        raise ReportBuildError("calculation groups have missing or extra pair results")
    for group in groups:
        for pair_id in group.pair_ids:
            if calculation_signature(result_by_pair[pair_id]) != group.signature:
                raise ReportBuildError(f"group {group.group_id} result signature mismatch")
    return {pair_id: group.group_id for group in groups for pair_id in group.pair_ids}


def _matrix_row(
    pair: PairCase,
    result: PairResult,
    group_id: str,
    net_names: dict[str, str],
) -> MatrixRow:
    effective = result.effective_inputs
    return MatrixRow(
        pair_id=str(result.pair_id),
        pair_key=result.pair_key,
        result_sha256=calculation_signature(result),
        net_a=net_names[str(pair.net_a)],
        net_b=net_names[str(pair.net_b)],
        stresses=_report_stresses(effective.voltages),
        frequency=_report_effective(effective.frequency_hz),
        impulse=_report_effective(effective.impulse_v),
        insulation_type=_enum_text(effective.insulation_type.value),
        insulation_type_provenance=effective.insulation_type.provenance.value,
        field_condition=_enum_text(effective.field_condition.value),
        field_condition_provenance=effective.field_condition.provenance.value,
        electrode_radius_mm=effective.electrode_radius_mm.value,
        electrode_radius_provenance=effective.electrode_radius_mm.provenance.value,
        construction_type=_enum_text(effective.construction_type.value),
        construction_type_provenance=effective.construction_type.provenance.value,
        cti_or_material_group=effective.cti_or_material_group.value,
        cti_or_material_group_provenance=effective.cti_or_material_group.provenance.value,
        pollution_degree=effective.pollution_degree.value,
        pollution_degree_provenance=effective.pollution_degree.provenance.value,
        altitude_m=effective.altitude_m.value,
        altitude_provenance=effective.altitude_m.provenance.value,
        clearance_mm=result.clearance_mm,
        creepage_mm=result.creepage_mm,
        inner_clearance_mm=result.inner_clearance_mm,
        inner_creepage_mm=result.inner_creepage_mm,
        governing_clearance_path=result.trace.governing_clearance_candidate_id,
        governing_creepage_path=result.trace.governing_creepage_candidate_id,
        group_id=group_id,
    )


def _calculation(result: PairResult) -> PairCalculationReport:
    clearance_source = _candidate_source(
        result.trace.clearance_candidates,
        result.trace.governing_clearance_candidate_id,
    )
    creepage_source = _candidate_source(
        result.trace.creepage_candidates,
        result.trace.governing_creepage_candidate_id,
    )
    governing_sources = {
        "clearance.maximum": clearance_source,
        "part1.creepage.clearance_floor": creepage_source,
        "part1.creepage.clearance_floor.candidate": clearance_source,
    }
    return PairCalculationReport(
        pair_id=str(result.pair_id),
        pair_key=result.pair_key,
        result_sha256=calculation_signature(result),
        effective_inputs=result.effective_inputs.model_copy(deep=True),
        stresses=_report_stresses(result.effective_inputs.voltages),
        clearance_candidates=tuple(
            candidate.model_copy(deep=True) for candidate in result.trace.clearance_candidates
        ),
        creepage_candidates=tuple(
            candidate.model_copy(deep=True) for candidate in result.trace.creepage_candidates
        ),
        omissions=tuple(item.model_copy(deep=True) for item in result.trace.omissions),
        hf_iterations=tuple(item.model_copy(deep=True) for item in result.trace.hf_iterations),
        pre_altitude_clearance_mm=result.trace.pre_altitude_clearance_mm,
        altitude_correction_applied=result.trace.altitude_correction_applied,
        governing_clearance_candidate_id=result.trace.governing_clearance_candidate_id,
        governing_clearance_reason=result.trace.governing_clearance_reason,
        governing_creepage_candidate_id=result.trace.governing_creepage_candidate_id,
        governing_creepage_reason=result.trace.governing_creepage_reason,
        clearance_mm=result.clearance_mm,
        creepage_mm=result.creepage_mm,
        inner_clearance_mm=result.inner_clearance_mm,
        inner_creepage_mm=result.inner_creepage_mm,
        steps=tuple(
            _report_step(step, governing_sources.get(step.semantic_rule_id))
            for step in result.trace.steps
        ),
        warnings=tuple(item.model_copy(deep=True) for item in result.warnings),
        verification_requirements=tuple(
            item.model_copy(deep=True) for item in result.verification_requirements
        ),
    )


def _candidate_source(
    candidates: tuple[DistanceCandidate, ...], candidate_id: str
) -> SourceReference | None:
    candidate = next(item for item in candidates if item.candidate_id == candidate_id)
    for step in reversed(candidate.steps):
        if step.source_reference is not None:
            return step.source_reference
        if step.formula_source_reference is not None:
            return step.formula_source_reference
    return None


def _report_step(step: TraceStep, fallback_source: SourceReference | None) -> ReportStep:
    source = step.source_reference or fallback_source
    try:
        return ReportStep(
            semantic_rule_id=step.semantic_rule_id,
            operation=step.operation,
            symbolic_latex=TrustedFormulaLatex(
                latex=_symbolic_latex(step),
                origin=(
                    "approved_rules"
                    if step.formula_source_reference is not None
                    and step.operation != "linear_interpolate"
                    else "engine"
                ),
            ),
            substituted_latex=TrustedFormulaLatex(
                latex=_substituted_latex(step.substituted),
                origin="engine",
            ),
            inputs=tuple(item.model_copy(deep=True) for item in step.inputs),
            source_reference=(None if source is None else source.model_copy(deep=True)),
            formula_source_reference=(
                None
                if step.formula_source_reference is None
                else step.formula_source_reference.model_copy(deep=True)
            ),
            source_cells=step.source_cells,
            cell_references=tuple(item.model_copy(deep=True) for item in step.cell_references),
            applicability=step.applicability,
            output=step.output.model_copy(deep=True),
            unrounded_value=step.unrounded_value,
            rounded_value=step.rounded_value,
            reason=step.reason,
        )
    except ValidationError as error:
        raise ReportBuildError(
            f"unsafe math LaTeX in trace step {step.semantic_rule_id!r}: {error}"
        ) from error


_ENGINE_IDENTIFIER = re.compile(r"(?<![\\\w])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)")


def _symbolic_latex(step: TraceStep) -> str:
    if step.operation == "linear_interpolate":
        return r"y = y_0 + \frac{(x-x_0)(y_1-y_0)}{x_1-x_0}"
    if step.formula_source_reference is not None:
        return step.symbolic
    return _ENGINE_IDENTIFIER.sub(
        lambda match: rf"\mathrm{{{match.group(1).replace('_', r'\_')}}}",
        step.symbolic,
    )


_QUANTITY = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?) ?([A-Za-z][A-Za-z0-9*/^-]*)")
_ALLOWED_MATH_COMMANDS = frozenset(
    {
        "frac",
        "ge",
        "geq",
        "le",
        "left",
        "max",
        "min",
        "ne",
        "operatorname",
        "mathrm",
        "right",
        "times",
    }
)
_ALLOWED_MATH_ESCAPES = frozenset({",", "_", "%", "&", "{", "}"})


def _validate_math_latex(value: str) -> None:
    if not value or not value.isascii():
        raise ValueError("unsafe math LaTeX: value must be non-empty ASCII")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("unsafe math LaTeX: control characters are forbidden")
    if "^^" in value:
        raise ValueError("unsafe math LaTeX: character-code escapes are forbidden")
    if any(character in "$#~`" for character in value):
        raise ValueError("unsafe math LaTeX: unsafe math token")

    depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\":
            index += 1
            if index == len(value):
                raise ValueError("unsafe math LaTeX: trailing escape")
            if value[index].isalpha():
                end = index + 1
                while end < len(value) and value[end].isalpha():
                    end += 1
                command = value[index:end]
                if command not in _ALLOWED_MATH_COMMANDS:
                    raise ValueError(f"unsafe math LaTeX: command {command!r} is forbidden")
                index = end
                continue
            escape = value[index]
            if escape not in _ALLOWED_MATH_ESCAPES:
                raise ValueError(f"unsafe math LaTeX: escape {escape!r} is forbidden")
        elif character == "%":
            raise ValueError("unsafe math LaTeX: comments are forbidden")
        elif character == "&":
            raise ValueError("unsafe math LaTeX: alignment tokens are forbidden")
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("unsafe math LaTeX: unbalanced braces")
        index += 1
    if depth:
        raise ValueError("unsafe math LaTeX: unbalanced braces")


def _substituted_latex(value: str) -> str:
    value = value.replace("×", r"\times")
    return _QUANTITY.sub(
        lambda match: (
            f"{match.group(1)}"
            rf"\,\mathrm{{{_latex_unit(match.group(2))}}}"
        ),
        value,
    )


def _latex_unit(value: str) -> str:
    return (
        value.replace("\\", "")
        .replace("{", "")
        .replace("}", "")
        .replace("_", r"\_")
        .replace("%", r"\%")
        .replace("&", r"\&")
    )


def _report_effective(value: EffectiveValue[Decimal | None]) -> ReportEffectiveValue:
    return ReportEffectiveValue(value=value.value, provenance=value.provenance.value)


#: Stress display names, in the order :meth:`PairVoltages.stresses` returns them.
_STRESS_NAMES = (
    "long-term RMS",
    "steady-state peak",
    "recurring peak",
    "temporary overvoltage peak",
)


def _report_stresses(voltages: PairVoltages) -> tuple[ReportStress, ...]:
    return tuple(
        ReportStress(
            name=name,
            applicability=voltage.applicability.value,
            value_v=voltage.value,
            justification=voltage.justification,
            provenance="pair_input",
        )
        for name, voltage in zip(_STRESS_NAMES, voltages.stresses(), strict=True)
    )


def _excluded_pair(pair: PairCase, net_names: dict[str, str]) -> ExcludedPair:
    """Describe an excluded pair. Its note is the reason it carries."""
    return ExcludedPair(
        pair_id=str(pair.id),
        pair_key=pair.key,
        net_a=net_names[str(pair.net_a)],
        net_b=net_names[str(pair.net_b)],
        notes=pair.notes,
    )


def _enum_text(value: StrEnum | None) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def _effective_snapshot(effective: EffectiveCase) -> EffectiveInputSnapshot:
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


def _project_hash(project: Project) -> str:
    payload = json.dumps(
        project.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
