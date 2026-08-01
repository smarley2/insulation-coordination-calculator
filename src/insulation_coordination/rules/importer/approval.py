from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    DraftRulePackage,
    Expression,
    RulePackage,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.archive import _archive_bytes
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    _content_digest,
)
from insulation_coordination.rules.importer.identify import StandardRecipe
from insulation_coordination.rules.validation import validate_rule_package

_EXPECTED_DRAFT_FAILURES = {
    "approval",
    "approval_record",
    "compatibility",
    "checksums",
    "package_digest",
}


class ApprovalError(RulePackageError):
    """A draft has not satisfied every non-bypassable approval gate."""


def _source_matches(actual: SourceReference, expected: SourceReference) -> bool:
    return all(
        getattr(actual, field) == getattr(expected, field)
        for field in ("standard", "edition", "clause", "table", "figure")
    )


def _review_resolution_exists(item: ImportReviewItem, changed: ImportedRuleDraft) -> bool:
    if item.kind == "table":
        return any(
            grid.id == f"raw-{item.semantic_id}" and _source_matches(grid.source, item.source)
            for grid in changed.raw_grids
        )
    if item.kind == "formula":
        return any(
            equation.id == item.semantic_id
            and equation.parse_status == "parsed"
            and _source_matches(equation.source, item.source)
            for equation in changed.extracted_equations
        ) or any(
            spec.semantic_id == item.semantic_id
            for recipe in _recipes()
            for spec in recipe.formulas
            if not spec.extract_from_pdf
        )
    if item.kind == "mapping":
        return any(spec.id == item.semantic_id for recipe in _recipes() for spec in recipe.mappings)
    return any(
        f"{grid.id}:{cell.row}:{cell.column}" == item.semantic_id
        and _source_matches(cell.source, item.source)
        and cell.value is not None
        and cell.parse_status == "numeric"
        for grid in changed.raw_grids
        for cell in grid.cells
    )


def _recipes() -> tuple[StandardRecipe, ...]:
    from insulation_coordination.rules.importer.recipes import RECIPES

    return RECIPES


def _changed_tokens(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
) -> tuple[str, ...]:
    tokens: list[str] = []
    for label, before_items, after_items in (
        ("table", original.tables, changed.tables),
        ("formula", original.formulas, changed.formulas),
        ("mapping", original.mappings, changed.mappings),
    ):
        before = {item.id: item for item in before_items}
        after = {item.id: item for item in after_items}
        tokens.extend(
            f"{label}:{item_id}"
            for item_id in sorted(set(before) | set(after))
            if before.get(item_id) != after.get(item_id)
        )
    before_grids = {grid.id: grid for grid in original.raw_grids}
    after_grids = {grid.id: grid for grid in changed.raw_grids}
    tokens.extend(
        f"raw-grid:{grid_id}"
        for grid_id in sorted(set(before_grids) | set(after_grids))
        if before_grids.get(grid_id) != after_grids.get(grid_id)
    )
    before_equations = {item.id: item for item in original.extracted_equations}
    after_equations = {item.id: item for item in changed.extracted_equations}
    tokens.extend(
        f"equation:{equation_id}"
        for equation_id in sorted(set(before_equations) | set(after_equations))
        if before_equations.get(equation_id) != after_equations.get(equation_id)
    )
    return tuple(tokens)


def _require_safe_raw_grid_correction(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
) -> None:
    before_grids = {grid.id: grid for grid in original.raw_grids}
    after_grids = {grid.id: grid for grid in changed.raw_grids}
    if set(before_grids) != set(after_grids):
        raise ApprovalError("a correction cannot add or remove extracted raw grids")
    for grid_id, before in before_grids.items():
        after = after_grids[grid_id]
        if (
            before.rows,
            before.columns,
            before.target_unit,
            before.segments,
            before.source,
        ) != (
            after.rows,
            after.columns,
            after.target_unit,
            after.segments,
            after.source,
        ):
            raise ApprovalError("a correction cannot rewrite raw grid structure")
        before_cells = {(cell.row, cell.column): cell for cell in before.cells}
        after_cells = {(cell.row, cell.column): cell for cell in after.cells}
        if set(before_cells) != set(after_cells):
            raise ApprovalError("a correction cannot add or remove raw grid cells")
        if any(
            before_cells[key].raw_text != after_cells[key].raw_text
            or before_cells[key].source != after_cells[key].source
            or before_cells[key].role != after_cells[key].role
            or before_cells[key].logical_row != after_cells[key].logical_row
            or before_cells[key].logical_column != after_cells[key].logical_column
            for key in before_cells
        ):
            raise ApprovalError("a correction cannot rewrite extracted raw text or source")


