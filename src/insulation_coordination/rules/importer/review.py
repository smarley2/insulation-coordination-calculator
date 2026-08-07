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
import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from insulation_coordination.domain.rules import (
    CompatibilityMapping,
    DraftRulePackage,
    Formula,
    LinearInterpolate,
    Literal,
    Lookup,
    Parameter,
    ParameterSet,
    SourceReference,
    Table,
    Variable,
)
from insulation_coordination.domain.rules import Expression as RuleExpression
from insulation_coordination.rules.importer.approval import record_correction
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    ImportReviewItem,
    RawGrid,
    RawGridCell,
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
        "review_items": payload["review_items"],
        "raw_grids": payload["raw_grids"],
        "extracted_equations": payload["extracted_equations"],
    }
    canonical = json.dumps(
        stable,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


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
        standard=identity.standard,
        edition=identity.edition,
        clause=spec.clause,
        table=spec.table,
        figure=spec.figure,
        note=f"PDF page {spec.page_number}",
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
            standard=identity.standard,
            edition=identity.edition,
            clause=spec.clause,
            table=spec.table,
            figure=spec.figure,
            note=f"PDF page {spec.page_number}",
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
        row, column = item.semantic_id.rsplit(":", 2)[-2:]
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
        if cell.role == "data" and ((cell.row, cell.column) in flagged or cell.value is not None)
    }


def _corrected_cells(
    grid: RawGrid,
    corrections: Mapping[tuple[int, int], Decimal],
    flagged: set[tuple[int, int]],
) -> tuple[RawGridCell, ...]:
    """Apply retyped values and clear the parser's flag on every flagged cell."""
    correctable = correctable_coordinates(grid, flagged)
    unexpected = set(corrections) - correctable
    if unexpected:
        raise ValueError(f"raw grid cell is not correctable: {sorted(unexpected)!r}")
    cells: list[RawGridCell] = []
    for cell in grid.cells:
        coordinate = (cell.row, cell.column)
        if coordinate not in flagged and coordinate not in corrections:
            cells.append(cell)
            continue
        value = corrections.get(coordinate, cell.value)
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


def accept_raw_table(
    draft: ImportedRuleDraft,
    *,
    grid_id: str,
    corrections: Mapping[tuple[int, int], Decimal],
    actor: str,
    notes: str,
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
    changed_grid = grid.model_copy(
        update={"cells": _corrected_cells(grid, corrections, coordinates)}
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
    corrections: Mapping[tuple[int, int], Decimal],
    actor: str,
    notes: str,
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
    changed_grid = grid.model_copy(
        update={"cells": _corrected_cells(grid, corrections, flagged_coordinates(pending))}
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

    identities = {i.recipe_id: i for i in draft.source_identities}
    grids = {g.id: g for g in draft.raw_grids}
    equations = {equation.id: equation for equation in draft.extracted_equations}

    tables: dict[str, Table] = {}
    formulas: dict[str, Formula] = {}
    mappings: dict[str, CompatibilityMapping] = {}

    for recipe in RECIPES:
        identity = identities[recipe.id]
        for table_spec in recipe.tables:
            tables[table_spec.semantic_id] = project_table(
                identity, table_spec, grids[f"raw-{table_spec.semantic_id}"]
            )
        for formula_spec in recipe.formulas:
            formulas[formula_spec.semantic_id] = project_formula(identity, formula_spec, equations)
        for mapping_spec in recipe.mappings:
            mappings[mapping_spec.id] = project_mapping(identity, mapping_spec)

    changed = draft.model_copy(
        update={
            "tables": tuple(tables.values()),
            "formulas": tuple(formulas.values()),
            "mappings": tuple(mappings.values()),
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
        for field in ("standard", "edition", "clause", "table", "figure")
    )


def required_content_report(draft: ImportedRuleDraft) -> tuple[RequiredContentStatus, ...]:
    """Required tables/formulas/mappings and whether typed content is present."""
    from insulation_coordination.rules.importer.recipes import RECIPES

    table_ids = {table.id: table for table in draft.tables}
    formula_ids = {formula.id: formula for formula in draft.formulas}
    mapping_ids = {mapping.id: mapping for mapping in draft.mappings}

    statuses: list[RequiredContentStatus] = []
    for recipe in RECIPES:
        for table_spec in recipe.tables:
            expected = SourceReference(
                standard=recipe.standard,
                edition=recipe.edition,
                clause=table_spec.clause,
                table=table_spec.source_table,
                note=f"PDF page {table_spec.page_number}",
            )
            table = table_ids.get(table_spec.semantic_id)
            present = table is not None and _matches(table.source, expected)
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
                standard=recipe.standard,
                edition=recipe.edition,
                clause=formula_spec.clause,
                table=formula_spec.table,
                figure=formula_spec.figure,
                note=f"PDF page {formula_spec.page_number}",
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
                standard=recipe.standard,
                edition=recipe.edition,
                clause=mapping_spec.clause,
                table=mapping_spec.table,
                figure=mapping_spec.figure,
                note=f"PDF page {mapping_spec.page_number}",
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
