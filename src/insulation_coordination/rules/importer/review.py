"""Deterministic reconstruction of reviewed typed content from an imported draft.

The importer deliberately produces an unusable draft (raw grids + manual review
items only).  Approval requires typed tables/formulas/mappings that exactly match
each recipe contract and the raw grids.  This module rebuilds that typed content
from the recipe specs so the maintainer can approve a fresh extraction without
hand-crafting every table and mapping.  Formula literal values that cannot be
derived from the raw grids are set to placeholder constants; a maintainer should
review them via ``record_correction``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    CompatibilityMapping,
    CurveAxis,
    CurvePoint,
    CurveSegment,
    DecisionRule,
    DraftRulePackage,
    FaultTimeVoltageVariant,
    Formula,
    GuidanceRule,
    LinearInterpolate,
    Literal,
    Lookup,
    Parameter,
    ParameterSet,
    PiecewiseCurveRule,
    ProcedureRule,
    RuleKind,
    SourceReference,
    Table,
    Variable,
)
from insulation_coordination.domain.rules import Expression as RuleExpression
from insulation_coordination.rules.archive import _canonical_json
from insulation_coordination.rules.importer.approval import ApprovalError, record_correction
from insulation_coordination.rules.importer.curves import (
    ConservatismReport,
    CurveDigitizationResult,
    PlotCalibration,
    RawCurveTrace,
    RawFigure,
    _log_space_point,
    prove_variant_conservative,
    rebuild_variant_from_calibration,
)
from insulation_coordination.rules.importer.extract import (
    ComponentFormulaCandidate,
    CurveTraceAssociation,
    CurveVariantRejection,
    CurveVariantReview,
    ImportedRuleDraft,
    ImportReviewItem,
    ManualCurveTrace,
    RawGrid,
    RawGridCell,
    SemanticProposal,
    canonical_model_sha256,
    is_recipe_derived,
)
from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardIdentity,
    StandardRecipe,
)
from insulation_coordination.rules.importer.projection import (
    project_formula,
    project_mapping,
    project_table,
)


def draft_review_digest(draft: DraftRulePackage) -> str:
    """Return a stable digest of extracted material for a human-reviewed baseline."""
    payload = draft.model_dump(mode="json")
    manifest = payload["manifest"]
    stable = {
        "source_documents": manifest["source_documents"],
        "tables": payload["tables"],
        "formulas": payload["formulas"],
        "mappings": payload["mappings"],
        "decisions": payload["decisions"],
        "procedures": payload["procedures"],
        "guidance": payload["guidance"],
        "curves": payload["curves"],
        "review_items": payload.get("review_items", []),
        "raw_grids": payload.get("raw_grids", []),
        "raw_clause_fragments": payload.get("raw_clause_fragments", []),
        "extracted_equations": payload.get("extracted_equations", []),
        "semantic_proposals": payload.get("semantic_proposals", []),
    }
    return hashlib.sha256(_canonical_json(stable)).hexdigest()


SemanticRule = (
    Table
    | Formula
    | CompatibilityMapping
    | DecisionRule
    | ProcedureRule
    | GuidanceRule
    | PiecewiseCurveRule
)


def _rule_entries(draft: DraftRulePackage) -> tuple[tuple[RuleKind, SemanticRule], ...]:
    entries: list[tuple[RuleKind, SemanticRule]] = []
    entries.extend(("table", rule) for rule in draft.tables)
    entries.extend(("formula", rule) for rule in draft.formulas)
    entries.extend(("mapping", rule) for rule in draft.mappings)
    entries.extend(("decision", rule) for rule in draft.decisions)
    entries.extend(("procedure", rule) for rule in draft.procedures)
    entries.extend(("guidance", rule) for rule in draft.guidance)
    entries.extend(("curve", rule) for rule in draft.curves)
    return tuple(entries)


def _rule_for(draft: ImportedRuleDraft, proposal: SemanticProposal) -> SemanticRule:
    matches = tuple(
        rule
        for kind, rule in _rule_entries(draft)
        if kind == proposal.rule_kind and rule.id == proposal.semantic_id
    )
    if len(matches) != 1:
        raise ApprovalError(
            f"semantic proposal {proposal.semantic_id} has no unique current rule"
        )
    return matches[0]


def proposal_for(draft: ImportedRuleDraft, semantic_id: str) -> SemanticProposal:
    """Return the unique draft-only semantic proposal for one rule ID."""
    matches = tuple(
        proposal for proposal in draft.semantic_proposals if proposal.semantic_id == semantic_id
    )
    if len(matches) != 1:
        raise ValueError(f"no unique semantic proposal for {semantic_id}")
    return matches[0]


def _aggregate_artifact_pairs(pairs: tuple[tuple[str, str], ...]) -> str:
    if not pairs:
        raise ApprovalError("semantic proposal has no current source artifact")
    ordered = tuple(sorted(pairs))
    if len({artifact_id for artifact_id, _ in ordered}) != len(ordered):
        raise ApprovalError("semantic proposal has duplicate source artifact IDs")
    if len(ordered) == 1:
        return ordered[0][1]
    return hashlib.sha256(_canonical_json(ordered)).hexdigest()


def _review_item_artifact_id(item: ImportReviewItem) -> str:
    return f"{item.semantic_id}:{item.code}"


def _source_semantic_id(proposal: SemanticProposal) -> str:
    from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

    table_decision_sources = {
        ids.DVC_VOLTAGE_LIMITS: (
            ids.DVC_VOLTAGE_LIMITS,
            f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
            f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
            f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
        ),
        ids.DVC_PROTECTION_MATRIX: (
            ids.DVC_PROTECTION_MATRIX,
        ),
        ids.DVC_FAULT_APPLICABILITY: (ids.DVC_FAULT_APPLICABILITY,),
    }
    if proposal.rule_kind == "decision":
        for source_id, decision_ids in table_decision_sources.items():
            if proposal.semantic_id in decision_ids:
                return source_id
    return proposal.semantic_id


def _required_review_items(
    draft: ImportedRuleDraft,
    proposal: SemanticProposal,
) -> tuple[ImportReviewItem, ...]:
    rule = _rule_for(draft, proposal)
    semantic_ids = {proposal.semantic_id, _source_semantic_id(proposal)}
    if proposal.rule_kind == "curve":
        assert isinstance(rule, PiecewiseCurveRule)
        semantic_ids.update(variant.id for variant in rule.variants)
    items = tuple(
        item
        for item in draft.review_items
        if item.semantic_id in semantic_ids
        or (
            proposal.rule_kind == "table"
            and item.semantic_id.startswith(f"raw-{proposal.semantic_id}:")
        )
    )
    if not items:
        raise ApprovalError(
            f"semantic proposal {proposal.semantic_id} has no required review item inventory"
        )
    ordered = tuple(sorted(items, key=_review_item_artifact_id))
    artifact_ids = tuple(_review_item_artifact_id(item) for item in ordered)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ApprovalError("draft has duplicate review item artifact IDs")
    inventory = {item.sha256: item for item in ordered}
    if len(inventory) != len(ordered):
        raise ApprovalError("draft has duplicate review item hashes")
    return ordered


def _recipe_source_artifacts(proposal: SemanticProposal) -> tuple[tuple[str, str], ...]:
    from insulation_coordination.rules.importer.recipes import RECIPES

    artifacts: list[tuple[str, str]] = []
    for recipe in RECIPES:
        if proposal.rule_kind == "table":
            artifacts.extend(
                (f"{recipe.id}:table:{spec.semantic_id}", canonical_model_sha256(spec))
                for spec in recipe.tables
                if spec.semantic_id == proposal.semantic_id
            )
        elif proposal.rule_kind == "formula":
            artifacts.extend(
                (f"{recipe.id}:formula:{spec.semantic_id}", canonical_model_sha256(spec))
                for spec in recipe.formulas
                if spec.semantic_id == proposal.semantic_id
            )
        elif proposal.rule_kind == "mapping":
            artifacts.extend(
                (f"{recipe.id}:mapping:{spec.id}", canonical_model_sha256(spec))
                for spec in recipe.mappings
                if spec.id == proposal.semantic_id
            )
    return tuple(artifacts)


def _current_source_artifact_sha256(
    draft: ImportedRuleDraft,
    proposal: SemanticProposal,
) -> str:
    rule = _rule_for(draft, proposal)
    if proposal.rule_kind == "curve":
        assert isinstance(rule, PiecewiseCurveRule)
        return _aggregate_artifact_pairs(
            tuple(
                (variant.id, variant.reviewed_artifact_sha256)
                for variant in rule.variants
            )
        )

    source_semantic_id = _source_semantic_id(proposal)
    grids = tuple(
        (grid.id, canonical_model_sha256(grid))
        for grid in draft.raw_grids
        if grid.id
        in {
            proposal.semantic_id,
            f"raw-{proposal.semantic_id}",
            source_semantic_id,
            f"raw-{source_semantic_id}",
        }
    )
    if grids:
        return _aggregate_artifact_pairs(grids)
    fragments = tuple(
        (fragment.id, canonical_model_sha256(fragment))
        for fragment in draft.raw_clause_fragments
        if fragment.id
        in {
            proposal.semantic_id,
            f"raw-{proposal.semantic_id}",
            source_semantic_id,
            f"raw-{source_semantic_id}",
        }
    )
    if fragments:
        return _aggregate_artifact_pairs(fragments)
    equations = tuple(
        (equation.id, canonical_model_sha256(equation))
        for equation in draft.extracted_equations
        if equation.id == proposal.semantic_id
    )
    if equations:
        return _aggregate_artifact_pairs(equations)

    review_items = _required_review_items(draft, proposal)
    geometry = tuple(
        (_review_item_artifact_id(item), item.source.geometry.artifact_sha256)
        for item in review_items
        if item.source.geometry is not None
    )
    if geometry:
        return _aggregate_artifact_pairs(geometry)
    recipe_artifacts = _recipe_source_artifacts(proposal)
    if recipe_artifacts:
        return _aggregate_artifact_pairs(recipe_artifacts)
    raise ApprovalError(
        f"semantic proposal {proposal.semantic_id} has no real current source artifact"
    )


def _require_current_proposal(
    draft: ImportedRuleDraft,
    proposal: SemanticProposal,
    *,
    require_resolved_members: bool,
) -> None:
    rule = _rule_for(draft, proposal)
    if proposal.rule_sha256 != canonical_model_sha256(rule):
        raise ApprovalError(f"semantic proposal {proposal.semantic_id} has a stale rule hash")
    review_items = _required_review_items(draft, proposal)
    required_hashes = tuple(item.sha256 for item in review_items)
    if proposal.review_item_sha256s != required_hashes:
        raise ApprovalError(
            f"semantic proposal {proposal.semantic_id} has stale required review item hashes"
        )
    if proposal.source_artifact_sha256 != _current_source_artifact_sha256(draft, proposal):
        raise ApprovalError(f"semantic proposal {proposal.semantic_id} has a stale source hash")
    if require_resolved_members:
        resolved = {item.review_item_sha256 for item in draft.review_resolutions}
        missing = {item.sha256 for item in review_items} - resolved
        if missing:
            raise ApprovalError(
                f"semantic proposal {proposal.semantic_id} has an unresolved review item"
            )


def mark_proposal_reviewed(
    draft: ImportedRuleDraft,
    semantic_id: str,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Review the exact current rule, source artifact, and member review hashes."""
    if not actor.strip() or not notes.strip():
        raise ApprovalError("semantic review actor and notes are required")
    proposal = proposal_for(draft, semantic_id)
    _require_current_proposal(draft, proposal, require_resolved_members=True)
    if proposal.state == "reviewed":
        raise ApprovalError(f"semantic proposal {semantic_id} is already reviewed")
    reviewed = proposal.model_copy(update={"state": "reviewed"})
    recorded_at = datetime.now(UTC)
    manifest = draft.manifest.model_copy(
        update={
            "approval_records": (
                *draft.manifest.approval_records,
                ApprovalRecord(
                    action="correction",
                    actor=actor.strip(),
                    recorded_at=recorded_at,
                    notes=f"semantic:{semantic_id}:reviewed; {notes.strip()}",
                ),
            )
        }
    )
    return draft.model_copy(
        update={
            "manifest": manifest,
            "semantic_proposals": tuple(
                reviewed if item is proposal else item for item in draft.semantic_proposals
            ),
        }
    )