def _require_safe_equation_correction(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
) -> None:
    before = {equation.id: equation for equation in original.extracted_equations}
    after = {equation.id: equation for equation in changed.extracted_equations}
    if set(before) != set(after):
        raise ApprovalError("a correction cannot add or remove extracted equations")
    if any(
        before[equation_id].raw_text != after[equation_id].raw_text
        or before[equation_id].source != after[equation_id].source
        for equation_id in before
    ):
        raise ApprovalError("a correction cannot rewrite extracted equation text or source")


def _require_valid_review_resolutions(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
    resolve: tuple[ImportReviewItem, ...],
    *,
    actor: str,
    notes: str,
    recorded_at: datetime,
) -> tuple[ImportReviewResolution, ...]:
    inventory = {item.sha256: item for item in original.review_items}
    existing = {resolution.review_item_sha256 for resolution in original.review_resolutions}
    requested = {item.sha256 for item in resolve}
    if (
        len(inventory) != len(original.review_items)
        or len(requested) != len(resolve)
        or not requested <= set(inventory)
        or any(inventory.get(item.sha256) != item for item in resolve)
    ):
        raise ApprovalError("manual review resolution does not match original inventory")
    if requested & existing:
        raise ApprovalError("manual review item is already resolved")
    if any(not _review_resolution_exists(item, changed) for item in resolve):
        raise ApprovalError("manual review resolution lacks matching typed content")
    return (
        *original.review_resolutions,
        *(
            ImportReviewResolution(
                review_item_sha256=item.sha256,
                actor=actor,
                recorded_at=recorded_at,
                notes=notes,
            )
            for item in resolve
        ),
    )


