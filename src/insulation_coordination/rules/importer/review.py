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
from typing import Literal as TypingLiteral

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    ApprovalRecord,
    CompatibilityMapping,
    CurveAxis,
    CurvePoint,
    DecisionRule,
    DraftRulePackage,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    Formula,
    GuidanceRule,
    Identifier,
    LinearInterpolate,
    Literal,
    Lookup,
    Parameter,
    ParameterSet,
    PiecewiseCurveRule,
    ProcedureRule,
    RuleKind,
    RulePackageError,
    SourceReference,
    Table,
    Variable,
)
from insulation_coordination.domain.rules import Expression as RuleExpression
from insulation_coordination.rules.archive import _canonical_json
from insulation_coordination.rules.importer.approval import ApprovalError, record_correction
from insulation_coordination.rules.importer.axis_selectors import (
    AxisSelector,
    AxisSelectorProposal,
    AxisSelectorReview,
    ConfirmedAxes,
    selector_sha256,
)
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ClauseFactCompletion,
    ClauseFactDismissal,
    ClauseFactReview,
    ConfirmedFacts,
    SupplyFact,
    evidence_sha256,
    same_clause_fact_reading,
)
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    RawFigure,
    infer_curve_segments,
)
from insulation_coordination.rules.importer.extract import (
    ComponentFormulaCandidate,
    CurveCalibrationReview,
    CurveVariantReview,
    ImportedRuleDraft,
    ImportReviewItem,
    ManualCurveVariantInput,
    RawGrid,
    RawGridCell,
    SemanticProposal,
    aggregate_artifact_sha256,
    axis_evidence_sha256,
    axis_positions,
    canonical_model_sha256,
    is_recipe_derived,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    CurveAuditSpec,
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardIdentity,
    StandardRecipe,
    TableAuditSpec,
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
        raise ApprovalError(f"semantic proposal {proposal.semantic_id} has no unique current rule")
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
    if len({artifact_id for artifact_id, _ in pairs}) != len(pairs):
        raise ApprovalError("semantic proposal has duplicate source artifact IDs")
    # Through the same function a multi-artifact projection grounds its own proposal with, so
    # the gate cannot re-derive a different aggregate from the same artifacts.
    return aggregate_artifact_sha256(pairs)


def _review_item_artifact_id(item: ImportReviewItem) -> str:
    return f"{item.semantic_id}:{item.code}"


def _source_semantic_id(proposal: SemanticProposal) -> str:
    """The recipe spec a projected rule came from.

    A projection may emit several rules from one source artifact -- a table that becomes a
    family of decisions, a clause that yields a decision plus the guidance its NOTE
    carries -- and names them ``"<spec id>.<route>"``. Their review inventory and source
    artifact belong to the spec, not to the route, and the recipe is what knows which
    specs exist, so this reads the declarations rather than listing one standard's
    identifiers here.
    """
    from insulation_coordination.rules.importer.recipes import RECIPES

    declared: set[str] = set()
    for recipe in RECIPES:
        declared.update(spec.semantic_id for spec in recipe.tables)
        declared.update(spec.semantic_id for spec in recipe.clauses)
        declared.update(spec.semantic_id for spec in recipe.curves)
        declared.update(spec.semantic_id for spec in recipe.formulas)
    if proposal.semantic_id in declared:
        return proposal.semantic_id
    #: Only a route the recipe declares resolves back to its spec. An identifier that
    #: merely starts with a spec's identifier is not one of its routes and must not borrow
    #: its grounding, so it keeps its own identifier and fails the review inventory check.
    for recipe in RECIPES:
        for table_spec in recipe.tables:
            if proposal.semantic_id in table_spec.decision_route_ids:
                return table_spec.semantic_id
        for clause_spec in recipe.clauses:
            if proposal.semantic_id in clause_spec.projected_rule_ids:
                return clause_spec.semantic_id
    return proposal.semantic_id


def _clause_evidence_semantic_ids(source_semantic_id: str) -> frozenset[str]:
    """The evidence-only clause specs the named clause spec's rule also rests on.

    A rule read from two subclauses is grounded in both, so both fragments' review items gate
    its proposal and both fragments' hashes enter its source digest. Without this the second
    fragment would contribute nothing to the proposal's grounding, which is the whole hazard
    ``projection_role`` exists to avoid.
    """
    from insulation_coordination.rules.importer.recipes import RECIPES

    return frozenset(
        evidence_id
        for recipe in RECIPES
        for spec in recipe.clauses
        if spec.semantic_id == source_semantic_id
        for evidence_id in spec.evidence_clause_ids
    )


def _required_review_items(
    draft: ImportedRuleDraft,
    proposal: SemanticProposal,
) -> tuple[ImportReviewItem, ...]:
    rule = _rule_for(draft, proposal)
    source_semantic_id = _source_semantic_id(proposal)
    semantic_ids = {proposal.semantic_id, source_semantic_id}
    semantic_ids.update(_clause_evidence_semantic_ids(source_semantic_id))
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
            tuple((variant.id, variant.reviewed_artifact_sha256) for variant in rule.variants)
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
    fragment_ids = {
        proposal.semantic_id,
        f"raw-{proposal.semantic_id}",
        source_semantic_id,
        f"raw-{source_semantic_id}",
    }
    # A rule two subclauses state between them is grounded in both fragments, never in
    # whichever one the spec lookup above happens to reach first.
    fragment_ids.update(
        f"raw-{evidence_id}" for evidence_id in _clause_evidence_semantic_ids(source_semantic_id)
    )
    fragments = tuple(
        (fragment.id, canonical_model_sha256(fragment))
        for fragment in draft.raw_clause_fragments
        if fragment.id in fragment_ids
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
    cross_standard = _cross_standard_artifacts(draft, proposal)
    if cross_standard:
        return _aggregate_artifact_pairs(cross_standard)
    recipe_artifacts = _recipe_source_artifacts(proposal)
    if recipe_artifacts:
        return _aggregate_artifact_pairs(recipe_artifacts)
    raise ApprovalError(
        f"semantic proposal {proposal.semantic_id} has no real current source artifact"
    )


def _cross_standard_artifacts(
    draft: ImportedRuleDraft,
    proposal: SemanticProposal,
) -> tuple[tuple[str, str], ...]:
    """Both compared grids, for a mapping a cross-standard check produced.

    The evidence for an equivalence is the pair of grids it compared, so a change to
    either one changes this proposal's artifact hash and resets its review. Neither grid
    carries the mapping's own identifier, which is why the earlier lookups miss it.
    """
    from insulation_coordination.rules.importer.recipes import RECIPES

    spec = next(
        (
            check
            for recipe in RECIPES
            for check in recipe.cross_standard_checks
            if check.id == proposal.semantic_id
        ),
        None,
    )
    if spec is None:
        return ()
    compared = {spec.source_grid_id, spec.target_grid_id}
    pairs = tuple(
        (grid.id, canonical_model_sha256(grid)) for grid in draft.raw_grids if grid.id in compared
    )
    return pairs if len(pairs) == len(compared) else ()


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
    if not any(fragment.id == f"raw-{semantic_id}" for fragment in draft.raw_clause_fragments):
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
        coordinate for coordinate in component_corrections if coordinate[:2] not in correctable
    )
    if unexpected:
        raise ValueError(f"raw grid cell is not correctable: {sorted(unexpected)!r}")
    cells: list[RawGridCell] = []
    for cell in grid.cells:
        coordinate = (cell.row, cell.column)
        selected_components = {
            key[2]: value for key, value in component_corrections.items() if key[:2] == coordinate
        }
        if (
            coordinate not in flagged
            and coordinate not in scalar_corrections
            and not selected_components
        ):
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
                            if (cell.row, cell.column) == (replacement.row, replacement.column)
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
        and {part.component_id for part in cell.components} == set(cell.compound_component_ids)
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
        component for component in cell.components if component.source_index == source_index
    )
    if len(matches) != 1:
        raise ValueError("association correction needs one exact source occurrence")
    replacement = matches[0].model_copy(update={"component_id": component_id})
    components = tuple(
        replacement if part.source_index == source_index else part for part in cell.components
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
        candidate for candidate in cell.formula_candidates if candidate.source_index != source_index
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
    changed = cell.model_copy(update={"components": components, "formula_candidates": candidates})
    return changed.model_copy(
        update={"parse_status": "compound" if _compound_complete(changed) else "ambiguous_compound"}
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
            (item.code == "AMBIGUOUS_COMPOUND_CELL" and item.semantic_id.startswith(prefix))
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
            (part for part in cell.components if part.source_index == source_index),
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
    from insulation_coordination.rules.importer.crosscheck import compare_across_standards
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
    procedures: dict[str, ProcedureRule] = {rule.id: rule for rule in draft.procedures}

    def collect(projected: tuple[object, ...]) -> None:
        """Route each projected rule to the draft field its type belongs in.

        One source artifact may project several kinds: a clause yields a decision plus the
        guidance its NOTE carries, and a procedure table yields one procedure per variant.
        ``model_copy`` does not validate, so a rule appended to the wrong field would sit
        there undetected -- hence the explicit refusal of a kind this does not know.
        """
        for rule in projected:
            if isinstance(rule, DecisionRule):
                decisions[rule.id] = rule
            elif isinstance(rule, GuidanceRule):
                guidance[rule.id] = rule
            elif isinstance(rule, ProcedureRule):
                procedures[rule.id] = rule
            else:
                raise TypeError(
                    f"projection produced an unsupported rule type: {type(rule).__name__}"
                )

    for recipe in RECIPES:
        identity = identities[recipe.id]
        for table_spec in recipe.tables:
            grid = grids[f"raw-{table_spec.semantic_id}"]
            if table_spec.comparison_only:
                # Extracted to prove or refute equivalence with another standard's rule,
                # not to be executed. The raw grid stays in the draft as the evidence.
                continue
            grid_projector = recipe.grid_projectors.get(table_spec.semantic_id)
            if grid_projector is None:
                tables[table_spec.semantic_id] = project_table(identity, table_spec, grid)
                continue
            confirmed_axes = resolve_confirmed_axis_selectors(table_spec, grid, draft)
            projected, _proposals = grid_projector(grid, identity, confirmed_axes)
            collect(projected)
        for formula_spec in recipe.formulas:
            formulas[formula_spec.semantic_id] = project_formula(identity, formula_spec, equations)
        for mapping_spec in recipe.mappings:
            mappings[mapping_spec.id] = project_mapping(identity, mapping_spec)
        for check_spec in recipe.cross_standard_checks:
            if not {check_spec.source_grid_id, check_spec.target_grid_id} <= set(grids):
                # Neither grid can be compared before both are extracted. A draft that
                # should hold them and does not is caught by the completeness gate at
                # approval, which reports the absent content by name.
                continue
            mapping, divergences = compare_across_standards(grids, check_spec)
            if divergences:
                raise ValueError(
                    "Resolve cross-standard divergences first: "
                    + "; ".join(item.expected_contract for item in divergences[:3])
                )
            if mapping is not None:
                mappings[mapping.id] = mapping
        for clause_spec in recipe.clauses:
            if clause_spec.projection_role == "evidence":
                # Its fragment is reviewed evidence for another clause's rule, and it projects
                # nothing of its own. The recipe refuses to register a projector for it.
                continue
            fragment = fragments.get(f"raw-{clause_spec.semantic_id}")
            required = (clause_spec.semantic_id, *clause_spec.evidence_clause_ids)
            if any(f"raw-{item}" not in fragments for item in required):
                # A draft extracted before this clause recipe existed has no
                # fragment; approval gating reports the missing required content.
                continue
            assert fragment is not None
            confirmed_facts = resolve_confirmed_clause_facts(clause_spec, draft)
            projected, _proposals = recipe.clause_projectors[clause_spec.semantic_id](
                fragment, identity, draft, confirmed_facts
            )
            collect(projected)

    changed = draft.model_copy(
        update={
            "tables": tuple(tables.values()),
            "formulas": tuple(formulas.values()),
            "mappings": tuple(mappings.values()),
            "decisions": tuple(decisions.values()),
            "guidance": tuple(guidance.values()),
            "procedures": tuple(procedures.values()),
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
            if table_spec.comparison_only:
                # A comparison-only grid is present once its raw evidence is in the draft;
                # it never becomes a typed rule of its own.
                present = f"raw-{table_spec.semantic_id}" in {
                    raw_grid.id for raw_grid in draft.raw_grids
                }
            else:
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
                    page_number=clause_spec.segments[0].page_number,
                    clause=clause_spec.clause,
                    present=f"raw-{clause_spec.semantic_id}" in fragment_ids,
                )
            )
    return tuple(statuses)


def missing_required_content(draft: ImportedRuleDraft) -> tuple[RequiredContentStatus, ...]:
    """Required content that is not yet present as typed rule content."""
    return tuple(item for item in required_content_report(draft) if not item.present)


class InventoryStatus(FrozenModel):
    """How far one required source item has travelled through the pipeline."""

    semantic_id: Identifier
    consumer_issue_ids: tuple[int, ...]
    located: bool
    extracted: bool
    typed: bool
    approved: bool
    deferred: bool


def _covers(candidate: str, semantic_id: str) -> bool:
    """Whether ``candidate`` is the required item or one of its declared routes.

    A required item is often extracted as several specs -- Table 7 splits into an AC and a
    DC route, Table 9 into one construction each -- so a route is named
    ``"<semantic id>.<route>"``.
    """
    return candidate == semantic_id or candidate.startswith(f"{semantic_id}.")


def inventory_report(draft: ImportedRuleDraft) -> tuple[InventoryStatus, ...]:
    """Package completeness computed from the required source inventory.

    Completeness is never a count of extracted tables: it is this checklist, in the order
    the inventory declares, so a package cannot look complete while a required item is
    absent.
    """
    from insulation_coordination.rules.importer.expectations import package_expectations
    from insulation_coordination.rules.importer.iec62477_2022.inventory import (
        DEFERRED_SEMANTIC_IDS,
        REQUIRED_SOURCE_ITEMS,
    )
    from insulation_coordination.rules.importer.recipes import RECIPES

    # What each declared spec is expected to contribute, from the one derivation the
    # approval and validation gates also read. A spec's kind decides both whether a raw
    # artifact must exist for it and what counts as its typed result, so they cannot share
    # one set: a formula has no raw grid, and a comparison-only grid never becomes a typed
    # rule at all.
    expectations = package_expectations(RECIPES)
    needs_raw = expectations.raw_artifact_ids
    evidence_only = expectations.evidence_grid_ids
    typed_expected = expectations.typed_results
    declared = frozenset(typed_expected)

    raw_ids = {grid.id for grid in draft.raw_grids}
    raw_ids.update(fragment.id for fragment in draft.raw_clause_fragments)
    raw_ids.update(f"raw-{curve.id}" for curve in draft.curves)
    typed_ids = {rule.id for rule in draft.tables}
    typed_ids.update(rule.id for rule in draft.decisions)
    typed_ids.update(rule.id for rule in draft.procedures)
    typed_ids.update(rule.id for rule in draft.guidance)
    typed_ids.update(rule.id for rule in draft.curves)
    typed_ids.update(rule.id for rule in draft.formulas)
    unresolved = {
        item.semantic_id
        for kind in ("table", "formula", "mapping", "clause", "semantic", "curve")
        for item in _unresolved_items(draft, kind)
    }

    statuses: list[InventoryStatus] = []
    for item in REQUIRED_SOURCE_ITEMS:
        semantic_id = item.semantic_id
        matching = {candidate for candidate in declared if _covers(candidate, semantic_id)}
        located = bool(matching)
        extracted = located and all(
            f"raw-{candidate}" in raw_ids or candidate in raw_ids
            for candidate in matching & needs_raw
        )
        # A comparison-only grid contributes evidence, not a rule, so it satisfies this item
        # by being extracted. Everything else must produce the typed result its kind implies.
        required_typed = {
            route
            for candidate in matching - evidence_only
            for route in typed_expected.get(candidate, frozenset({candidate}))
        }
        typed = located and required_typed <= typed_ids
        blocked = any(
            _covers(pending, semantic_id) or pending.startswith(f"raw-{semantic_id}")
            for pending in unresolved
        )
        statuses.append(
            InventoryStatus(
                semantic_id=semantic_id,
                consumer_issue_ids=item.consumer_issue_ids,
                located=located,
                extracted=extracted,
                typed=typed,
                approved=typed and not blocked,
                deferred=semantic_id in DEFERRED_SEMANTIC_IDS,
            )
        )
    return tuple(statuses)


def missing_inventory_items(draft: ImportedRuleDraft) -> tuple[InventoryStatus, ...]:
    """Required inventory items this build can extract but this draft has not approved.

    An item no recipe declares is not reported here: that is either Slice E content, which
    the deferred set records, or a build running an injected recipe registry. Either way
    the gap is in the build rather than in the draft, and
    ``test_inventory.py`` asserts against the real registry that every non-deferred item
    has a recipe. What this gate refuses is a draft that skipped content the build knows
    how to extract.
    """
    return tuple(
        status
        for status in inventory_report(draft)
        if status.located and not (status.approved or status.deferred)
    )


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


def _manual_recipes() -> tuple[StandardRecipe, ...]:
    from insulation_coordination.rules.importer.recipes import RECIPES

    return RECIPES


def _manual_curve_slot(
    draft: ImportedRuleDraft, variant_id: str
) -> tuple[CurveAuditSpec, FaultTimeVoltageSelector]:
    """Resolve a stable variant ID from the recipe slot inventory."""

    matches: list[tuple[CurveAuditSpec, FaultTimeVoltageSelector]] = []
    for identity in draft.source_identities:
        for recipe in _manual_recipes():
            if (
                recipe.id != identity.recipe_id
                or recipe.standard != identity.standard
                or recipe.edition != identity.edition
            ):
                continue
            for spec in recipe.curves:
                for index, selector in enumerate(spec.variant_slots, start=1):
                    if variant_id == f"{spec.semantic_id}.{spec.figure}.{index}":
                        matches.append((spec, selector))
    if len(matches) != 1:
        raise ValueError(f"unknown curve variant: {variant_id}")
    return matches[0]


def _source_matches(actual: SourceReference, expected: SourceReference) -> bool:
    return all(
        getattr(actual, field) == getattr(expected, field)
        for field in ("document_id", "standard", "edition", "page", "figure")
    )


def _manual_figure(draft: ImportedRuleDraft, spec: CurveAuditSpec) -> RawFigure:
    matches = tuple(
        figure
        for figure in draft.raw_figures
        if figure.source.page == spec.page_number
        and figure.source.figure == spec.figure
        and any(
            identity.standard == figure.source.standard
            and identity.edition == figure.source.edition
            for identity in draft.source_identities
        )
    )
    if len(matches) != 1:
        raise ApprovalError("curve variant must have exactly one matching source figure")
    return matches[0]


def _manual_calibration(draft: ImportedRuleDraft, figure: RawFigure) -> CurveCalibrationReview:
    matches = tuple(
        review
        for review in draft.curve_calibrations
        if review.figure_artifact_sha256 == figure.artifact_sha256
    )
    if len(matches) != 1:
        raise ApprovalError("curve variant must have exactly one reviewed calibration")
    calibration = matches[0]
    if (
        calibration.calibration.figure_artifact_sha256 != figure.artifact_sha256
        or calibration.calibration_sha256 != canonical_model_sha256(calibration.calibration)
    ):
        raise ApprovalError("curve variant has stale calibration evidence")
    return calibration


def _manual_reviewed_artifact_sha256(figure: RawFigure, calibration_sha256: str) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "figure_artifact_sha256": figure.artifact_sha256,
                "calibration_sha256": calibration_sha256,
            }
        )
    ).hexdigest()