def _unresolved_items(
    draft: ImportedRuleDraft,
    kind: str,
) -> tuple[ImportReviewItem, ...]:
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    return tuple(
        item for item in draft.review_items if item.kind == kind and item.sha256 not in resolved
    )


def unresolved_table_items(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    return _unresolved_items(draft, "table")


def unresolved_equation_items(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    return _unresolved_items(draft, "formula")


def unresolved_mapping_items(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    return _unresolved_items(draft, "mapping")


def unresolved_clause_items(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    return _unresolved_items(draft, "clause")


def accept_clause_fragment(
    draft: ImportedRuleDraft,
    *,
    semantic_id: str,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Resolve one clause review item against its extracted fragment."""

    from insulation_coordination.rules.importer.approval import record_correction

    pending = tuple(
        item for item in unresolved_clause_items(draft) if item.semantic_id == semantic_id
    )
    if not pending:
        raise ValueError(f"clause {semantic_id} has no unresolved review item")
    if not any(
        fragment.id == f"raw-{semantic_id}" for fragment in draft.raw_clause_fragments
    ):
        raise ValueError(f"clause {semantic_id} has no extracted fragment")
    return record_correction(
        draft,
        draft,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=pending,
    )


def recipe_derived_items(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    """Review items the importer resolved itself because no PDF content backs them."""
    return tuple(item for item in draft.review_items if is_recipe_derived(item))


def _table_id_for(recipe: StandardRecipe, spec: FormulaAuditSpec) -> str:
    raw = spec.expression_shape
    if ":" in raw and "(" in raw:
        candidate = raw.split(":", 1)[1].split("(", 1)[0]
        return candidate or recipe.tables[0].semantic_id
    return recipe.tables[0].semantic_id


def _formula_from_spec(
    identity: StandardIdentity,
    spec: FormulaAuditSpec,
    table_id: str,
) -> Formula:
    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=spec.page_number,
        clause=spec.clause,
        table=spec.table,
        figure=spec.figure,
    )
    return Formula(
        id=spec.semantic_id,
        expression=_expression(spec, table_id),
        unit=spec.unit,
        precision=34,
        parameter_sets=(
            ParameterSet(
                id="reviewed",
                parameters=tuple(Parameter(name=name, unit="1") for name in spec.variables),
                source=source,
            ),
        ),
        source=source,
    )


def _expression(spec: FormulaAuditSpec, table_id: str) -> RuleExpression:
    """Build an Expression matching the recipe's canonical shape string."""
    raw = spec.expression_shape
    if raw.startswith("linear_interpolate:"):
        x = Variable(name=spec.variables[0]) if spec.variables else Variable(name="raw_sequence")
        return LinearInterpolate(table_id=table_id, x=x)
    if raw.startswith("lookup:") or raw == "lookup":
        return Lookup(
            table_id=table_id,
            row=Literal(value=Decimal(1)),
            column=Literal(value=Decimal(1)),
        )
    if "compare(divide(" in raw and spec.variables:
        from insulation_coordination.domain.rules import Compare, Divide

        left, right = spec.variables
        return Compare(
            comparison="lt",
            left=Divide(
                numerator=Variable(name=left),
                denominator=Variable(name=right),
            ),
            right=Literal(value=Decimal(1)),
        )
    if raw == "compare(literal,literal)":
        from insulation_coordination.domain.rules import Compare

        return Compare(
            comparison="lt",
            left=Literal(value=Decimal(1)),
            right=Literal(value=Decimal(1)),
        )
    raise ValueError(f"cannot auto-build formula shape for {spec.semantic_id}: {raw}")


def _mapping_from_spec(
    identity: StandardIdentity,
    spec: MappingAuditSpec,
) -> CompatibilityMapping:
    return CompatibilityMapping(
        id=spec.id,
        source_rule_id=spec.semantic_route,
        target_rule_id=spec.target_rule_id,
        approved=False,
        source=SourceReference(
            document_id=identity.recipe_id,
            standard=identity.standard,
            edition=identity.edition,
            page=spec.page_number,
            clause=spec.clause,
            table=spec.table,
            figure=spec.figure,
        ),
    )


def unresolved_raw_review_items(
    draft: ImportedRuleDraft,
) -> tuple[ImportReviewItem, ...]:
    """Raw-cell review items without an explicit maintainer resolution."""
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    return tuple(
        item
        for item in draft.review_items
        if item.kind == "raw_cell" and item.sha256 not in resolved
    )


def flagged_coordinates(items: Iterable[ImportReviewItem]) -> set[tuple[int, int]]:
    """Grid coordinates carried by raw-cell review items."""
    coordinates: set[tuple[int, int]] = set()
    for item in items:
        parts = item.semantic_id.rsplit(
            ":",
            3 if item.code in {"AMBIGUOUS_COMPOUND_CELL", "AMBIGUOUS_COMPONENT_FORMULA"} else 2,
        )
        row, column = parts[-3:-1] if len(parts) == 4 else parts[-2:]
        coordinates.add((int(row), int(column)))
    return coordinates


def correctable_coordinates(
    grid: RawGrid,
    flagged: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Data cells a maintainer may retype.

    Parser confidence is not correctness: a cell read as a clean number can
    still be the wrong number, so every numeric data cell is correctable, not
    only the ones the parser flagged.  Cells the parser could not turn into a
    number at all stay correctable through their flag, and a value can never be
    removed, so the count of numeric cells backing a typed table cannot change.
    """
    return {
        (cell.row, cell.column)
        for cell in grid.cells
        if cell.role == "data"
        and (
            (cell.row, cell.column) in flagged
            or cell.value is not None
            or any(component.value is not None for component in cell.components)
        )
    }


def _corrected_cells(
    grid: RawGrid,
    corrections: Mapping[tuple[int, int] | tuple[int, int, int], Decimal],
    flagged: set[tuple[int, int]],
) -> tuple[RawGridCell, ...]:
    """Apply retyped values and clear the parser's flag on every flagged cell."""
    correctable = correctable_coordinates(grid, flagged)
    scalar_corrections = {
        coordinate: value for coordinate, value in corrections.items() if len(coordinate) == 2
    }
    component_corrections = {
        coordinate: value for coordinate, value in corrections.items() if len(coordinate) == 3
    }
    unexpected: set[tuple[int, int] | tuple[int, int, int]] = set()
    unexpected.update(set(scalar_corrections) - correctable)
    unexpected.update(
        coordinate
        for coordinate in component_corrections
        if coordinate[:2] not in correctable
    )
    if unexpected:
        raise ValueError(f"raw grid cell is not correctable: {sorted(unexpected)!r}")
    cells: list[RawGridCell] = []
    for cell in grid.cells:
        coordinate = (cell.row, cell.column)
        selected_components = {
            key[2]: value
            for key, value in component_corrections.items()
            if key[:2] == coordinate
        }
        if coordinate not in flagged and coordinate not in scalar_corrections and not selected_components:
            cells.append(cell)
            continue
        if selected_components:
            known = {component.source_index for component in cell.components}
            if set(selected_components) - known:
                raise ValueError(f"raw grid component is not correctable: {coordinate}")
            if any(not value.is_finite() for value in selected_components.values()):
                raise ValueError(f"raw grid correction must be a finite decimal: {coordinate}")
            components = tuple(
                component.model_copy(update={"value": selected_components[component.source_index]})
                if component.source_index in selected_components
                else component
                for component in cell.components
            )
            cells.append(cell.model_copy(update={"components": components}))
            continue
        if cell.components:
            cells.append(cell)
            continue
        value = scalar_corrections.get(coordinate, cell.value)
        if value is None or not value.is_finite():
            raise ValueError(f"raw grid correction must be a finite decimal: {coordinate}")
        cells.append(
            cell.model_copy(
                update={
                    "value": value,
                    "qualifier": None,
                    "suffix": None,
                    "parse_status": "numeric",
                }
            )
        )
    return tuple(cells)


def _raw_cell(draft: ImportedRuleDraft, grid_id: str, row: int, column: int) -> RawGridCell:
    grid = next((item for item in draft.raw_grids if item.id == grid_id), None)
    if grid is None:
        raise ValueError(f"unknown raw grid: {grid_id}")
    cell = next(
        (item for item in grid.cells if (item.row, item.column) == (row, column)),
        None,
    )
    if cell is None:
        raise ValueError("unknown raw grid cell")
    return cell


def _replace_raw_cell(
    draft: ImportedRuleDraft,
    grid_id: str,
    replacement: RawGridCell,
) -> ImportedRuleDraft:
    return draft.model_copy(
        update={
            "raw_grids": tuple(
                grid.model_copy(
                    update={
                        "cells": tuple(
                            replacement
                            if (cell.row, cell.column)
                            == (replacement.row, replacement.column)
                            else cell
                            for cell in grid.cells
                        )
                    }
                )
                if grid.id == grid_id
                else grid
                for grid in draft.raw_grids
            )
        }
    )


def correct_raw_component(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    row: int,
    column: int,
    component_id: str,
    value: Decimal,
    source_index: int | None = None,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Retype one labelled compound component without changing its siblings."""
    if not value.is_finite():
        raise ValueError("raw component correction must be a finite decimal")
    cell = _raw_cell(draft, grid_id, row, column)
    if component_id not in cell.compound_component_ids:
        raise ValueError("component is not declared for this compound cell")
    existing = tuple(
        part
        for part in cell.components
        if part.component_id == component_id
        and (source_index is None or part.source_index == source_index)
    )
    if len(existing) != 1:
        raise ValueError("component value correction needs one exact source occurrence")
    replacement = existing[0].model_copy(update={"value": value})
    components = tuple(
        replacement if part.source_index == replacement.source_index else part
        for part in cell.components
    )
    changed_cell = cell.model_copy(update={"components": components})
    changed = _replace_raw_cell(draft, grid_id, changed_cell)
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
    )


def _compound_complete(cell: RawGridCell) -> bool:
    return (
        len(cell.components) == len(cell.compound_component_ids)
        and {part.component_id for part in cell.components}
        == set(cell.compound_component_ids)
        and all(part.value is not None for part in cell.components)
    )


def _associated_cell(
    cell: RawGridCell,
    *,
    source_index: int,
    component_id: str,
    formula_id: str | None = None,
) -> RawGridCell:
    if component_id not in cell.compound_component_ids:
        raise ValueError("component is not declared for this compound cell")
    matches = tuple(
        component
        for component in cell.components
        if component.source_index == source_index
    )
    if len(matches) != 1:
        raise ValueError("association correction needs one exact source occurrence")
    replacement = matches[0].model_copy(update={"component_id": component_id})
    components = tuple(
        replacement if part.source_index == source_index else part
        for part in cell.components
    )
    allowed = {
        allowed_formula_id
        for route_component_id, allowed_formula_id in cell.allowed_component_formula_ids
        if route_component_id == component_id
    }
    if allowed and formula_id is None:
        raise ValueError("association correction requires one exact route-local formula")
    if formula_id is not None and formula_id not in allowed:
        raise ValueError("formula is not declared for this exact component route")
    candidates = tuple(
        candidate
        for candidate in cell.formula_candidates
        if candidate.source_index != source_index
    )
    if formula_id is not None:
        candidates = (
            *candidates,
            ComponentFormulaCandidate(
                source_index=source_index,
                component_id=component_id,
                formula_id=formula_id,
                source=replacement.source,
            ),
        )
    changed = cell.model_copy(
        update={"components": components, "formula_candidates": candidates}
    )
    return changed.model_copy(
        update={
            "parse_status": "compound" if _compound_complete(changed) else "ambiguous_compound"
        }
    )


def correct_component_association(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    row: int,
    column: int,
    source_index: int,
    component_id: str,
    formula_id: str | None = None,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Associate one source occurrence and its required route-local formula."""
    cell = _raw_cell(draft, grid_id, row, column)
    changed_cell = _associated_cell(
        cell,
        source_index=source_index,
        component_id=component_id,
        formula_id=formula_id,
    )
    changed = _replace_raw_cell(draft, grid_id, changed_cell)
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    prefix = f"{grid_id}:{row}:{column}:"
    coordinate = f"{prefix}{source_index}"
    resolve = tuple(
        item
        for item in draft.review_items
        if (
            (
                item.code == "AMBIGUOUS_COMPOUND_CELL"
                and item.semantic_id.startswith(prefix)
            )
            or (
                item.code == "AMBIGUOUS_COMPONENT_FORMULA"
                and formula_id is not None
                and item.semantic_id == coordinate
            )
        )
        and item.sha256 not in resolved
        and _compound_complete(changed_cell)
    )
    if not resolve:
        raise ValueError("component association has no resolved ambiguity")
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=resolve,
    )


def _formula_selected_cell(
    cell: RawGridCell,
    *,
    component_id: str,
    formula_id: str,
    source_index: int | None = None,
) -> tuple[RawGridCell, int]:
    components = tuple(
        component
        for component in cell.components
        if component.component_id == component_id
        and (source_index is None or component.source_index == source_index)
    )
    if len(components) != 1:
        raise ValueError("formula correction needs one exact source occurrence")
    source_index = components[0].source_index
    allowed = {
        allowed_formula_id
        for route_component_id, allowed_formula_id in cell.allowed_component_formula_ids
        if route_component_id == component_id
    }
    if formula_id not in allowed:
        raise ValueError("formula is not declared for this exact component route")
    selected = ComponentFormulaCandidate(
        source_index=source_index,
        component_id=component_id,
        formula_id=formula_id,
        source=components[0].source,
    )
    return (
        cell.model_copy(
            update={
                "formula_candidates": (
                    *tuple(
                        candidate
                        for candidate in cell.formula_candidates
                        if candidate.source_index != source_index
                    ),
                    selected,
                )
            }
        ),
        source_index,
    )


def select_component_formula(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    row: int,
    column: int,
    component_id: str,
    formula_id: str,
    source_index: int | None = None,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Choose exactly one route-local formula for one source occurrence."""
    cell = _raw_cell(draft, grid_id, row, column)
    changed_cell, source_index = _formula_selected_cell(
        cell,
        component_id=component_id,
        formula_id=formula_id,
        source_index=source_index,
    )
    changed = _replace_raw_cell(draft, grid_id, changed_cell)
    coordinate = f"{grid_id}:{row}:{column}:{source_index}"
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    resolve = tuple(
        item
        for item in draft.review_items
        if item.code == "AMBIGUOUS_COMPONENT_FORMULA"
        and item.semantic_id == coordinate
        and item.sha256 not in resolved
    )
    if not resolve:
        raise ValueError("component formula has no unresolved ambiguity")
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=resolve,
    )


def _corrected_compound_cells(
    cells: tuple[RawGridCell, ...],
    associations: Mapping[tuple[int, int, int], str],
    formulas: Mapping[tuple[int, int, int], str],
) -> tuple[RawGridCell, ...]:
    by_coordinate = {(cell.row, cell.column): cell for cell in cells}
    for (row, column, source_index), component_id in sorted(associations.items()):
        coordinate = (row, column)
        cell = by_coordinate.get(coordinate)
        if cell is None:
            raise ValueError(f"unknown compound cell: {coordinate}")
        key = (row, column, source_index)
        by_coordinate[coordinate] = _associated_cell(
            cell,
            source_index=source_index,
            component_id=component_id,
            formula_id=formulas.get(key),
        )
    for (row, column, source_index), formula_id in sorted(formulas.items()):
        coordinate = (row, column)
        cell = by_coordinate.get(coordinate)
        if cell is None:
            raise ValueError(f"unknown compound cell: {coordinate}")
        component = next(
            (
                part
                for part in cell.components
                if part.source_index == source_index
            ),
            None,
        )
        if component is None or component.component_id is None:
            raise ValueError("formula correction needs a reviewed component association")
        by_coordinate[coordinate], _ = _formula_selected_cell(
            cell,
            source_index=source_index,
            component_id=component.component_id,
            formula_id=formula_id,
        )
    return tuple(by_coordinate[(cell.row, cell.column)] for cell in cells)


def accept_raw_table(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    corrections: Mapping[tuple[int, int] | tuple[int, int, int], Decimal],
    actor: str,
    notes: str,
    component_associations: Mapping[tuple[int, int, int], str] | None = None,
    formula_selections: Mapping[tuple[int, int, int], str] | None = None,
) -> ImportedRuleDraft:
    """Accept one logical table, including any explicitly reviewed data cells."""
    grid = next((item for item in draft.raw_grids if item.id == grid_id), None)
    if grid is None:
        raise ValueError(f"unknown raw grid: {grid_id}")
    semantic_id = grid_id.removeprefix("raw-")
    table_items = tuple(
        item for item in unresolved_table_items(draft) if item.semantic_id == semantic_id
    )
    raw_items = tuple(
        item
        for item in unresolved_raw_review_items(draft)
        if item.semantic_id.startswith(f"{grid_id}:")
    )
    if not table_items and not raw_items:
        raise ValueError(f"raw table {grid_id} is already accepted")
    coordinates = flagged_coordinates(raw_items)
    corrected_cells = _corrected_cells(grid, corrections, coordinates)
    changed_grid = grid.model_copy(
        update={
            "cells": _corrected_compound_cells(
                corrected_cells,
                component_associations or {},
                formula_selections or {},
            )
        }
    )
    changed = draft.model_copy(
        update={
            "raw_grids": tuple(
                changed_grid if item.id == grid_id else item for item in draft.raw_grids
            )
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=(*table_items, *raw_items),
    )


def accept_equation_mapping(
    draft: ImportedRuleDraft,
    *,
    equation_ids: tuple[str, ...],
    mapping_ids: tuple[str, ...],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Accept selected canonical formula/equation and mapping source artifacts."""
    equations = {item.semantic_id: item for item in unresolved_equation_items(draft)}
    mappings = {item.semantic_id: item for item in unresolved_mapping_items(draft)}
    if not equation_ids and not mapping_ids:
        raise ValueError("select equations or mappings to accept")
    if set(equation_ids) - set(equations) or set(mapping_ids) - set(mappings):
        raise ValueError("equation or mapping is unknown or already accepted")
    extracted = {equation.id: equation for equation in draft.extracted_equations}
    if any(
        equation_id in extracted and extracted[equation_id].parse_status != "parsed"
        for equation_id in equation_ids
    ):
        raise ValueError("an equation still requires parsed-field review")
    resolve = tuple(equations[item] for item in equation_ids) + tuple(
        mappings[item] for item in mapping_ids
    )
    return record_correction(
        draft,
        draft,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=resolve,
    )


def accept_raw_grid(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    corrections: Mapping[tuple[int, int] | tuple[int, int, int], Decimal],
    actor: str,
    notes: str,
    component_associations: Mapping[tuple[int, int, int], str] | None = None,
    formula_selections: Mapping[tuple[int, int, int], str] | None = None,
) -> ImportedRuleDraft:
    """Correct or explicitly accept all pending review cells in one raw grid."""
    grid = next((item for item in draft.raw_grids if item.id == grid_id), None)
    if grid is None:
        raise ValueError(f"unknown raw grid: {grid_id}")
    pending = tuple(
        item
        for item in unresolved_raw_review_items(draft)
        if item.semantic_id.startswith(f"{grid_id}:")
    )
    if not pending:
        raise ValueError(f"raw grid {grid_id} has no unresolved raw cells")
    corrected_cells = _corrected_cells(
        grid,
        corrections,
        flagged_coordinates(pending),
    )
    changed_grid = grid.model_copy(
        update={
            "cells": _corrected_compound_cells(
                corrected_cells,
                component_associations or {},
                formula_selections or {},
            )
        }
    )
    changed = draft.model_copy(
        update={
            "raw_grids": tuple(
                changed_grid if item.id == grid_id else item for item in draft.raw_grids
            )
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=pending,
    )


def build_reviewed_draft(
    draft: ImportedRuleDraft,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Project typed content only after every source artifact is accepted."""
    from insulation_coordination.rules.importer.recipes import RECIPES

    if unresolved_table_items(draft) or unresolved_raw_review_items(draft):
        raise ValueError("Review extracted tables first")
    if unresolved_equation_items(draft) or unresolved_mapping_items(draft):
        raise ValueError("Review equations and mappings first")
    if unresolved_clause_items(draft):
        raise ValueError("Review extracted clauses first")

    identities = {i.recipe_id: i for i in draft.source_identities}
    grids = {g.id: g for g in draft.raw_grids}
    fragments = {fragment.id: fragment for fragment in draft.raw_clause_fragments}
    equations = {equation.id: equation for equation in draft.extracted_equations}

    tables: dict[str, Table] = {}
    formulas: dict[str, Formula] = {}
    mappings: dict[str, CompatibilityMapping] = {}
    decisions: dict[str, DecisionRule] = {rule.id: rule for rule in draft.decisions}
    guidance: dict[str, GuidanceRule] = {rule.id: rule for rule in draft.guidance}

    def collect(projected: tuple[object, ...]) -> None:
        """Route each projected rule to the draft field its type belongs in.

        A projection may return guidance alongside decisions -- a source NOTE becomes
        guidance, never an executable branch -- and ``model_copy`` does not validate, so a
        guidance rule appended to ``decisions`` would sit there undetected.
        """
        for rule in projected:
            if isinstance(rule, DecisionRule):
                decisions[rule.id] = rule
            elif isinstance(rule, GuidanceRule):
                guidance[rule.id] = rule
            else:
                raise TypeError(
                    f"projection produced an unsupported rule type: {type(rule).__name__}"
                )

    for recipe in RECIPES:
        identity = identities[recipe.id]
        for table_spec in recipe.tables:
            grid = grids[f"raw-{table_spec.semantic_id}"]
            grid_projector = recipe.grid_projectors.get(table_spec.semantic_id)
            if grid_projector is None:
                tables[table_spec.semantic_id] = project_table(identity, table_spec, grid)
                continue
            projected, _proposals = grid_projector(grid, identity)
            collect(projected)
        for formula_spec in recipe.formulas:
            formulas[formula_spec.semantic_id] = project_formula(identity, formula_spec, equations)
        for mapping_spec in recipe.mappings:
            mappings[mapping_spec.id] = project_mapping(identity, mapping_spec)
        for clause_spec in recipe.clauses:
            fragment = fragments.get(f"raw-{clause_spec.semantic_id}")
            if fragment is None:
                # A draft extracted before this clause recipe existed has no
                # fragment; approval gating reports the missing required content.
                continue
            projected, _proposals = recipe.clause_projectors[clause_spec.semantic_id](
                fragment, identity
            )
            collect(projected)

    changed = draft.model_copy(
        update={
            "tables": tuple(tables.values()),
            "formulas": tuple(formulas.values()),
            "mappings": tuple(mappings.values()),
            "decisions": tuple(decisions.values()),
            "guidance": tuple(guidance.values()),
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=(),
    )


class RequiredContentStatus:
    """One required recipe item and whether typed content is present."""

    def __init__(
        self,
        *,
        standard: str,
        kind: str,
        semantic_id: str,
        source_table: str | None,
        page_number: int,
        clause: str,
        present: bool,
    ) -> None:
        self.standard = standard
        self.kind = kind
        self.semantic_id = semantic_id
        self.source_table = source_table
        self.page_number = page_number
        self.clause = clause
        self.present = present


def _matches(source: SourceReference, expected: SourceReference) -> bool:
    return all(
        getattr(source, field) == getattr(expected, field)
        for field in ("document_id", "standard", "edition", "page", "clause", "table", "figure")
    )


def required_content_report(draft: ImportedRuleDraft) -> tuple[RequiredContentStatus, ...]:
    """Required tables/formulas/mappings and whether typed content is present."""
    from insulation_coordination.rules.importer.recipes import RECIPES

    table_ids = {table.id: table for table in draft.tables}
    decision_ids = {decision.id for decision in draft.decisions}
    formula_ids = {formula.id: formula for formula in draft.formulas}
    mapping_ids = {mapping.id: mapping for mapping in draft.mappings}
    fragment_ids = {fragment.id for fragment in draft.raw_clause_fragments}

    statuses: list[RequiredContentStatus] = []
    for recipe in RECIPES:
        for table_spec in recipe.tables:
            expected = SourceReference(
                document_id=recipe.id,
                standard=recipe.standard,
                edition=recipe.edition,
                page=table_spec.page_number,
                clause=table_spec.clause,
                table=table_spec.source_table,
            )
            decision_routes = set(table_spec.decision_route_ids)
            table = table_ids.get(table_spec.semantic_id)
            present = (
                decision_routes <= decision_ids
                if decision_routes
                else table is not None and _matches(table.source, expected)
            )
            statuses.append(
                RequiredContentStatus(
                    standard=recipe.standard,
                    kind="table",
                    semantic_id=table_spec.semantic_id,
                    source_table=table_spec.source_table,
                    page_number=table_spec.page_number,
                    clause=table_spec.clause,
                    present=present,
                )
            )
        for formula_spec in recipe.formulas:
            expected = SourceReference(
                document_id=recipe.id,
                standard=recipe.standard,
                edition=recipe.edition,
                page=formula_spec.page_number,
                clause=formula_spec.clause,
                table=formula_spec.table,
                figure=formula_spec.figure,
            )
            formula = formula_ids.get(formula_spec.semantic_id)
            present = formula is not None and _matches(formula.source, expected)
            statuses.append(
                RequiredContentStatus(
                    standard=recipe.standard,
                    kind="formula",
                    semantic_id=formula_spec.semantic_id,
                    source_table=formula_spec.table,
                    page_number=formula_spec.page_number,
                    clause=formula_spec.clause,
                    present=present,
                )
            )
        for mapping_spec in recipe.mappings:
            expected = SourceReference(
                document_id=recipe.id,
                standard=recipe.standard,
                edition=recipe.edition,
                page=mapping_spec.page_number,
                clause=mapping_spec.clause,
                table=mapping_spec.table,
                figure=mapping_spec.figure,
            )
            mapping = mapping_ids.get(mapping_spec.id)
            present = mapping is not None and _matches(mapping.source, expected)
            statuses.append(
                RequiredContentStatus(
                    standard=recipe.standard,
                    kind="mapping",
                    semantic_id=mapping_spec.id,
                    source_table=mapping_spec.table,
                    page_number=mapping_spec.page_number,
                    clause=mapping_spec.clause,
                    present=present,
                )
            )
        for clause_spec in recipe.clauses:
            statuses.append(
                RequiredContentStatus(
                    standard=recipe.standard,
                    kind="clause",
                    semantic_id=clause_spec.semantic_id,
                    source_table=None,
                    page_number=clause_spec.page_number,
                    clause=clause_spec.clause,
                    present=f"raw-{clause_spec.semantic_id}" in fragment_ids,
                )
            )
    return tuple(statuses)


def missing_required_content(draft: ImportedRuleDraft) -> tuple[RequiredContentStatus, ...]:
    """Required content that is not yet present as typed rule content."""
    return tuple(item for item in required_content_report(draft) if not item.present)


def placeholder_formula_ids() -> set[str]:
    """Formula ids whose shape has a standalone constant the human must confirm."""
    from insulation_coordination.rules.importer.recipes import RECIPES

    return {
        spec.semantic_id
        for recipe in RECIPES
        for spec in recipe.formulas
        if not spec.expression_shape.startswith("linear_interpolate")
        and "literal" in spec.expression_shape
    }


def _fill_expression_literals(
    expr: Any,
    values: list[Decimal],
) -> RuleExpression:
    """Return a clone of ``expr`` with every Literal node replaced in order."""
    from insulation_coordination.domain.rules import (
        Add,
        Compare,
        Divide,
        LinearInterpolate,
        Lookup,
        Maximum,
        Minimum,
        Multiply,
        Power,
        Round,
        Select,
        TableSelect,
    )

    assert isinstance(expr, dict), "expression node must be a dict dump"
    op = expr["op"]
    if op == "literal":
        return Literal(value=values.pop(0))
    if op == "variable":
        return Variable(name=expr["name"])
    if op == "add":
        return Add(operands=tuple(_fill_expression_literals(c, values) for c in expr["operands"]))
    if op == "multiply":
        return Multiply(
            operands=tuple(_fill_expression_literals(c, values) for c in expr["operands"])
        )
    if op == "minimum":
        return Minimum(
            operands=tuple(_fill_expression_literals(c, values) for c in expr["operands"])
        )
    if op == "maximum":
        return Maximum(
            operands=tuple(_fill_expression_literals(c, values) for c in expr["operands"])
        )
    if op == "divide":
        return Divide(
            numerator=_fill_expression_literals(expr["numerator"], values),
            denominator=_fill_expression_literals(expr["denominator"], values),
        )
    if op == "compare":
        return Compare(
            comparison=expr["comparison"],
            left=_fill_expression_literals(expr["left"], values),
            right=_fill_expression_literals(expr["right"], values),
        )
    if op == "select":
        return Select(
            condition=_fill_expression_literals(expr["condition"], values),
            if_true=_fill_expression_literals(expr["if_true"], values),
            if_false=_fill_expression_literals(expr["if_false"], values),
        )
    if op == "round":
        return Round(
            places=expr["places"],
            mode=expr["mode"],
            value=_fill_expression_literals(expr["value"], values),
        )
    if op == "lookup":
        return Lookup(
            table_id=expr["table_id"],
            row=_fill_expression_literals(expr["row"], values),
            column=_fill_expression_literals(expr["column"], values),
        )
    if op == "table_select":
        return TableSelect(
            table_id=expr["table_id"],
            row=_fill_expression_literals(expr["row"], values),
            column=_fill_expression_literals(expr["column"], values),
            row_mode=expr["row_mode"],
            column_mode=expr["column_mode"],
        )
    if op == "power":
        # The exponent is a pair of plain integers, not Literal nodes, so — like
        # Round's places — only the base is traversed for literals to rebuild.
        return Power(
            base=_fill_expression_literals(expr["base"], values),
            numerator=expr["numerator"],
            denominator=expr["denominator"],
        )
    if op == "linear_interpolate":
        column = expr.get("column")
        return LinearInterpolate(
            table_id=expr["table_id"],
            x=_fill_expression_literals(expr["x"], values),
            column=_fill_expression_literals(column, values) if column is not None else None,
        )
    raise ValueError(f"cannot rebuild literal in expression op {op}")


def placeholder_formula_literals(
    draft: ImportedRuleDraft,
) -> tuple[tuple[str, tuple[Decimal, ...]], ...]:
    """(formula_id, current placeholder literal values) for each placeholder formula."""
    report: list[tuple[str, tuple[Decimal, ...]]] = []
    formulas = {f.id: f for f in draft.formulas}
    for formula_id in sorted(placeholder_formula_ids()):
        formula = formulas.get(formula_id)
        if formula is None:
            continue
        values: list[Decimal] = []
        _collect_literals(formula.expression, values)
        report.append((formula_id, tuple(values)))
    return tuple(report)


def _collect_literals(expr: Any, out: list[Decimal]) -> None:
    if hasattr(expr, "model_dump"):
        _collect_literals(expr.model_dump(mode="python"), out)
        return
    if isinstance(expr, dict):
        if expr["op"] == "literal":
            out.append(expr["value"])
        for value in expr.values():
            _collect_literals(value, out)
    elif isinstance(expr, (tuple, list)):
        for item in expr:
            _collect_literals(item, out)


def confirm_placeholder_formula(
    draft: ImportedRuleDraft,
    *,
    formula_id: str,
    values: tuple[Decimal, ...],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Replace placeholder literal values in one formula and resolve its review item."""
    if formula_id not in placeholder_formula_ids():
        raise ValueError(f"{formula_id} is not a placeholder formula that needs confirmation")
    formulas = {f.id: f for f in draft.formulas}
    formula = formulas.get(formula_id)
    if formula is None:
        raise ValueError(f"formula {formula_id} is missing from the reviewed draft")
    current = placeholder_formula_values(formula.expression)
    if len(values) != len(current):
        raise ValueError(
            f"expected {len(current)} literal value(s) for {formula_id}, got {len(values)}"
        )
    new_expression = _fill_expression_literals(
        formula.expression.model_dump(mode="python"), list(values)
    )
    new_formula = formula.model_copy(update={"expression": new_expression})
    changed = draft.model_copy(
        update={"formulas": tuple(new_formula if f.id == formula_id else f for f in draft.formulas)}
    )
    item = next(
        (i for i in draft.review_items if i.kind == "formula" and i.semantic_id == formula_id),
        None,
    )
    if item is None:
        raise ValueError(f"no review item for formula {formula_id}")
    return record_correction(
        draft,
        changed,
        actor=actor.strip(),
        notes=notes.strip(),
        resolve=(item,),
    )


def placeholder_formula_values(expression: Any) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    _collect_literals(expression, values)
    return tuple(values)


def _curve_rule(draft: ImportedRuleDraft, rule_id: str) -> PiecewiseCurveRule:
    rule = next((rule for rule in draft.curves if rule.id == rule_id), None)
    if rule is None:
        raise ValueError(f"unknown curve rule: {rule_id}")
    return rule


def _replace_curve(
    draft: ImportedRuleDraft,
    rule_id: str,
    changed_rule: PiecewiseCurveRule,
    *,
    actor: str,
    notes: str,
    curve_digitizations: tuple[CurveDigitizationResult, ...] | None = None,
    original_draft: ImportedRuleDraft | None = None,
) -> ImportedRuleDraft:
    from insulation_coordination.rules.importer.approval import record_correction

    original_rule = next((rule for rule in draft.curves if rule.id == rule_id), None)
    before_variants = (
        {variant.id: variant for variant in original_rule.variants}
        if original_rule is not None
        else {}
    )
    after_variants = {variant.id: variant for variant in changed_rule.variants}
    changed_variant_ids = {
        variant_id
        for variant_id in set(before_variants) | set(after_variants)
        if before_variants.get(variant_id) != after_variants.get(variant_id)
    }

    changed = draft.model_copy(
        update={
            "curves": tuple(
                changed_rule if rule.id == rule_id else rule for rule in draft.curves
            ),
            "curve_variant_reviews": tuple(
                review
                for review in draft.curve_variant_reviews
                if review.variant_id not in changed_variant_ids
            ),
            "curve_variant_rejections": tuple(
                rejection
                for rejection in draft.curve_variant_rejections
                if rejection.variant_id not in changed_variant_ids
            ),
            "curve_digitizations": (
                curve_digitizations
                if curve_digitizations is not None
                else draft.curve_digitizations
            ),
        }
    )
    return record_correction(original_draft or draft, changed, actor=actor, notes=notes)


def _variant(rule: PiecewiseCurveRule, variant_id: str) -> FaultTimeVoltageVariant:
    variant = next((v for v in rule.variants if v.id == variant_id), None)
    if variant is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    return variant


def _variant_evidence(
    draft: ImportedRuleDraft,
    variant: FaultTimeVoltageVariant,
) -> tuple[RawFigure, CurveDigitizationResult, RawCurveTrace]:
    figures = tuple(
        figure
        for figure in draft.raw_figures
        if _source_matches(figure.source, variant.source)
    )
    if len(figures) != 1:
        raise ApprovalError("curve variant must have exactly one matching source figure")
    figure = figures[0]
    digitizations = tuple(
        item
        for item in draft.curve_digitizations
        if item.proposed_rule is not None
        and any(member.id == variant.id for member in item.proposed_rule.variants)
    )
    if len(digitizations) != 1 or digitizations[0].calibration is None:
        raise ApprovalError("curve variant must have exactly one calibrated digitization")
    _require_exact_trace_inventory(draft, figure, digitizations[0])
    associations = tuple(
        item for item in draft.curve_trace_associations if item.variant_id == variant.id
    )
    manual_traces = tuple(
        item.trace
        for item in draft.manual_curve_traces
        if item.figure_artifact_sha256 == figure.artifact_sha256
    )
    available_traces = (*figure.traces, *manual_traces)
    if associations:
        if len(associations) != 1 or associations[0].figure_artifact_sha256 != figure.artifact_sha256:
            raise ApprovalError("curve variant has stale or ambiguous trace association")
        traces = tuple(
            trace for trace in available_traces if trace.id == associations[0].trace_id
        )
    else:
        traces = available_traces
    if len(traces) != 1:
        raise ApprovalError("curve variant must have exactly one associated source trace")
    return figure, digitizations[0], traces[0]


def _source_matches(actual: SourceReference, expected: SourceReference) -> bool:
    return all(
        getattr(actual, field) == getattr(expected, field)
        for field in ("document_id", "standard", "edition", "page", "figure")
    )


def _require_exact_trace_inventory(
    draft: ImportedRuleDraft,
    figure: RawFigure,
    digitization: CurveDigitizationResult,
) -> None:
    """Require one distinct plausible source trace for every figure variant."""

    proposed = digitization.proposed_rule
    if proposed is None:
        raise ApprovalError("curve figure lacks a proposed trace inventory")
    variants = tuple(
        variant
        for variant in proposed.variants
        if _source_matches(variant.source, figure.source)
    )
    manual_traces = tuple(
        item.trace
        for item in draft.manual_curve_traces
        if item.figure_artifact_sha256 == figure.artifact_sha256
    )
    traces = (*figure.traces, *manual_traces)
    trace_ids = tuple(trace.id for trace in traces)
    if not variants or len(trace_ids) < len(variants) or len(set(trace_ids)) != len(trace_ids):
        raise ApprovalError(
            "curve figure trace inventory must exactly match its variant inventory"
        )
    variant_ids = {variant.id for variant in variants}
    associations = tuple(
        item
        for item in draft.curve_trace_associations
        if item.variant_id in variant_ids
    )
    if len(variants) == 1 and not associations:
        if len(trace_ids) == 1:
            return
        raise ApprovalError(
            "curve figure with extra traces requires an audited active association"
        )
    if (
        len(associations) != len(variants)
        or {item.variant_id for item in associations} != variant_ids
        or any(
            item.figure_artifact_sha256 != figure.artifact_sha256
            for item in associations
        )
        or len({item.trace_id for item in associations}) != len(associations)
        or not {item.trace_id for item in associations} <= set(trace_ids)
    ):
        raise ApprovalError(
            "curve figure trace inventory must associate every variant one-to-one"
        )


def _reviewed_variant(
    variant: FaultTimeVoltageVariant,
    *,
    figure: RawFigure,
    trace: RawCurveTrace,
    calibration: PlotCalibration,
) -> FaultTimeVoltageVariant:
    payload = {
        "figure_artifact_sha256": figure.artifact_sha256,
        "trace_id": trace.id,
        "calibration": calibration.model_dump(mode="json"),
        "variant": variant.model_copy(
            update={"reviewed_artifact_sha256": figure.artifact_sha256}
        ).model_dump(mode="json"),
    }
    artifact_sha256 = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return variant.model_copy(update={"reviewed_artifact_sha256": artifact_sha256})


def _require_exact_trace_domain(
    trace: RawCurveTrace,
    calibration: PlotCalibration,
    variant: FaultTimeVoltageVariant,
) -> None:
    source = tuple(sorted(_log_space_point(point, calibration) for point in trace.points))
    candidate = tuple((point.x.log10(), point.y.log10()) for point in variant.points)
    tolerance = Decimal("1e-9")
    if (
        not source
        or not candidate
        or abs(candidate[0][0] - source[0][0]) > tolerance
        or abs(candidate[-1][0] - source[-1][0]) > tolerance
    ):
        raise ApprovalError("curve domain must equal the active source trace endpoints")


def _combined_conservatism_report(
    draft: ImportedRuleDraft,
    digitization: CurveDigitizationResult,
    variants: tuple[FaultTimeVoltageVariant, ...],
    calibration: PlotCalibration,
) -> ConservatismReport:
    reports = tuple(
        prove_variant_conservative(
            figure,
            trace,
            calibration,
            variant,
        )
        for variant in variants
        for figure, _current, trace in (_variant_evidence(draft, variant),)
    )
    if not reports or digitization.proposed_rule is None:
        raise ApprovalError("curve digitization lacks a complete proof inventory")
    return ConservatismReport(
        maximum_positive_voltage_error=max(
            report.maximum_positive_voltage_error for report in reports
        ),
        maximum_fidelity_error_pixels=max(
            report.maximum_fidelity_error_pixels for report in reports
        ),
        proven=all(report.proven for report in reports),
    )


def validate_current_curve_evidence(
    draft: ImportedRuleDraft,
    variant: FaultTimeVoltageVariant,
) -> None:
    """Recompute the executable variant proof from its current source evidence."""

    figure, digitization, trace = _variant_evidence(draft, variant)
    calibration = digitization.calibration
    if calibration is None:
        raise ApprovalError("curve variant lacks current calibration evidence")
    if any(
        (segment.segment_type, segment.interpolation)
        not in {("continuous", "log_log"), ("plateau", "constant")}
        for segment in variant.segments
    ):
        raise ApprovalError("curve interpolation has no analytic conservative proof")
    _require_exact_trace_domain(trace, calibration, variant)
    report = prove_variant_conservative(figure, trace, calibration, variant)
    proposed = digitization.proposed_rule
    if proposed is None:
        raise ApprovalError("curve proof lacks its proposed variant inventory")
    combined = _combined_conservatism_report(
        draft, digitization, proposed.variants, calibration
    )
    if not report.proven or digitization.conservatism != combined:
        raise ApprovalError("curve variant lacks a freshly recomputed conservative proof")
    expected = _reviewed_variant(
        variant,
        figure=figure,
        trace=trace,
        calibration=calibration,
    )
    if variant.reviewed_artifact_sha256 != expected.reviewed_artifact_sha256:
        raise ApprovalError("curve variant provenance is stale for current source evidence")
    if tuple(member for member in proposed.variants if member.id == variant.id) != (
        variant,
    ):
        raise ApprovalError("curve proof does not match the current semantic variant")


def _reprove_curve_variant(
    draft: ImportedRuleDraft,
    variant: FaultTimeVoltageVariant,
    *,
    calibration: PlotCalibration | None = None,
    trace: RawCurveTrace | None = None,
    allow_domain_rebuild: bool = False,
) -> tuple[FaultTimeVoltageVariant, tuple[CurveDigitizationResult, ...]]:
    figure, digitization, current_trace = _variant_evidence(draft, variant)
    active_trace = trace or current_trace
    if active_trace != current_trace:
        raise ApprovalError("curve trace does not match the active source evidence")
    active_calibration = calibration or digitization.calibration
    assert active_calibration is not None
    if any(
        (segment.segment_type, segment.interpolation)
        not in {("continuous", "log_log"), ("plateau", "constant")}
        for segment in variant.segments
    ):
        raise ApprovalError(
            "curve interpolation has no analytic conservative proof"
        )
    _require_exact_trace_domain(active_trace, active_calibration, variant)
    prior = next(
        member
        for member in digitization.proposed_rule.variants  # type: ignore[union-attr]
        if member.id == variant.id
    )
    if not allow_domain_rebuild and (
        variant.points[0].x != prior.points[0].x
        or variant.points[-1].x != prior.points[-1].x
    ):
        raise ApprovalError("curve correction cannot shorten or extend the reviewed domain")
    report = prove_variant_conservative(figure, active_trace, active_calibration, variant)
    if not report.proven:
        raise ApprovalError("curve correction is not conservative against source geometry")
    reviewed_variant = _reviewed_variant(
        variant,
        figure=figure,
        trace=active_trace,
        calibration=active_calibration,
    )
    proposed = digitization.proposed_rule
    assert proposed is not None
    changed_proposed = proposed.model_copy(
        update={
            "variants": tuple(
                reviewed_variant if member.id == variant.id else member
                for member in proposed.variants
            )
        }
    )
    combined_report = _combined_conservatism_report(
        draft,
        digitization,
        changed_proposed.variants,
        active_calibration,
    )
    if not combined_report.proven:
        raise ApprovalError("curve correction invalidates a sibling conservative proof")
    changed_digitization = digitization.model_copy(
        update={
            "proposed_rule": changed_proposed,
            "calibration": active_calibration,
            "conservatism": combined_report,
            "blocking_review_items": (),
        }
    )
    return reviewed_variant, tuple(
        changed_digitization if item is digitization else item
        for item in draft.curve_digitizations
    )


def replace_curve_breakpoint(
    draft: ImportedRuleDraft,
    *,
    variant_id: str,
    index: int,
    point: CurvePoint,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Replace one breakpoint of one variant; the aggregate proposal resets."""

    rule = next((r for r in draft.curves for v in r.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    if not 0 <= index < len(variant.points):
        raise ValueError("breakpoint index outside the variant")
    points = tuple(
        point if position == index else existing
        for position, existing in enumerate(variant.points)
    )
    changed_variant, digitizations = _reprove_curve_variant(
        draft, variant.model_copy(update={"points": points})
    )
    changed_rule = rule.model_copy(
        update={
            "variants": tuple(
                changed_variant if member.id == variant_id else member
                for member in rule.variants
            )
        }
    )
    return _replace_curve(
        draft,
        rule.id,
        changed_rule,
        actor=actor,
        notes=notes,
        curve_digitizations=digitizations,
    )


def replace_curve_points(
    draft: ImportedRuleDraft,
    *,
    variant_id: str,
    points: tuple[CurvePoint, ...],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Replace all points in one rejected automatic variant as one audited edit."""

    if not any(item.variant_id == variant_id for item in draft.curve_variant_rejections):
        raise ApprovalError("manual curve points require a blocking failure or rejection")
    rule = next((r for r in draft.curves for v in r.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    if len(points) != len(variant.points):
        raise ApprovalError("manual curve points must preserve the reviewed point inventory")
    changed_variant, digitizations = _reprove_curve_variant(
        draft, variant.model_copy(update={"points": points})
    )
    changed_rule = rule.model_copy(
        update={
            "variants": tuple(
                changed_variant if member.id == variant_id else member
                for member in rule.variants
            )
        }
    )
    return _replace_curve(
        draft,
        rule.id,
        changed_rule,
        actor=actor,
        notes=notes,
        curve_digitizations=digitizations,
    )


def recover_blocked_curve_figures(
    draft: ImportedRuleDraft,
    *,
    replacements: tuple[
        tuple[int, int, str | RawCurveTrace, PlotCalibration, tuple[CurvePoint, ...]], ...
    ],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Recover every blocked figure together, then build the aggregate proposal."""

    if not replacements:
        raise ApprovalError("manual recovery requires at least one blocked figure")
    by_slot = {
        (figure_index, slot_index): (trace_input, calibration, points)
        for figure_index, slot_index, trace_input, calibration, points in replacements
    }
    if len(by_slot) != len(replacements):
        raise ApprovalError("manual recovery contains duplicate variant entries")
    from insulation_coordination.rules.importer.recipes import RECIPES
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
        project_fault_time_voltage,
    )

    identities = {identity.recipe_id: identity for identity in draft.source_identities}
    recipe = next(
        (
            candidate
            for candidate in RECIPES
            if candidate.id == "iec62477-1-2022" and candidate.curves
        ),
        None,
    )
    identity = identities.get("iec62477-1-2022")
    if recipe is None or identity is None:
        raise ApprovalError("manual recovery lacks the IEC curve recipe identity")
    if len(draft.raw_figures) != len(draft.curve_digitizations) or len(recipe.curves) != 3:
        raise ApprovalError("manual recovery has an incomplete figure inventory")
    blocked_indexes = {
        index
        for index, result in enumerate(draft.curve_digitizations)
        if result.proposed_rule is None and result.blocking_review_items
    }
    expected_slots = {
        (figure_index, slot_index)
        for figure_index in blocked_indexes
        for slot_index in range(len(recipe.curves[figure_index].variant_slots))
    }
    if set(by_slot) != expected_slots:
        raise ApprovalError("manual recovery must cover every blocked curve variant exactly once")
    digitizations = list(draft.curve_digitizations)
    recovered_variants: dict[str, FaultTimeVoltageVariant] = {}
    raw_variants: dict[int, dict[int, FaultTimeVoltageVariant]] = {}
    reports: dict[int, list[ConservatismReport]] = {}
    associations = list(draft.curve_trace_associations)
    selected_trace_ids: dict[int, set[str]] = {}
    manual_traces = list(draft.manual_curve_traces)
    for (figure_index, slot_index), (trace_input, calibration, points) in sorted(
        by_slot.items()
    ):
        if not 0 <= figure_index < len(digitizations):
            raise ApprovalError("manual recovery figure index is outside the inventory")
        result = digitizations[figure_index]
        figure = draft.raw_figures[figure_index]
        spec = recipe.curves[figure_index]
        if result.proposed_rule is not None or not result.blocking_review_items:
            raise ApprovalError("manual recovery is allowed only for a blocked figure")
        available = tuple(
            item.trace
            for item in manual_traces
            if item.figure_artifact_sha256 == figure.artifact_sha256
        )
        if isinstance(trace_input, RawCurveTrace):
            if any(point.space != "pixel" for point in trace_input.points):
                raise ApprovalError("manual source trace must use figure pixel coordinates")
            if any(trace.id == trace_input.id for trace in (*figure.traces, *available)):
                raise ApprovalError("manual source trace ID duplicates existing evidence")
            manual_traces.append(
                ManualCurveTrace(
                    figure_artifact_sha256=figure.artifact_sha256,
                    trace=trace_input,
                    actor=actor.strip(),
                    recorded_at=datetime.now(UTC),
                    notes=notes.strip(),
                )
            )
            trace = trace_input
        else:
            traces = tuple(
                trace
                for trace in (*figure.traces, *available)
                if trace.id == trace_input
            )
            if len(traces) != 1:
                raise ApprovalError("manual recovery requires one source-scoped trace")
            trace = traces[0]
        used = selected_trace_ids.setdefault(figure_index, set())
        if trace.id in used:
            raise ApprovalError("manual recovery cannot reuse one trace for multiple variants")
        used.add(trace.id)
        if len(points) < 2 or any(point.x <= 0 or point.y <= 0 for point in points):
            raise ApprovalError("manual recovery requires at least two positive points")
        source_log = tuple(sorted(_log_space_point(point, calibration) for point in trace.points))
        candidate_log = tuple((point.x.log10(), point.y.log10()) for point in points)
        domain_tolerance = Decimal("1e-9")
        if (
            abs(candidate_log[0][0] - source_log[0][0]) > domain_tolerance
            or abs(candidate_log[-1][0] - source_log[-1][0]) > domain_tolerance
        ):
            raise ApprovalError("manual curve domain must equal the explicit traced endpoints")
        x_values = tuple(point.x for point in points)
        y_values = tuple(point.y for point in points)
        variant_id = f"{spec.semantic_id}.{spec.figure}"
        if len(spec.variant_slots) > 1:
            variant_id = f"{variant_id}.{slot_index + 1}"
        variant = FaultTimeVoltageVariant(
            id=variant_id,
            selector=spec.variant_slots[slot_index],
            x_axis=CurveAxis(
                quantity_kind=spec.x_quantity_kind,
                unit=spec.x_unit,
                scale="log10",
                minimum=min(x_values),
                maximum=max(x_values),
            ),
            y_axis=CurveAxis(
                quantity_kind=spec.y_quantity_kind,
                unit=spec.y_unit,
                scale="log10",
                minimum=min(y_values),
                maximum=max(y_values),
            ),
            points=points,
            segments=tuple(
                CurveSegment(
                    start=position,
                    end=position + 1,
                    segment_type="continuous",
                    interpolation="log_log",
                )
                for position in range(len(points) - 1)
            ),
            applicability="manual recovery requires exact review",
            source=figure.source,
            reviewed_artifact_sha256=figure.artifact_sha256,
        )
        report = prove_variant_conservative(figure, trace, calibration, variant)
        if not report.proven:
            raise ApprovalError("manual curve is not conservative against source geometry")
        raw_variants.setdefault(figure_index, {})[slot_index] = variant
        reports.setdefault(figure_index, []).append(report)
        recovered_variants[variant.id] = _reviewed_variant(
            variant,
            figure=figure,
            trace=trace,
            calibration=calibration,
        )
        associations.append(
            CurveTraceAssociation(
                variant_id=variant.id,
                figure_artifact_sha256=figure.artifact_sha256,
                trace_id=trace.id,
            )
        )
    for figure_index in blocked_indexes:
        result = digitizations[figure_index]
        figure = draft.raw_figures[figure_index]
        spec = recipe.curves[figure_index]
        members = tuple(
            raw_variants[figure_index][slot_index]
            for slot_index in range(len(spec.variant_slots))
        )
        member_reports = reports[figure_index]
        calibration = by_slot[(figure_index, 0)][1]
        if any(
            by_slot[(figure_index, slot_index)][1] != calibration
            for slot_index in range(len(spec.variant_slots))
        ):
            raise ApprovalError("manual variants from one figure must share one calibration")
        digitizations[figure_index] = result.model_copy(
            update={
                "proposed_rule": PiecewiseCurveRule(
                    id=spec.semantic_id,
                    variants=members,
                    source=figure.source,
                ),
                "calibration": calibration,
                "conservatism": ConservatismReport(
                    maximum_positive_voltage_error=max(
                        report.maximum_positive_voltage_error for report in member_reports
                    ),
                    maximum_fidelity_error_pixels=max(
                        report.maximum_fidelity_error_pixels for report in member_reports
                    ),
                    proven=True,
                ),
                "blocking_review_items": (),
            }
        )
    if any(result.proposed_rule is None for result in digitizations):
        raise ApprovalError("all blocked figures must be recovered in one audited action")
    variant_groups = tuple(
        result.proposed_rule.variants
        for result in digitizations
        if result.proposed_rule is not None
    )
    rule, proposals = project_fault_time_voltage(
        draft.raw_figures,
        variant_groups[0],
        variant_groups[1],
        variant_groups[2],
        identity,
    )
    rule = rule.model_copy(
        update={
            "variants": tuple(
                recovered_variants.get(variant.id, variant)
                for variant in rule.variants
            )
        }
    )
    for figure_index in blocked_indexes:
        proposed = digitizations[figure_index].proposed_rule
        assert proposed is not None
        digitizations[figure_index] = digitizations[figure_index].model_copy(
            update={
                "proposed_rule": proposed.model_copy(
                    update={
                        "variants": tuple(
                            recovered_variants[variant.id]
                            for variant in proposed.variants
                        )
                    }
                )
            }
        )
    blocking = tuple(
        item
        for item in draft.review_items
        if item.kind == "curve" and item.code != "CURVE_VARIANT_REVIEW_REQUIRED"
    )
    changed = draft.model_copy(
        update={
            "curves": (rule,),
            "curve_digitizations": tuple(digitizations),
            "curve_trace_associations": tuple(associations),
            "manual_curve_traces": tuple(manual_traces),
            "semantic_proposals": proposals,
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor,
        notes=notes,
        resolve=blocking,
    )


def replace_curve_segment(
    draft: ImportedRuleDraft,
    *,
    variant_id: str,
    index: int,
    segment: CurveSegment,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Replace one segment declaration of one variant; review resets."""

    rule = next((r for r in draft.curves for v in r.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    if not 0 <= index < len(variant.segments):
        raise ValueError("segment index outside the variant")
    segments = tuple(
        segment if position == index else existing
        for position, existing in enumerate(variant.segments)
    )
    changed_variant, digitizations = _reprove_curve_variant(
        draft, variant.model_copy(update={"segments": segments})
    )
    changed_rule = rule.model_copy(
        update={
            "variants": tuple(
                changed_variant if v.id == variant_id else v for v in rule.variants
            )
        }
    )
    return _replace_curve(
        draft,
        rule.id,
        changed_rule,
        actor=actor,
        notes=notes,
        curve_digitizations=digitizations,
    )


def _rebuild_figure_curve(
    draft: ImportedRuleDraft,
    *,
    figure: RawFigure,
    calibration: PlotCalibration,
) -> tuple[PiecewiseCurveRule, PiecewiseCurveRule, tuple[CurveDigitizationResult, ...]]:
    variants = tuple(
        variant
        for rule in draft.curves
        for variant in rule.variants
        if _source_matches(variant.source, figure.source)
    )
    if not variants:
        raise ApprovalError("curve correction requires figure variants")
    rules = tuple(
        rule for rule in draft.curves if any(variant in rule.variants for variant in variants)
    )
    if len(rules) != 1:
        raise ApprovalError("curve correction requires one aggregate curve rule")
    rule = rules[0]
    reviewed: dict[str, FaultTimeVoltageVariant] = {}
    reports: list[ConservatismReport] = []
    digitization: CurveDigitizationResult | None = None
    for variant in variants:
        active_figure, current_digitization, trace = _variant_evidence(draft, variant)
        if digitization is not None and current_digitization is not digitization:
            raise ApprovalError("figure variants do not share one calibration inventory")
        digitization = current_digitization
        rebuilt = rebuild_variant_from_calibration(trace, calibration, variant)
        _require_exact_trace_domain(trace, calibration, rebuilt)
        report = prove_variant_conservative(active_figure, trace, calibration, rebuilt)
        if not report.proven:
            raise ApprovalError(
                "curve correction is not conservative against source geometry"
            )
        reports.append(report)
        reviewed[variant.id] = _reviewed_variant(
            rebuilt,
            figure=active_figure,
            trace=trace,
            calibration=calibration,
        )
    assert digitization is not None and digitization.proposed_rule is not None
    changed_proposed = digitization.proposed_rule.model_copy(
        update={
            "variants": tuple(
                reviewed.get(member.id, member)
                for member in digitization.proposed_rule.variants
            )
        }
    )
    combined = ConservatismReport(
        maximum_positive_voltage_error=max(
            report.maximum_positive_voltage_error for report in reports
        ),
        maximum_fidelity_error_pixels=max(
            report.maximum_fidelity_error_pixels for report in reports
        ),
        proven=all(report.proven for report in reports),
    )
    changed_digitization = digitization.model_copy(
        update={
            "proposed_rule": changed_proposed,
            "calibration": calibration,
            "conservatism": combined,
            "blocking_review_items": (),
        }
    )
    digitizations = tuple(
        changed_digitization if item is digitization else item
        for item in draft.curve_digitizations
    )
    changed_rule = rule.model_copy(
        update={
            "variants": tuple(
                reviewed.get(member.id, member) for member in rule.variants
            )
        }
    )
    return rule, changed_rule, digitizations


def associate_curve_traces(
    draft: ImportedRuleDraft,
    *,
    variant_trace_ids: Mapping[str, str],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Atomically replace one figure's complete variant-to-trace permutation."""

    if not variant_trace_ids:
        raise ApprovalError("curve trace association mapping is empty")
    selected = tuple(
        variant
        for rule in draft.curves
        for variant in rule.variants
        if variant.id in variant_trace_ids
    )
    if len(selected) != len(variant_trace_ids):
        raise ValueError("curve trace association contains an unknown variant")
    figures = tuple(
        figure
        for figure in draft.raw_figures
        if _source_matches(figure.source, selected[0].source)
    )
    if len(figures) != 1 or any(
        not _source_matches(variant.source, figures[0].source) for variant in selected
    ):
        raise ApprovalError("curve trace association must target exactly one source figure")
    figure = figures[0]
    siblings = tuple(
        variant
        for rule in draft.curves
        for variant in rule.variants
        if _source_matches(variant.source, figure.source)
    )
    if set(variant_trace_ids) != {variant.id for variant in siblings}:
        raise ApprovalError("curve trace association must cover every figure variant")
    if len(set(variant_trace_ids.values())) != len(variant_trace_ids):
        raise ApprovalError("curve trace association must be one-to-one")
    manual_traces = tuple(
        item.trace
        for item in draft.manual_curve_traces
        if item.figure_artifact_sha256 == figure.artifact_sha256
    )
    available_ids = {trace.id for trace in (*figure.traces, *manual_traces)}
    if not set(variant_trace_ids.values()) <= available_ids:
        raise ApprovalError("curve trace association references foreign source evidence")
    _figure, digitization, _trace = _variant_evidence(draft, siblings[0])
    assert digitization.calibration is not None
    traces_by_id = {
        trace.id: trace for trace in (*figure.traces, *manual_traces)
    }
    for variant in siblings:
        _require_exact_trace_domain(
            traces_by_id[variant_trace_ids[variant.id]],
            digitization.calibration,
            variant,
        )
    sibling_ids = {variant.id for variant in siblings}
    associated = draft.model_copy(
        update={
            "curve_trace_associations": (
                *(
                    item
                    for item in draft.curve_trace_associations
                    if item.variant_id not in sibling_ids
                ),
                *(
                    CurveTraceAssociation(
                        variant_id=variant.id,
                        figure_artifact_sha256=figure.artifact_sha256,
                        trace_id=variant_trace_ids[variant.id],
                    )
                    for variant in siblings
                ),
            )
        }
    )
    rule, changed_rule, digitizations = _rebuild_figure_curve(
        associated,
        figure=figure,
        calibration=digitization.calibration,
    )
    return _replace_curve(
        associated,
        rule.id,
        changed_rule,
        actor=actor,
        notes=notes,
        curve_digitizations=digitizations,
        original_draft=draft,
    )


def associate_curve_trace(
    draft: ImportedRuleDraft,
    *,
    trace_id: str,
    variant_id: str,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Select one trace; swap its occupied sibling association atomically."""

    rule = next((r for r in draft.curves for v in r.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    figures = tuple(
        figure
        for figure in draft.raw_figures
        if _source_matches(figure.source, variant.source)
    )
    if len(figures) != 1:
        raise ApprovalError("curve variant must have exactly one matching source figure")
    figure = figures[0]
    siblings = tuple(
        member for member in rule.variants if _source_matches(member.source, figure.source)
    )
    associations = {
        item.variant_id: item.trace_id
        for item in draft.curve_trace_associations
        if item.variant_id in {member.id for member in siblings}
    }
    if not associations and len(siblings) == 1:
        manual_traces = tuple(
            item.trace
            for item in draft.manual_curve_traces
            if item.figure_artifact_sha256 == figure.artifact_sha256
        )
        traces = (*figure.traces, *manual_traces)
        if len(traces) != 1:
            raise ApprovalError("curve trace selection requires an active source inventory")
        associations[variant.id] = traces[0].id
    if set(associations) != {member.id for member in siblings}:
        raise ApprovalError("curve trace selection requires complete current associations")
    available = {
        trace.id
        for trace in (
            *figure.traces,
            *(
                item.trace
                for item in draft.manual_curve_traces
                if item.figure_artifact_sha256 == figure.artifact_sha256
            ),
        )
    }
    if trace_id not in available:
        if any(
            trace.id == trace_id
            for other in draft.raw_figures
            if other is not figure
            for trace in other.traces
        ):
            raise ApprovalError("curve trace does not belong to the variant source figure")
        raise ValueError(f"unknown raw trace: {trace_id}")
    old_trace_id = associations[variant.id]
    occupant = next(
        (member_id for member_id, current in associations.items() if current == trace_id),
        None,
    )
    associations[variant.id] = trace_id
    if occupant is not None and occupant != variant.id:
        associations[occupant] = old_trace_id
    return associate_curve_traces(
        draft,
        variant_trace_ids=associations,
        actor=actor,
        notes=notes,
    )


def correct_curve_calibration(
    draft: ImportedRuleDraft,
    *,
    figure_page: int,
    calibration: PlotCalibration,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Replace one figure's calibration; the digitization and rule must rebuild."""

    figure = next(
        (figure for figure in draft.raw_figures if figure.source.page == figure_page),
        None,
    )
    if figure is None:
        raise ValueError(f"unknown raw figure on page {figure_page}")
    rule, changed_rule, digitizations = _rebuild_figure_curve(
        draft,
        figure=figure,
        calibration=calibration,
    )
    return _replace_curve(
        draft,
        rule.id,
        changed_rule,
        actor=actor,
        notes=notes,
        curve_digitizations=digitizations,
    )


def review_curve_variant(
    draft: ImportedRuleDraft,
    variant_id: str,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record an exact member review; review the aggregate only after every member."""

    if not actor.strip() or not notes.strip():
        raise ApprovalError("curve review actor and notes are required")
    rule = next((rule for rule in draft.curves for v in rule.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    if any(
        rejection.variant_id == variant.id
        and rejection.variant_sha256 == canonical_model_sha256(variant)
        for rejection in draft.curve_variant_rejections
    ):
        raise ApprovalError("rejected curve variant must be corrected before review")
    figure, _digitization, _trace = _variant_evidence(draft, variant)
    if variant.reviewed_artifact_sha256 == figure.artifact_sha256:
        changed_variant, digitizations = _reprove_curve_variant(draft, variant)
        changed_rule = rule.model_copy(
            update={
                "variants": tuple(
                    changed_variant if member.id == variant.id else member
                    for member in rule.variants
                )
            }
        )
        draft = _replace_curve(
            draft,
            rule.id,
            changed_rule,
            actor=actor,
            notes=f"bind exact curve review provenance: {notes}",
            curve_digitizations=digitizations,
        )
        rule = next(rule for rule in draft.curves if rule.id == changed_rule.id)
        variant = _variant(rule, variant_id)
    validate_current_curve_evidence(draft, variant)
    review = CurveVariantReview(
        variant_id=variant.id,
        variant_sha256=canonical_model_sha256(variant),
        source_artifact_sha256=variant.reviewed_artifact_sha256,
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    member_items = tuple(
        item
        for item in draft.review_items
        if item.kind == "curve" and item.semantic_id == variant.id
    )
    if len(member_items) != 1:
        raise ApprovalError("curve variant lacks one exact review item")
    base = draft
    if not any(
        item.review_item_sha256 == member_items[0].sha256
        for item in draft.review_resolutions
    ):
        base = record_correction(
            draft,
            draft,
            actor=actor,
            notes=notes,
            resolve=member_items,
        )
    current = tuple(
        item for item in base.curve_variant_reviews if item.variant_id != variant.id
    )
    changed = base.model_copy(
        update={"curve_variant_reviews": (*current, review)}
    )
    changed = record_correction(
        base,
        changed,
        actor=actor,
        notes=f"record exact curve variant review: {notes}",
    )
    if all(
        any(
            item.variant_id == member.id
            and item.variant_sha256 == canonical_model_sha256(member)
            and item.source_artifact_sha256 == member.reviewed_artifact_sha256
            for item in changed.curve_variant_reviews
        )
        for member in rule.variants
    ):
        return mark_proposal_reviewed(changed, rule.id, actor=actor, notes=notes)
    return changed


def reject_curve_variant(
    draft: ImportedRuleDraft,
    variant_id: str,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record rejection of the current automatic proposal and enable manual fallback."""

    if not actor.strip() or not notes.strip():
        raise ApprovalError("curve rejection actor and notes are required")
    rule = next((rule for rule in draft.curves for v in rule.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    rejection = CurveVariantRejection(
        variant_id=variant.id,
        variant_sha256=canonical_model_sha256(variant),
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    proposals = tuple(
        proposal.model_copy(update={"state": "proposed"})
        if proposal.semantic_id == rule.id
        else proposal
        for proposal in draft.semantic_proposals
    )
    changed = draft.model_copy(
        update={
            "semantic_proposals": proposals,
            "curve_variant_reviews": tuple(
                review for review in draft.curve_variant_reviews if review.variant_id != variant.id
            ),
            "curve_variant_rejections": (
                *(
                    item
                    for item in draft.curve_variant_rejections
                    if item.variant_id != variant.id
                ),
                rejection,
            ),
        }
    )
    return record_correction(draft, changed, actor=actor, notes=notes)