def _validated_draft(draft: DraftRulePackage) -> ImportedRuleDraft:
    if not isinstance(draft, ImportedRuleDraft):
        raise ApprovalError("approval workflow requires an imported draft")
    try:
        return ImportedRuleDraft.model_validate(draft.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ApprovalError("draft is structurally invalid") from error


def record_correction(
    draft: ImportedRuleDraft,
    corrected: ImportedRuleDraft,
    *,
    actor: str,
    notes: str,
    resolve: tuple[ImportReviewItem, ...] = (),
) -> ImportedRuleDraft:
    """Return corrected content with immutable item and content audits appended."""

    original = _validated_draft(draft)
    changed = _validated_draft(corrected)
    if not actor.strip() or not notes.strip():
        raise ApprovalError("correction actor and notes are required")
    if changed.manifest != original.manifest:
        raise ApprovalError("a correction cannot change the imported manifest")
    if changed.source_identities != original.source_identities:
        raise ApprovalError("a correction cannot change recognized source identities")
    if changed.review_items != original.review_items:
        raise ApprovalError("a correction cannot rewrite imported review items")
    if changed.review_resolutions != original.review_resolutions:
        raise ApprovalError("a correction cannot rewrite review resolutions")
    _require_safe_raw_grid_correction(original, changed)
    _require_safe_equation_correction(original, changed)
    content_changed = (
        changed.tables,
        changed.formulas,
        changed.mappings,
        changed.extracted_equations,
    ) != (
        original.tables,
        original.formulas,
        original.mappings,
        original.extracted_equations,
    )
    raw_changed = changed.raw_grids != original.raw_grids
    if not content_changed and not raw_changed and not resolve:
        raise ApprovalError("a correction must change rule content")
    _require_logged_content(original)
    original_reviews = original.review_items
    changed_reviews = changed.review_items
    corrected_mappings = tuple(
        mapping.model_copy(update={"approved": False}) for mapping in changed.mappings
    )
    before = _content_digest(
        original.tables,
        original.formulas,
        original.mappings,
        original_reviews,
        original.raw_grids,
        original.manifest.source_documents,
        original.source_identities,
        original.review_resolutions,
        original.extracted_equations,
    )
    recorded_at = datetime.now(UTC)
    resolutions = _require_valid_review_resolutions(
        original,
        changed,
        resolve,
        actor=actor.strip(),
        notes=notes.strip(),
        recorded_at=recorded_at,
    )
    after = _content_digest(
        changed.tables,
        changed.formulas,
        corrected_mappings,
        changed_reviews,
        changed.raw_grids,
        changed.manifest.source_documents,
        changed.source_identities,
        resolutions,
        changed.extracted_equations,
    )
    audit_records = tuple(
        ApprovalRecord(
            action="correction",
            actor=actor.strip(),
            recorded_at=recorded_at,
            notes=token,
        )
        for token in _changed_tokens(original, changed)
    )
    record = ApprovalRecord(
        action="correction",
        actor=actor.strip(),
        recorded_at=recorded_at,
        notes=f"content:{before}->{after}; {notes.strip()}",
    )
    manifest = original.manifest.model_copy(
        update={
            "approval_records": (
                *original.manifest.approval_records,
                *audit_records,
                record,
            )
        }
    )
    return ImportedRuleDraft(
        manifest=manifest,
        tables=changed.tables,
        formulas=changed.formulas,
        mappings=corrected_mappings,
        review_items=changed.review_items,
        review_resolutions=resolutions,
        raw_grids=changed.raw_grids,
        extracted_equations=changed.extracted_equations,
        source_identities=changed.source_identities,
    )


def _require_complete_audit(draft: DraftRulePackage) -> None:
    audited = {
        record.notes
        for record in draft.manifest.approval_records
        if (record.action == "extraction" and record.actor == f"icc-importer/{IMPORTER_VERSION}")
        or record.action == "correction"
    }
    required = (
        {
            note
            for identity in draft.source_identities
            for note in (
                f"identity:{identity.recipe_id}",
                f"layout:{identity.recipe_id}",
            )
        }
        if isinstance(draft, ImportedRuleDraft)
        else set()
    )
    required.update(f"table:{table.id}" for table in draft.tables)
    required.update(f"formula:{formula.id}" for formula in draft.formulas)
    required.update(f"mapping:{mapping.id}" for mapping in draft.mappings)
    if isinstance(draft, ImportedRuleDraft):
        required.update(f"equation:{equation.id}" for equation in draft.extracted_equations)
    missing = required - audited
    if missing:
        raise ApprovalError("draft has incomplete extraction, table, formula, or mapping audits")


def _require_logged_content(draft: DraftRulePackage) -> None:
    extraction_digests = tuple(
        record.notes.removeprefix("content:")
        for record in draft.manifest.approval_records
        if record.action == "extraction"
        and record.actor == f"icc-importer/{IMPORTER_VERSION}"
        and re.fullmatch(r"content:[0-9a-f]{64}", record.notes)
    )
    if len(extraction_digests) != 1:
        raise ApprovalError("draft content has no unique extraction audit")
    expected = extraction_digests[0]
    for record in draft.manifest.approval_records:
        if record.action != "correction" or not record.notes.startswith("content:"):
            continue
        match = re.match(
            r"content:([0-9a-f]{64})->([0-9a-f]{64});\s+\S",
            record.notes,
        )
        if match is None or match.group(1) != expected:
            raise ApprovalError("draft has a broken correction audit chain")
        expected = match.group(2)
    reviews = draft.review_items if isinstance(draft, ImportedRuleDraft) else ()
    raw_grids = draft.raw_grids if isinstance(draft, ImportedRuleDraft) else ()
    actual = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        reviews,
        raw_grids,
        draft.manifest.source_documents,
        draft.source_identities if isinstance(draft, ImportedRuleDraft) else (),
        draft.review_resolutions if isinstance(draft, ImportedRuleDraft) else (),
        draft.extracted_equations if isinstance(draft, ImportedRuleDraft) else (),
    )
    if actual != expected:
        raise ApprovalError("draft contains an unlogged content change")