def _resolved_curve_items(
    draft: ImportedRuleDraft, variant_ids: set[str]
) -> tuple[ImportReviewItem, ...]:
    resolved = {item.review_item_sha256 for item in draft.review_resolutions}
    return tuple(
        item
        for item in draft.review_items
        if (item.kind == "curve" and item.semantic_id in variant_ids and item.sha256 in resolved)
    )


def _source_x_scale(spec: CurveAuditSpec) -> Decimal:
    source_unit = spec.x_source_unit or spec.x_unit
    if source_unit == spec.x_unit:
        return Decimal(1)
    if (source_unit, spec.x_unit) == ("ms", "s"):
        return Decimal("0.001")
    raise ApprovalError("unsupported source-axis unit conversion")


def set_manual_curve_calibration(
    draft: ImportedRuleDraft,
    *,
    figure: str,
    calibration: ManualPlotCalibration,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record one local plot calibration and invalidate its curve reviews."""

    figures = tuple(
        raw_figure for raw_figure in draft.raw_figures if raw_figure.source.figure == figure
    )
    if len(figures) != 1:
        raise ValueError(f"unknown raw figure: {figure}")
    raw_figure = figures[0]
    if calibration.figure_artifact_sha256 != raw_figure.artifact_sha256:
        raise ApprovalError("manual calibration does not match the source figure")
    calibration_sha256 = canonical_model_sha256(calibration)
    reviewed_artifact_sha256 = _manual_reviewed_artifact_sha256(raw_figure, calibration_sha256)
    updated_variants = {
        variant.id: variant.model_copy(
            update={"reviewed_artifact_sha256": reviewed_artifact_sha256}
        )
        for rule in draft.curves
        for variant in rule.variants
        if _source_matches(variant.source, raw_figure.source)
    }
    reviewed_ids = set(updated_variants)
    calibration_review = CurveCalibrationReview(
        figure_artifact_sha256=raw_figure.artifact_sha256,
        calibration=calibration,
        calibration_sha256=calibration_sha256,
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    changed = draft.model_copy(
        update={
            "curves": tuple(
                rule.model_copy(
                    update={
                        "variants": tuple(
                            updated_variants.get(variant.id, variant) for variant in rule.variants
                        )
                    }
                )
                for rule in draft.curves
            ),
            "curve_calibrations": (
                *(
                    item
                    for item in draft.curve_calibrations
                    if item.figure_artifact_sha256 != raw_figure.artifact_sha256
                ),
                calibration_review,
            ),
            "curve_variant_reviews": tuple(
                review
                for review in draft.curve_variant_reviews
                if review.variant_id not in reviewed_ids
            ),
            "manual_curve_variant_inputs": tuple(
                input.model_copy(
                    update={
                        "variant_sha256": canonical_model_sha256(
                            updated_variants[input.variant_id]
                        ),
                        "source_artifact_sha256": reviewed_artifact_sha256,
                        "calibration_sha256": calibration_sha256,
                    }
                )
                if input.variant_id in updated_variants
                else input
                for input in draft.manual_curve_variant_inputs
            ),
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor,
        notes=notes,
        reopen=_resolved_curve_items(draft, reviewed_ids),
    )


def replace_manual_curve_variant(
    draft: ImportedRuleDraft,
    *,
    variant_id: str,
    source_points: tuple[CurvePoint, ...],
    actor: str,
    notes: str,
    input_origin: TypingLiteral["empty", "automatic_suggestion"],
) -> ImportedRuleDraft:
    """Atomically replace one manually reviewed curve variant from table points."""

    spec, selector = _manual_curve_slot(draft, variant_id)
    raw_figure = _manual_figure(draft, spec)
    calibration_review = _manual_calibration(draft, raw_figure)
    calibration = calibration_review.calibration
    if input_origin not in {"empty", "automatic_suggestion"}:
        raise ValueError("manual curve input origin is invalid")
    if any(
        point.x < calibration.x_min
        or point.x > calibration.x_max
        or point.y < calibration.y_min
        or point.y > calibration.y_max
        for point in source_points
    ):
        raise ApprovalError("manual curve points must be inside reviewed axis bounds")
    if source_points and (
        source_points[0].x != calibration.x_min or source_points[-1].x != calibration.x_max
    ):
        raise ApprovalError("manual curve points must cover the full reviewed X-axis domain")
    x_scale = _source_x_scale(spec)
    points = tuple(CurvePoint(x=point.x * x_scale, y=point.y) for point in source_points)
    variant = FaultTimeVoltageVariant(
        id=variant_id,
        selector=selector,
        x_axis=CurveAxis(
            quantity_kind=spec.x_quantity_kind,
            unit=spec.x_unit,
            scale=spec.x_scale,
            minimum=calibration.x_min * x_scale,
            maximum=calibration.x_max * x_scale,
        ),
        y_axis=CurveAxis(
            quantity_kind=spec.y_quantity_kind,
            unit=spec.y_unit,
            scale=spec.y_scale,
            minimum=calibration.y_min,
            maximum=calibration.y_max,
        ),
        points=points,
        segments=infer_curve_segments(points),
        applicability="manually reviewed",
        source=raw_figure.source,
        reviewed_artifact_sha256=_manual_reviewed_artifact_sha256(
            raw_figure, calibration_review.calibration_sha256
        ),
    )
    rules = tuple(rule for rule in draft.curves if rule.id == spec.semantic_id)
    if len(rules) > 1:
        raise ApprovalError("curve rule inventory is ambiguous")
    current = {member.id: member for member in rules[0].variants} if rules else {}
    current[variant.id] = variant
    order = tuple(
        f"{candidate.semantic_id}.{candidate.figure}.{index}"
        for recipe in _manual_recipes()
        for candidate in recipe.curves
        if candidate.semantic_id == spec.semantic_id
        for index, _selector in enumerate(candidate.variant_slots, start=1)
    )
    changed_rule = PiecewiseCurveRule(
        id=spec.semantic_id,
        variants=tuple(current[item] for item in order if item in current),
        source=rules[0].source if rules else raw_figure.source,
    )
    changed = draft.model_copy(
        update={
            "curves": tuple(
                changed_rule if rule.id == spec.semantic_id else rule for rule in draft.curves
            )
            if rules
            else (*draft.curves, changed_rule),
            "curve_variant_reviews": tuple(
                review for review in draft.curve_variant_reviews if review.variant_id != variant_id
            ),
            "manual_curve_variant_inputs": tuple(
                input
                for input in draft.manual_curve_variant_inputs
                if input.variant_id != variant_id
            )
            + (
                ManualCurveVariantInput(
                    variant_id=variant.id,
                    variant_sha256=canonical_model_sha256(variant),
                    source_artifact_sha256=variant.reviewed_artifact_sha256,
                    calibration_sha256=calibration_review.calibration_sha256,
                    input_origin=input_origin,
                ),
            ),
        }
    )
    return record_correction(
        draft,
        changed,
        actor=actor,
        notes=notes,
        reopen=_resolved_curve_items(draft, {variant_id}),
    )


def _variant(rule: PiecewiseCurveRule, variant_id: str) -> FaultTimeVoltageVariant:
    variant = next((item for item in rule.variants if item.id == variant_id), None)
    if variant is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    return variant


def review_curve_variant(
    draft: ImportedRuleDraft,
    variant_id: str,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record an exact manual review; review the aggregate after every member."""

    if not actor.strip() or not notes.strip():
        raise ApprovalError("curve review actor and notes are required")
    rule = next((rule for rule in draft.curves for v in rule.variants if v.id == variant_id), None)
    if rule is None:
        raise ValueError(f"unknown curve variant: {variant_id}")
    variant = _variant(rule, variant_id)
    spec, _selector = _manual_curve_slot(draft, variant_id)
    figure = _manual_figure(draft, spec)
    calibration = _manual_calibration(draft, figure)
    if variant.reviewed_artifact_sha256 != _manual_reviewed_artifact_sha256(
        figure, calibration.calibration_sha256
    ):
        raise ApprovalError("curve variant provenance is stale for reviewed calibration")
    inputs = tuple(
        input
        for input in draft.manual_curve_variant_inputs
        if (
            input.variant_id == variant.id
            and input.variant_sha256 == canonical_model_sha256(variant)
            and input.source_artifact_sha256 == variant.reviewed_artifact_sha256
            and input.calibration_sha256 == calibration.calibration_sha256
        )
    )
    if len(inputs) != 1:
        raise ApprovalError("curve variant lacks one exact manual input origin")
    review = CurveVariantReview(
        variant_id=variant.id,
        variant_sha256=canonical_model_sha256(variant),
        source_artifact_sha256=variant.reviewed_artifact_sha256,
        calibration_sha256=calibration.calibration_sha256,
        input_origin=inputs[0].input_origin,
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
    if any(item.review_item_sha256 == member_items[0].sha256 for item in draft.review_resolutions):
        raise ApprovalError("curve variant review item is already resolved")
    changed = draft.model_copy(
        update={
            "curve_variant_reviews": tuple(
                item for item in draft.curve_variant_reviews if item.variant_id != variant.id
            )
            + (review,)
        }
    )
    changed = record_correction(
        draft,
        changed,
        actor=actor,
        notes=f"record exact curve variant review: {notes}",
        resolve=member_items,
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


# --- reviewed clause facts ---------------------------------------------------------


def fact_set_sha256(facts: tuple[SupplyFact, ...]) -> str:
    """Digest of one route's authored fact set, so a completion record binds what it approved."""

    members = sorted(canonical_model_sha256(fact) for fact in facts)
    return hashlib.sha256("\n".join(members).encode("utf-8")).hexdigest()


def live_evidence_sha256(draft: ImportedRuleDraft, nodes: tuple[CitedNode, ...]) -> str | None:
    """One fact's evidence digest, recomputed from the draft's own current fragment nodes.

    ``None`` for a citation this draft cannot resolve, which no recorded digest can equal, so
    such a fact reads as stale rather than as silently current -- the same contract
    ``live_axis_evidence_sha256`` keeps for an axis position.
    """

    live: list[CitedNode] = []
    for cited in nodes:
        fragment = next(
            (item for item in draft.raw_clause_fragments if item.id == cited.fragment_id), None
        )
        node = (
            next((item for item in fragment.nodes if item.order == cited.node_order), None)
            if fragment is not None
            else None
        )
        if node is None:
            return None
        live.append(cited.model_copy(update={"node_sha256": canonical_model_sha256(node)}))
    return evidence_sha256(tuple(live))


#: One source statement's coverage anchor: which fragment, which node, and that node's content,
#: for every node the statement rests on. Route plus this set is the whole anchor -- amendment
#: A5-C -- and nothing about the values anybody proposed or authored enters it.
_StatementAnchor = frozenset[tuple[str, int, str]]


def _statement_anchor(nodes: tuple[CitedNode, ...]) -> _StatementAnchor:
    """The cited-evidence bundle a statement is anchored by.

    Deliberately **not** the sentence index: the clause-region slice widens the extracted regions
    and renumbers every sentence, which would silently orphan the coverage of statements nobody
    touched. And deliberately not the proposed or authored dimensions: a maintainer who reads the
    source, finds a suggestion wrong and authors corrected values must still have covered the
    statement they corrected, or exercising judgement would block completion for ever.

    This is the structural spelling of the same identity ``evidence_sha256`` digests, kept as a set
    here because coverage has to ask whether one statement's evidence is *among* a fact's citations,
    which a digest cannot answer.
    """

    return frozenset((node.fragment_id, node.node_order, node.node_sha256) for node in nodes)


def _statement_label(anchor: _StatementAnchor) -> str:
    """One uncovered statement as the reviewer is told about it, by the nodes it rests on."""

    orders = ", ".join(str(order) for _fragment, order, _digest in sorted(anchor))
    return f"the statement resting on clause node(s) {orders}"


def _dismissed_anchors(draft: ImportedRuleDraft, route: str) -> set[_StatementAnchor]:
    """The evidence identity of every statement this route's reviewer dismissed as out of scope."""

    return {
        _statement_anchor(item.node_references)
        for item in draft.clause_fact_dismissals
        if item.rule_route == route
    }


def _proposed_anchors(draft: ImportedRuleDraft, route: str) -> set[_StatementAnchor]:
    """The evidence identity of every statement this route's own drafts rest on.

    What a dismissal has to name one of. One reader for the guard and for the dismissal check, so a
    statement the guard counts as an obligation is exactly a statement the reviewer may dismiss.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        propose_supply_facts,
    )

    fragment = next(
        (item for item in draft.raw_clause_fragments if item.id == f"raw-{route}"), None
    )
    if fragment is None:
        return set()
    return {
        _statement_anchor(proposal.node_references)
        for proposal in propose_supply_facts(fragment, route)
    }


def clause_fact_statement_dismissed(
    draft: ImportedRuleDraft, route: str, nodes: tuple[CitedNode, ...]
) -> bool:
    """Whether this route's reviewer has dismissed the statement resting on exactly these nodes.

    The one reader a surface needs: the review dialog asks it of each draft so a dismissed sentence
    is shown as decided rather than as outstanding, and asks nothing about how the anchor is spelled.
    """

    return _statement_anchor(nodes) in _dismissed_anchors(draft, route)


def dismiss_clause_fact_statement(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    nodes: tuple[CitedNode, ...],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record that one proposed statement of a route states nothing that route models.

    The reviewed answer for a sentence a route's fact family cannot express: another rule's design
    basis, a determination this clause only refers to, a recommendation that is not normative. Such a
    statement's draft can never be closed by authoring anything, so without this the route's pane
    reads as permanently outstanding and completion is asserted over a list that always looks
    unfinished.

    It is deliberately not cheap, and these are the reasons why -- attributability and re-opening are
    the minimum, and three more come free:

    - it must name a statement **this route actually proposes**, so a route cannot be quietened by
      dismissing anchors nobody suggested;
    - its citations must match the fragment's **current** nodes, exactly as an authored statement's
      must, so a decision cannot be recorded against evidence that has already moved;
    - a statement an authored fact already covers cannot be dismissed, so one sentence never carries
      a reading *and* the claim that there was nothing to read;
    - and a route still needs at least one authored statement to be complete
      (``clause_fact_route_defect``), so no route can be certified by dismissing all of it.

    Clearing the guard still only **permits** completion (amendment A5): the maintainer's own
    assertion remains what completes a route, and a dismissal changes what the guard counts, never
    what completion means.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("clause fact actor and notes are required")
    anchor = _statement_anchor(nodes)
    label = _statement_label(anchor)
    if anchor not in _proposed_anchors(draft, rule_route):
        raise ValueError(f"{rule_route} proposes no statement resting on those nodes")
    for cited in nodes:
        fragment = next(
            (item for item in draft.raw_clause_fragments if item.id == cited.fragment_id), None
        )
        node = (
            None
            if fragment is None
            else next((item for item in fragment.nodes if item.order == cited.node_order), None)
        )
        if node is None or canonical_model_sha256(node) != cited.node_sha256:
            raise ValueError(
                f"citation does not match a current node: {cited.fragment_id} "
                f"node {cited.node_order}"
            )
    if anchor in _dismissed_anchors(draft, rule_route):
        raise ValueError(f"{rule_route} has already dismissed {label}")
    if any(
        anchor <= _statement_anchor(item.fact.node_references)
        for item in draft.clause_fact_reviews
        if item.rule_route == rule_route
    ):
        raise ValueError(f"{rule_route} has authored {label} rather than finding nothing in it")
    dismissal = ClauseFactDismissal(
        rule_route=rule_route,
        node_references=nodes,
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    changed = draft.model_copy(
        update={"clause_fact_dismissals": (*draft.clause_fact_dismissals, dismissal)}
    )
    return record_correction(
        draft, changed, actor=actor, notes=f"dismiss clause fact statement: {notes}"
    )


def retract_clause_fact_dismissal(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    nodes: tuple[CitedNode, ...],
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Withdraw one out-of-scope decision, putting its statement back among the obligations.

    Retractable for the reason an authored statement is: a reviewer who reads a sentence again and
    finds a statement of this route in it after all must be able to say so, and an audited
    withdrawal is how. Any completion for the route is left in place, where the returning obligation
    blocks it until the reviewer asserts completeness again -- never silently repaired.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("clause fact actor and notes are required")
    anchor = _statement_anchor(nodes)
    kept = tuple(
        item
        for item in draft.clause_fact_dismissals
        if not (item.rule_route == rule_route and _statement_anchor(item.node_references) == anchor)
    )
    if len(kept) == len(draft.clause_fact_dismissals):
        raise ValueError(f"{rule_route} has not dismissed {_statement_label(anchor)}")
    changed = draft.model_copy(update={"clause_fact_dismissals": kept})
    return record_correction(
        draft, changed, actor=actor, notes=f"retract clause fact dismissal: {notes}"
    )


def uncovered_clause_fact_statements(draft: ImportedRuleDraft, route: str) -> tuple[str, ...]:
    """Every known source statement of one route that no authored fact covers.

    The completion guard's lower bound on review (amendment A5): a route carrying a proposal whose
    source statement no authored fact covers cannot be completed. Empty is a *permission* to
    complete and never a completion -- completion stays the maintainer's own assertion that no
    additional statement was missed, which is why both this and the completion record are required.

    Coverage is per **anchor**, not per draft: several drafts of one evidence bundle are one
    obligation, because the anchor is the cited evidence and never the sentence index. A fact covers
    an anchor when it cites every node that anchor names -- which is what lets a statement completing
    a list's opener cite the opener as well and still cover its own bullet -- and each fact covers at
    most one anchor, so one authored fact can never mark two distinct source statements as reviewed.

    A statement the reviewer has **dismissed as stating nothing this route models** is not an
    obligation either -- see ``dismiss_clause_fact_statement``. Subtracted from the obligations
    rather than accepted as coverage, because the two are different reviewed answers: one says a
    statement was read into a fact, the other says there was no statement of this route's kind to
    read. Both are decisions, and neither is a filter: the dismissal is anchored on the same evidence
    identity, so a sentence whose text moves becomes an obligation again by itself.

    Context-only nodes are not obligations, and this needs no branch of its own for it: a sentence
    that only scopes the ones after it yields no proposal at all (amendment A4, in
    ``propose_clause_facts``), so no anchor of its own ever reaches this function. The filter that
    used to sit here read the same stems the proposer reads and is gone with the drafts it skipped
    -- one enforcement point rather than two that can disagree.

    Knowingly partial, and knowingly so by design: it cannot catch a statement no proposal ever
    suggested, and it cannot tell one statement resting on two normative nodes from two statements
    resting on one each. Both are why the maintainer's assertion remains the definition of
    completion rather than being replaced by this count.

    ponytail: greedy assignment, smallest citation first, rather than a bipartite matching. It can
    report an anchor uncovered where a cleverer pairing exists, which errs towards blocking
    completion; upgrade to a real matching if a route ever carries facts whose citations overlap in
    a way this mis-pairs.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        propose_supply_facts,
    )

    fragment = next(
        (item for item in draft.raw_clause_fragments if item.id == f"raw-{route}"), None
    )
    if fragment is None:
        return ()
    obligations: set[_StatementAnchor] = {
        _statement_anchor(proposal.node_references)
        for proposal in propose_supply_facts(fragment, route)
    } - _dismissed_anchors(draft, route)
    unused = [
        _statement_anchor(item.fact.node_references)
        for item in draft.clause_fact_reviews
        if item.rule_route == route
    ]
    uncovered: list[str] = []
    for anchor in sorted(obligations, key=sorted):
        covering = [cited for cited in unused if anchor <= cited]
        if not covering:
            uncovered.append(_statement_label(anchor))
            continue
        unused.remove(min(covering, key=len))
    return tuple(uncovered)


def _unresolvable_rule_reference(fact: SupplyFact) -> str | None:
    """Why one statement's deferral to another rule cannot be followed, or ``None``.

    A ``RouteIdentifier`` dimension names a rule instead of restating its content, and nothing
    consumes those references yet -- that is a disclosed gap awaiting #53C. So until this, a mistyped
    id was recorded silently, covered by the fact digest and by the route's completion record, and
    would have surfaced only when a consumer first tried to follow it, long after the review that was
    supposed to have checked it. Refused at authoring instead, beside the other identity defects.

    The reference dimensions come from ``fact_dimensions``, the one place a dimension's kind is
    reported, so a field gaining or losing the marker changes this with it.
    """

    from insulation_coordination.rules.importer.clause_fact_proposals import fact_dimensions
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        declared_rule_references,
    )

    declared = declared_rule_references()
    statement_kind: str | None = getattr(fact, "statement_kind", "") or None
    for name, kind, _options in fact_dimensions(fact.fact_kind, statement_kind):
        if kind != "route_reference":
            continue
        value = getattr(fact, name)
        if value not in declared:
            return f"states {name} {value}, which names no rule this recipe declares"
    return None


def clause_fact_defect(
    rule_route: str,
    fact: SupplyFact,
    existing: tuple[SupplyFact, ...] = (),
) -> str | None:
    """Why one fact cannot stand for one route, or ``None`` if it can.

    Identity rather than evidence, the half ``axis_review_is_current`` keeps for an axis position
    and the digests alone cannot: the route must be one the recipe declares, the fact must belong
    to the family that route's clause states, it must cite that route's own fragment, where the
    route determines a dimension structurally -- a concrete ``supply_kind``, or the isolation the
    clause is scoped by -- the fact must not name the contradicting value, and a dimension that
    defers to another rule must name one the recipe declares. Without all of them a
    fact that cannot express a route's branches -- or one resting entirely on another clause, or one
    that states the wrong supply or the wrong barrier for its route -- certifies the route as
    reviewed, and reprinting the cited clause blocks a route whose rule it never stated.

    Citing the route's own fragment is required *as well as*, never instead of: a statement that
    genuinely rests on a second fragment may cite it too. The ``supply_kind`` check reads
    ``SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE``, the recipe's own declaration of which concrete kind each
    such route states. Every field spelling it names one concrete kind -- it is the one dimension of
    those families that stayed scalar when the rest became scopes, because the route settles it
    rather than the statement -- so there is no unrestricted reading of it to let through. The
    isolation check reads
    ``SUPPLY_FACT_ISOLATION_BY_ROUTE`` the same way, through the one dimension a barrier statement
    still spells: a statement naming the connection kind the other scope addresses is refused, which
    is what makes a positive-isolation reading of the unisolated clause unauthorable rather than
    merely undocumented. Authoring raises on a defect and the approval gate blocks on one, so a
    hand-built draft cannot bypass what authoring enforces.

    ``existing`` is the route's other authored statements, and a fact repeating one of their
    readings is the fifth defect. Without it, pressing Author twice on one draft recorded the same
    reading under two indices, silently, and a reviewer could reach statement 10 without noticing
    they had authored one reading ten times -- a fact set that certifies a route with far less
    review than its size claims. A statement at an index ``existing`` already holds is the
    sanctioned replace path and is never compared against itself, so replacing stays free.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        SUPPLY_FACT_FAMILY_BY_ROUTE,
        SUPPLY_FACT_ISOLATION_BY_ROUTE,
        SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE,
    )

    family = SUPPLY_FACT_FAMILY_BY_ROUTE.get(rule_route)
    if family is None:
        return f"is authored on an undeclared rule route: {rule_route}"
    if fact.fact_kind != family:
        return f"is a {fact.fact_kind} fact where {rule_route} states {family}"
    if not any(cited.fragment_id == f"raw-{rule_route}" for cited in fact.node_references):
        return f"cites no node of its own clause fragment raw-{rule_route}"
    expected_supply_kind = SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE.get(rule_route)
    fact_supply_kind = getattr(fact, "supply_kind", None)
    if (
        expected_supply_kind is not None
        and fact_supply_kind is not None
        and fact_supply_kind != expected_supply_kind
    ):
        return f"states supply_kind {fact_supply_kind} where {rule_route} is {expected_supply_kind}"
    expected_isolation = SUPPLY_FACT_ISOLATION_BY_ROUTE.get(rule_route)
    connection = getattr(fact, "downstream_connection_kind", None)
    if expected_isolation is not None and connection is not None:
        expected_connection = (
            "verified_galvanic_isolation" if expected_isolation else "no_isolation"
        )
        if connection != expected_connection:
            return (
                f"states downstream_connection_kind {connection} where {rule_route} is scoped to "
                f"{expected_connection}"
            )
    unresolvable = _unresolvable_rule_reference(fact)
    if unresolvable is not None:
        return unresolvable
    duplicate = next(
        (
            other.statement_index
            for other in existing
            if other.statement_index != fact.statement_index
            and same_clause_fact_reading(other, fact)
        ),
        None,
    )
    if duplicate is not None:
        return f"repeats the reading already authored as statement {duplicate}"
    return None


def clause_fact_route_defect(draft: ImportedRuleDraft, route: str) -> str | None:
    """Why one route's authored clause facts are not currently complete, or ``None`` if they are.

    The approval gate and the clause fact review dialog must agree exactly on what blocks a
    route, so both call this instead of each re-deriving the comparison -- the way
    ``axis_review_is_current`` keeps the gate and the axis review dialog aligned on one axis
    position. Every check reads the draft's own live state; no caller can supply a stored digest
    in its place.

    Identity before evidence, the order ``clause_fact_defect`` keeps for one fact: a fact of the
    wrong family, or one resting entirely on another clause, has perfectly current digests. A
    route this draft never extracted returns ``None`` here, the same as a route with nothing
    wrong -- callers scope to fragments the draft actually carries, the way
    ``missing_required_content`` finds the missing fragment.
    """

    fragment = next(
        (item for item in draft.raw_clause_fragments if item.id == f"raw-{route}"), None
    )
    if fragment is None:
        return None
    reviews = tuple(item for item in draft.clause_fact_reviews if item.rule_route == route)
    completions = tuple(item for item in draft.clause_fact_completions if item.rule_route == route)
    authored = tuple(item.fact for item in reviews)
    defects = tuple(
        defect
        for item in reviews
        if (defect := clause_fact_defect(route, item.fact, authored)) is not None
    )
    if not reviews:
        return "carries no authored clause fact"
    if defects:
        return f"has a fact that {defects[0]}"
    # As ``axis_review_is_current`` verifies a review's ``proposal_sha256``: a written digest
    # nothing reads is a digest a second writer can get wrong unnoticed.
    if any(item.fact_sha256 != canonical_model_sha256(item.fact) for item in reviews):
        return "has a review whose fact hash is not its fact's"
    # The lower bound before the assertion, never instead of it: a route clears this *and* carries
    # its own completion record, because no count of consumed proposals is the maintainer saying
    # nothing further was missed.
    uncovered = uncovered_clause_fact_statements(draft, route)
    if uncovered:
        return f"leaves a known statement unauthored: {'; '.join(uncovered)}"
    if len(completions) != 1:
        return "lacks one exact fact-set completion record"
    if (
        completions[0].fragment_id != fragment.id
        or completions[0].fragment_sha256 != fragment.raw_sha256
    ):
        return "was completed against a superseded or foreign fragment"
    if completions[0].fact_set_sha256 != fact_set_sha256(tuple(item.fact for item in reviews)):
        return "was completed against a different fact set"
    if any(
        item.evidence_sha256 != live_evidence_sha256(draft, item.fact.node_references)
        for item in reviews
    ):
        return "has a fact whose cited evidence has moved"
    return None


def author_clause_fact(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    fact: SupplyFact,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record one maintainer-authored normative statement for a rule route.

    Nothing proposes a statement: the reviewer reads the private fragment and authors it. The
    review binds the fact's own hash and a digest of exactly the nodes it cites.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("clause fact actor and notes are required")
    defect = clause_fact_defect(
        rule_route,
        fact,
        tuple(item.fact for item in draft.clause_fact_reviews if item.rule_route == rule_route),
    )
    if defect is not None:
        raise ValueError(f"clause fact {defect}")
    for cited in fact.node_references:
        fragment = next(
            (item for item in draft.raw_clause_fragments if item.id == cited.fragment_id), None
        )
        if fragment is None:
            raise ValueError(f"unknown fragment cited: {cited.fragment_id}")
        node = next((node for node in fragment.nodes if node.order == cited.node_order), None)
        if node is None or canonical_model_sha256(node) != cited.node_sha256:
            raise ValueError(
                f"citation does not match a current node: {cited.fragment_id} "
                f"node {cited.node_order}"
            )
    review = ClauseFactReview(
        rule_route=rule_route,
        statement_index=fact.statement_index,
        fact=fact,
        fact_sha256=canonical_model_sha256(fact),
        evidence_sha256=evidence_sha256(fact.node_references),
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(
        item
        for item in draft.clause_fact_reviews
        if not (item.rule_route == rule_route and item.statement_index == fact.statement_index)
    )
    changed = draft.model_copy(update={"clause_fact_reviews": (*kept, review)})
    return record_correction(draft, changed, actor=actor, notes=f"author clause fact: {notes}")


def retract_clause_fact(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    statement_index: int,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Remove one authored statement from a route's reviewed fact set.

    The statement must exist: retracting an unknown one would append an audited correction
    that corrected nothing. Any completion for the route is left in place, where the changed
    fact-set digest makes it stale -- completeness must be re-asserted by the reviewer, never
    silently repaired by the deletion that invalidated it.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("clause fact actor and notes are required")
    kept = tuple(
        item
        for item in draft.clause_fact_reviews
        if not (item.rule_route == rule_route and item.statement_index == statement_index)
    )
    if len(kept) == len(draft.clause_fact_reviews):
        raise ValueError(f"{rule_route} has no authored statement {statement_index}")
    changed = draft.model_copy(update={"clause_fact_reviews": kept})
    return record_correction(draft, changed, actor=actor, notes=f"retract clause fact: {notes}")


def record_fact_completion(
    draft: ImportedRuleDraft,
    *,
    rule_route: str,
    fragment_id: str,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Assert that one route's fact set is complete for the current fragment.

    The fragment must be the route's own. Completion is what binds a fragment hash to a route, so
    naming any other fragment would bind the route to a document region that does not state it.

    Refused while a known statement of the clause is unauthored (amendment A5): a route whose
    fragment carries several normative statements could previously be completed with one authored,
    because nothing compared the authored set against anything. Clearing that guard **permits** this
    assertion and does not constitute it -- this record stays the maintainer's own statement that no
    *additional* statement was missed, which is a claim no proposal count can make on their behalf.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("completion actor and notes are required")
    if fragment_id != f"raw-{rule_route}":
        raise ValueError(f"{rule_route} completes against raw-{rule_route}, not {fragment_id}")
    fragment = next((item for item in draft.raw_clause_fragments if item.id == fragment_id), None)
    if fragment is None:
        raise ValueError(f"unknown fragment: {fragment_id}")
    facts = tuple(item.fact for item in draft.clause_fact_reviews if item.rule_route == rule_route)
    if not facts:
        raise ApprovalError("a route with no authored facts cannot be complete")
    uncovered = uncovered_clause_fact_statements(draft, rule_route)
    if uncovered:
        raise ApprovalError(
            f"{rule_route} cannot be complete while a known statement of its clause is "
            f"unauthored: {'; '.join(uncovered)}"
        )
    completion = ClauseFactCompletion(
        rule_route=rule_route,
        fragment_id=fragment_id,
        fragment_sha256=fragment.raw_sha256,
        fact_set_sha256=fact_set_sha256(facts),
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(item for item in draft.clause_fact_completions if item.rule_route != rule_route)
    changed = draft.model_copy(update={"clause_fact_completions": (*kept, completion)})
    return record_correction(
        draft, changed, actor=actor, notes=f"record clause fact completion: {notes}"
    )


class ClauseFactResolutionError(RulePackageError):
    """A route's reviewed facts are missing, incomplete or stale."""


def resolve_confirmed_clause_facts(
    spec: ClauseAuditSpec,
    draft: ImportedRuleDraft,
) -> ConfirmedFacts:
    """Current reviewed facts for every route one clause spec's rules rest on, or an exception.

    Resolution owns every refusal so a projector receives a complete context and never inspects
    review state itself. A route no fact family is declared for resolves to nothing rather than
    refusing -- every clause outside the supply set, and the guidance route a supply clause also
    projects, keeps its authority in its recipe -- the way ``resolve_confirmed_axis_selectors``
    returns an empty result for a spec declaring no axis selectors.

    Each route is resolved against its own fragment rather than against one passed in: a rule two
    subclauses state between them has one evidence scope per subclause, and each scope's
    completion binds the fragment of the clause that states it.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        LEGACY_BRANCH_AUTHORITY_RULE_IDS,
        SUPPLY_FACT_FAMILY_BY_ROUTE,
    )

    fragments = {item.id: item for item in draft.raw_clause_fragments}
    by_route: dict[str, tuple[SupplyFact, ...]] = {}
    for route in (
        *(spec.projected_rule_ids or (spec.semantic_id,)),
        *spec.evidence_clause_ids,
    ):
        if route not in SUPPLY_FACT_FAMILY_BY_ROUTE or route in LEGACY_BRANCH_AUTHORITY_RULE_IDS:
            continue
        fragment = fragments.get(f"raw-{route}")
        if fragment is None:
            raise ClauseFactResolutionError(f"{route} has no extracted fragment")
        reviews = sorted(
            (item for item in draft.clause_fact_reviews if item.rule_route == route),
            key=lambda item: item.statement_index,
        )
        if not reviews:
            raise ClauseFactResolutionError(f"{route} has no authored facts")
        # Identity before evidence, the order the approval gate keeps, and through the same
        # function the authoring API refuses on: resolution must not accept a fact
        # ``author_clause_fact`` would have rejected, and a fact of the wrong family or one
        # resting entirely on another clause has perfectly current digests.
        authored = tuple(item.fact for item in reviews)
        for review in reviews:
            defect = clause_fact_defect(route, review.fact, authored)
            if defect is not None:
                raise ClauseFactResolutionError(
                    f"{route} statement {review.statement_index} {defect}"
                )
            # Projection runs before approval, so a review whose recorded hash no longer matches
            # the fact beside it would project a rule and only be caught at the gate. Resolution
            # owns every refusal, this one included.
            if review.fact_sha256 != canonical_model_sha256(review.fact):
                raise ClauseFactResolutionError(
                    f"{route} statement {review.statement_index} carries a review whose recorded "
                    f"hash is not its fact"
                )
        facts = tuple(review.fact for review in reviews)
        completion = next(
            (item for item in draft.clause_fact_completions if item.rule_route == route), None
        )
        if completion is None:
            raise ClauseFactResolutionError(f"{route} has no completion record")
        # Route resolution is fragment-granular even though review invalidation below is
        # node-granular, and deliberately so: a fragment that gained or lost a node may have
        # gained or lost a normative statement, so completeness has to be re-asserted rather
        # than inferred from the nodes that survived.
        if completion.fragment_sha256 != fragment.raw_sha256:
            raise ClauseFactResolutionError(f"{route} completion is bound to an older fragment")
        if completion.fact_set_sha256 != fact_set_sha256(facts):
            raise ClauseFactResolutionError(f"{route} completion predates its current fact set")
        # Against the draft's own live nodes, never against the citations stored inside the fact:
        # those are what the recorded digest was computed from, so comparing the two could only
        # catch a hand-edited review and never a node this draft has since moved or corrected.
        for review in reviews:
            if review.evidence_sha256 != live_evidence_sha256(draft, review.fact.node_references):
                raise ClauseFactResolutionError(
                    f"{route} statement {review.statement_index} cites evidence that has moved"
                )
        by_route[route] = facts
    return ConfirmedFacts(by_route=by_route)


class AxisResolutionError(RulePackageError):
    """A grid's reviewed axis selectors are missing, duplicated, stale or of the wrong kind."""


def live_axis_evidence_sha256(
    draft: ImportedRuleDraft, grid_id: str, axis: str, index: int
) -> str | None:
    """One axis position's evidence digest, recomputed from the draft's own live grid.

    Resolves ``grid_id`` to its grid and its declaring spec the way the approval gate does.
    Nothing re-derives ``axis_selector_proposals`` after a correction, so the digest stored on
    a proposal is the pre-correction one: every caller that has to decide whether a review is
    current reads the live digest through here instead. ``None`` for a grid or a spec this
    draft cannot resolve, which no recorded digest can equal, so such a position reads as
    unreviewed rather than as silently current.
    """

    from insulation_coordination.rules.importer.recipes import RECIPES

    grid = next((item for item in draft.raw_grids if item.id == grid_id), None)
    spec = next(
        (
            item
            for recipe in RECIPES
            for item in recipe.tables
            if item.axis_selectors and f"raw-{item.semantic_id}" == grid_id
        ),
        None,
    )
    if grid is None or spec is None:
        return None
    return axis_evidence_sha256(grid, spec, axis, index)


def axis_review_is_current(
    review: AxisSelectorReview,
    proposal: AxisSelectorProposal,
    draft: ImportedRuleDraft,
) -> bool:
    """Whether one review is still bound to its proposal's identity and current evidence.

    The resolver, the approval gate and the review UI must agree exactly on what counts as
    current, so all three call this instead of each repeating the comparison. The evidence
    digest is always the live one; no caller can supply a stored value. What keeps a header
    cell out of a correction's reach is ``correctable_coordinates``, which filters to
    ``cell.role == "data"`` -- not ``_require_safe_raw_grid_correction``, which freezes a
    cell's raw text, role, source and coordinates but permits its value, qualifier, suffix,
    footnotes, blank semantics and reference token on any cell, header included.
    """

    return (
        review.grid_id == proposal.grid_id
        and review.axis == proposal.axis
        and review.index == proposal.index
        and review.proposal_sha256 == proposal.proposal_sha256
        and review.evidence_sha256
        == live_axis_evidence_sha256(draft, proposal.grid_id, proposal.axis, proposal.index)
    )


def _require_distinct_selectors(
    grid_id: str, axis: str, selectors: dict[int, AxisSelector]
) -> None:
    """Refuse two positions of one axis confirmed as the same selector.

    ``evaluate_decision`` returns the first matcher that fits, so two positions resolving to
    equal selectors would produce duplicate matchers and silently serve whichever comes
    first, with no error anywhere. The old positional contract made this impossible by
    construction; resolution must refuse it explicitly now. Keyed on ``grid_id`` rather than a
    ``TableAuditSpec`` so ``review_axis_selector`` can run the same check against whatever
    positions are already reviewed, without needing the live grid resolution requires.
    """

    seen: dict[str, int] = {}
    for index in sorted(selectors):
        digest = selector_sha256(selectors[index])
        if digest in seen:
            raise AxisResolutionError(
                f"{grid_id} {axis} positions {seen[digest]} and {index} confirm the same selector"
            )
        seen[digest] = index


def resolve_confirmed_axis_selectors(
    spec: TableAuditSpec,
    grid: RawGrid,
    draft: ImportedRuleDraft,
) -> ConfirmedAxes:
    """Reviewed axis facts for one grid, or an empty result for a spec that declares none.

    Resolution owns every refusal, so a projector receives either a complete context or an
    exception. A projector never inspects review state itself.
    """

    if not spec.axis_selectors:
        return ConfirmedAxes()
    rows: dict[int, AxisSelector] = {}
    columns: dict[int, AxisSelector] = {}
    for axis_spec in spec.axis_selectors:
        for index in axis_positions(spec, axis_spec, grid):
            proposal = next(
                (
                    item
                    for item in draft.axis_selector_proposals
                    if item.grid_id == grid.id
                    and item.axis == axis_spec.axis
                    and item.index == index
                ),
                None,
            )
            if proposal is None:
                raise AxisResolutionError(
                    f"{grid.id} {axis_spec.axis} position {index} has no axis proposal"
                )
            exact = [
                review
                for review in draft.axis_selector_reviews
                if axis_review_is_current(review, proposal, draft)
            ]
            if len(exact) != 1:
                raise AxisResolutionError(
                    f"{grid.id} {axis_spec.axis} position {index} needs exactly one current "
                    f"review, found {len(exact)}"
                )
            confirmed = exact[0].confirmed_selector
            if confirmed.selector_kind != axis_spec.selector_kind:
                raise AxisResolutionError(
                    f"{grid.id} {axis_spec.axis} position {index} confirmed a "
                    f"{confirmed.selector_kind} selector but the axis declares "
                    f"{axis_spec.selector_kind}"
                )
            target = rows if axis_spec.axis == "row" else columns
            target[index] = confirmed
    _require_distinct_selectors(grid.id, "row", rows)
    _require_distinct_selectors(grid.id, "column", columns)
    return ConfirmedAxes(rows=rows, columns=columns)


def review_axis_selector(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    axis: str,
    index: int,
    selector: AxisSelector,
    actor: str,
    notes: str,
) -> ImportedRuleDraft:
    """Record one exact axis review: confirm, correct, or supply where nothing was proposed.

    The review binds the current proposal hash and the current per-position evidence hash, so
    a change to either drops it and re-opens review. Also refuses a selector that would
    duplicate another position's already-confirmed selector on the same axis of the same grid,
    using the same distinctness check resolution enforces -- so the reviewer sees the refusal
    at the moment of the mistake rather than only once the whole axis is complete.
    """

    if not actor.strip() or not notes.strip():
        raise ApprovalError("axis review actor and notes are required")
    proposal = next(
        (
            item
            for item in draft.axis_selector_proposals
            if item.grid_id == grid_id and item.axis == axis and item.index == index
        ),
        None,
    )
    if proposal is None:
        raise ValueError(f"unknown axis position: {grid_id} {axis} {index}")
    if selector.selector_kind != proposal.selector_kind:
        # Refused here rather than only at resolution, for the same reason the distinctness
        # check moved: the reviewer sees the mistake at the moment of it. It also keeps every
        # confirmed selector on a position readable as the kind its axis declares, which the
        # review dialog relies on to pre-fill its editor.
        raise AxisResolutionError(
            f"{grid_id} {axis} {index} declares {proposal.selector_kind} selectors, "
            f"not {selector.selector_kind}"
        )
    # The live digest, never the proposal's stored one: a correction to this position's own
    # evidence leaves that stored value behind, and a review carrying it could never be
    # current again -- so no review of this position could ever clear its approval blocker.
    evidence = live_axis_evidence_sha256(draft, grid_id, proposal.axis, index)
    if evidence is None:
        raise AxisResolutionError(
            f"{grid_id} {axis} {index} has no live grid and spec to read its evidence from"
        )
    review = AxisSelectorReview(
        grid_id=grid_id,
        axis=proposal.axis,
        index=index,
        proposal_sha256=proposal.proposal_sha256,
        evidence_sha256=evidence,
        confirmed_selector=selector,
        actor=actor.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    kept = tuple(
        item
        for item in draft.axis_selector_reviews
        if not (item.grid_id == grid_id and item.axis == axis and item.index == index)
    )
    changed = draft.model_copy(update={"axis_selector_reviews": (*kept, review)})
    # Only the reviews resolution would actually use reserve a selector. A stale one -- this
    # axis has another position whose own evidence changed -- must not refuse the position
    # that legitimately reads its selector, which nothing could then ever confirm.
    proposals = {
        (item.axis, item.index): item
        for item in changed.axis_selector_proposals
        if item.grid_id == grid_id
    }
    _require_distinct_selectors(
        grid_id,
        axis,
        {
            item.index: item.confirmed_selector
            for item in changed.axis_selector_reviews
            if item.grid_id == grid_id
            and item.axis == axis
            and (item.axis, item.index) in proposals
            and axis_review_is_current(item, proposals[item.axis, item.index], changed)
        },
    )
    return record_correction(
        draft,
        changed,
        actor=actor,
        notes=f"record exact axis selector review: {notes}",
    )