def _require_compatibility_mapping(draft: DraftRulePackage) -> None:
    routes = tuple(mapping.source_rule_id for mapping in draft.mappings)
    if len(routes) != len(set(routes)):
        raise ApprovalError("compatibility mappings are ambiguous")
    from insulation_coordination.rules.importer.recipes import RECIPES

    required = {spec.semantic_route for recipe in RECIPES for spec in recipe.mappings}
    if set(routes) != required or len(routes) != len(required):
        raise ApprovalError("exact compatibility mapping family is incomplete")


def _require_resolved_recipe_semantics(draft: ImportedRuleDraft) -> None:
    from insulation_coordination.rules.importer.recipes import RECIPES

    table_specs = tuple(spec for recipe in RECIPES for spec in recipe.tables)
    formula_specs = tuple(spec for recipe in RECIPES for spec in recipe.formulas)
    mapping_specs = tuple(spec for recipe in RECIPES for spec in recipe.mappings)
    tables = {table.id: table for table in draft.tables}
    formulas = {formula.id: formula for formula in draft.formulas}
    mappings = {mapping.id: mapping for mapping in draft.mappings}
    grids = {grid.id: grid for grid in draft.raw_grids}
    if (
        set(tables) != {spec.semantic_id for spec in table_specs}
        or set(formulas) != {spec.semantic_id for spec in formula_specs}
        or set(mappings) != {spec.id for spec in mapping_specs}
        or set(grids) != {f"raw-{spec.semantic_id}" for spec in table_specs}
    ):
        raise ApprovalError("reviewed content sets do not match exact recipe semantics")
    recipes_by_id = {recipe.id: recipe for recipe in RECIPES}
    identities_by_recipe = {identity.recipe_id: identity for identity in draft.source_identities}
    for recipe_id, recipe in recipes_by_id.items():
        identity = identities_by_recipe[recipe_id]
        for spec in recipe.tables:
            table = tables[spec.semantic_id]
            grid = grids[f"raw-{spec.semantic_id}"]
            expected_source = SourceReference(
                standard=identity.standard,
                edition=identity.edition,
                clause=spec.clause,
                table=spec.source_table,
                note=f"PDF page {spec.page_number}",
            )
            typed_column_count = (
                sum(column.role == "data" for column in spec.columns)
                if spec.columns
                else spec.expected_data_columns
            )
            if (
                table.unit != spec.target_unit
                or table.source != expected_source
                or table.row_axis.id != spec.row_axis_id
                or table.row_axis.unit != spec.row_axis_unit
                or len(table.row_axis.values) != spec.expected_data_rows
                or table.column_axis.id != spec.column_axis_id
                or table.column_axis.unit != spec.column_axis_unit
                or len(table.column_axis.values) != typed_column_count
                or (grid.rows, grid.columns) != (spec.expected_raw_rows, spec.expected_raw_columns)
                or grid.target_unit != spec.target_unit
            ):
                raise ApprovalError("reviewed table violates its exact recipe contract")
            grid_cells = {(cell.row, cell.column): cell for cell in grid.cells}
            if spec.columns:
                data_ids = tuple(
                    column.semantic_id for column in spec.columns if column.role == "data"
                )
                data_order = {semantic_id: index for index, semantic_id in enumerate(data_ids)}
                raw_values = tuple(
                    sorted(
                        (
                            cell
                            for cell in grid.cells
                            if cell.logical_column in data_order and cell.value is not None
                        ),
                        key=lambda cell: (
                            cell.logical_row,
                            data_order[cell.logical_column or ""],
                        ),
                    )
                )
            elif spec.data_strategy == "rectangle":
                if spec.data_row_start is None or spec.data_column_start is None:
                    raise ApprovalError("recipe rectangle has no source coordinate")
                raw_values = tuple(
                    grid_cells[
                        (
                            spec.data_row_start + row,
                            spec.data_column_start + column,
                        )
                    ]
                    for row in range(spec.expected_data_rows)
                    for column in range(spec.expected_data_columns)
                )
            else:
                raw_values = tuple(cell for cell in grid.cells if cell.value is not None)
            typed_values = tuple(sorted(table.cells, key=lambda cell: (cell.row, cell.column)))
            if len(raw_values) != len(typed_values) or any(
                raw.value is None
                or typed.value != raw.value
                or typed.unit != spec.target_unit
                or typed.source != raw.source
                for typed, raw in zip(typed_values, raw_values, strict=True)
            ):
                raise ApprovalError("reviewed table does not correspond to its raw recipe grid")
        for formula_spec in recipe.formulas:
            formula = formulas[formula_spec.semantic_id]
            expected_source = SourceReference(
                standard=identity.standard,
                edition=identity.edition,
                clause=formula_spec.clause,
                table=formula_spec.table,
                figure=formula_spec.figure,
                note=f"PDF page {formula_spec.page_number}",
            )
            expected_shape = {
                "critical_frequency_inverse_clearance": "divide(literal,variable:clearance_mm)",
                "linear_frequency_factor": (
                    "add(literal,multiply(divide(add(variable:frequency_mhz,"
                    "multiply(literal,variable:critical_frequency_mhz)),"
                    "add(variable:minimum_frequency_mhz,multiply(literal,"
                    "variable:critical_frequency_mhz))),literal))"
                ),
                "minimum_frequency_statement": "literal",
                "radius_to_clearance_criterion": (
                    "compare(divide(variable:radius_mm,variable:clearance_mm),literal)"
                ),
            }.get(formula_spec.expression_shape, formula_spec.expression_shape)
            if (
                formula.unit != formula_spec.unit
                or formula.source != expected_source
                or _expression_variables(formula.expression) != set(formula_spec.variables)
                or _expression_shape(formula.expression) != expected_shape
            ):
                raise ApprovalError("reviewed formula violates its exact recipe contract")
        for mapping_spec in recipe.mappings:
            mapping = mappings[mapping_spec.id]
            expected_source = SourceReference(
                standard=identity.standard,
                edition=identity.edition,
                clause=mapping_spec.clause,
                table=mapping_spec.table,
                figure=mapping_spec.figure,
                note=f"PDF page {mapping_spec.page_number}",
            )
            if (
                mapping.source_rule_id != mapping_spec.semantic_route
                or mapping.target_rule_id != mapping_spec.target_rule_id
                or mapping.source != expected_source
            ):
                raise ApprovalError("mapping violates its exact recipe contract")


def _expression_shape(expression: Expression) -> str:
    value = expression.model_dump(mode="python")

    def shape(node: dict[str, object]) -> str:
        op = str(node["op"])
        if op == "literal":
            return "literal"
        if op == "variable":
            return f"variable:{node['name']}"
        if op in {"add", "multiply", "minimum", "maximum"}:
            operands = node["operands"]
            assert isinstance(operands, tuple)
            return f"{op}({','.join(shape(item) for item in operands)})"
        if op == "divide":
            return f"divide({shape(node['numerator'])},{shape(node['denominator'])})"  # type: ignore[arg-type]
        if op == "compare":
            return f"compare({shape(node['left'])},{shape(node['right'])})"  # type: ignore[arg-type]
        if op == "select":
            return (
                f"select({shape(node['condition'])},"  # type: ignore[arg-type]
                f"{shape(node['if_true'])},{shape(node['if_false'])})"  # type: ignore[arg-type]
            )
        if op == "round":
            return f"round:{node['places']}:{node['mode']}({shape(node['value'])})"  # type: ignore[arg-type]
        if op == "lookup":
            return (
                f"lookup:{node['table_id']}({shape(node['row'])},"  # type: ignore[arg-type]
                f"{shape(node['column'])})"  # type: ignore[arg-type]
            )
        if op == "linear_interpolate":
            children = [shape(node["x"])]  # type: ignore[arg-type]
            if node["column"] is not None:
                children.append(shape(node["column"]))  # type: ignore[arg-type]
            return f"linear_interpolate:{node['table_id']}({','.join(children)})"
        if op == "table_select":
            return f"table_select:{node['table_id']}({node['row_mode']},{node['column_mode']})"
        raise ApprovalError("formula expression has an unsupported recipe shape")

    return shape(value)


def _expression_variables(expression: Expression) -> set[str]:
    value = expression.model_dump(mode="python")

    def collect(node: object) -> set[str]:
        if isinstance(node, dict):
            names = {str(node["name"])} if node.get("op") == "variable" else set()
            return names | set().union(*(collect(item) for item in node.values()))
        if isinstance(node, tuple | list):
            return set().union(*(collect(item) for item in node))
        return set()

    return collect(value)


def _require_source_genesis(draft: ImportedRuleDraft) -> None:
    source_documents = tuple(
        (source.standard, source.edition, source.sha256)
        for source in draft.manifest.source_documents
    )
    identities = tuple(
        (identity.standard, identity.edition, identity.sha256)
        for identity in draft.source_identities
    )
    if source_documents != identities:
        raise ApprovalError("source identity does not match the extraction genesis")
    from insulation_coordination.rules.importer.recipes import RECIPES

    expected = tuple(sorted(RECIPES, key=lambda recipe: recipe.id))
    if (
        len(draft.source_identities) != len(expected)
        or tuple(identity.recipe_id for identity in draft.source_identities)
        != tuple(recipe.id for recipe in expected)
        or any(
            identity.standard != recipe.standard
            or identity.edition != recipe.edition
            or identity.page_count != recipe.expected_page_count
            for identity, recipe in zip(
                draft.source_identities,
                expected,
                strict=True,
            )
        )
    ):
        raise ApprovalError("source layout identity does not match exact recipes")


def _require_draft_structure(draft: DraftRulePackage) -> None:
    package_view = RulePackage(
        manifest=draft.manifest,
        tables=draft.tables,
        formulas=draft.formulas,
        mappings=draft.mappings,
        checksums=draft.checksums,
        package_sha256=draft.package_sha256,
    )
    report = validate_rule_package(package_view)
    failures = tuple(
        result.code
        for result in report.results
        if not result.passed and result.code not in _EXPECTED_DRAFT_FAILURES
    )
    if failures:
        raise ApprovalError(f"approval validation failed: {', '.join(failures)}")


def is_fully_resolved(draft: ImportedRuleDraft) -> bool:
    """True when every manual review item has an associated resolution."""
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    inventory = {item.sha256 for item in draft.review_items}
    return (
        len(resolved) == len(draft.review_resolutions) == len(inventory) and resolved == inventory
    )


def approve_draft(
    draft: ImportedRuleDraft,
    approver: str,
    notes: str,
) -> RulePackage:
    """Approve only after importer audits and full package validation pass."""

    draft = _validated_draft(draft)
    if not approver.strip() or not notes.strip():
        raise ApprovalError("approver and approval notes are required")
    if draft.manifest.approved or any(
        record.action == "approval" for record in draft.manifest.approval_records
    ):
        raise ApprovalError("draft already contains an approval")
    resolved = {resolution.review_item_sha256 for resolution in draft.review_resolutions}
    inventory = {item.sha256 for item in draft.review_items}
    if (
        len(resolved) != len(draft.review_resolutions)
        or not resolved <= inventory
        or inventory - resolved
    ):
        raise ApprovalError("draft has unresolved manual review items")
    _require_source_genesis(draft)
    _require_complete_audit(draft)
    _require_compatibility_mapping(draft)
    _require_resolved_recipe_semantics(draft)
    _require_draft_structure(draft)
    _require_logged_content(draft)

    approval = ApprovalRecord(
        action="approval",
        actor=approver.strip(),
        recorded_at=datetime.now(UTC),
        notes=notes.strip(),
    )
    manifest = draft.manifest.model_copy(
        update={
            "approved": True,
            "compatible": True,
            "approval_records": (*draft.manifest.approval_records, approval),
            "notes": notes.strip(),
        }
    )
    candidate = RulePackage(
        manifest=manifest,
        tables=draft.tables,
        formulas=draft.formulas,
        mappings=tuple(mapping.model_copy(update={"approved": True}) for mapping in draft.mappings),
    )
    try:
        content, checksums = _archive_bytes(candidate)
        candidate = candidate.model_copy(
            update={
                "checksums": checksums,
                "package_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        report = validate_rule_package(candidate)
    except (AttributeError, TypeError, ValueError) as error:
        raise ApprovalError("approved candidate could not be validated") from error
    if not report.is_valid:
        failures = ", ".join(result.code for result in report.results if not result.passed)
        raise ApprovalError(f"approval validation failed: {failures}")
    return candidate
