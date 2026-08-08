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
    SemanticProposal,
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
        for field in ("document_id", "standard", "edition", "page", "clause", "table", "figure")
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
    cells = tuple(
        cell
        for grid in changed.raw_grids
        for cell in grid.cells
        if f"{grid.id}:{cell.row}:{cell.column}" == item.semantic_id
        and _source_matches(cell.source, item.source)
    )
    if item.code == "AMBIGUOUS_COMPOUND_CELL":
        return any(
            cell.parse_status == "compound"
            and len(cell.components) == len(cell.compound_component_ids)
            and {component.component_id for component in cell.components}
            == set(cell.compound_component_ids)
            and all(component.value is not None for component in cell.components)
            for cell in cells
        )
    if item.code == "AMBIGUOUS_COMPONENT_FORMULA":
        component_id = item.expected_contract.rsplit(":", 1)[-1]
        return any(
            len(
                tuple(
                    candidate
                    for candidate in cell.formula_candidates
                    if candidate.component_id == component_id
                    and candidate.formula_id is not None
                )
            )
            == 1
            and len(
                tuple(
                    candidate
                    for candidate in cell.formula_candidates
                    if candidate.component_id == component_id
                )
            )
            == 1
            for cell in cells
        )
    return any(
        cell.value is not None and cell.parse_status == "numeric" for cell in cells
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
        ("decision", original.decisions, changed.decisions),
        ("procedure", original.procedures, changed.procedures),
        ("guidance", original.guidance, changed.guidance),
        ("curve", original.curves, changed.curves),
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
    known_formula_ids = {
        spec.semantic_id for recipe in _recipes() for spec in recipe.formulas
    }
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
        for key, before_cell in before_cells.items():
            after_cell = after_cells[key]
            if before_cell.compound_component_ids != after_cell.compound_component_ids:
                raise ApprovalError("a correction cannot rewrite declared compound components")
            before_components = {part.component_id: part for part in before_cell.components}
            after_components = {part.component_id: part for part in after_cell.components}
            if len(after_components) != len(after_cell.components) or any(
                part.raw_text != before_components[component_id].raw_text
                or part.unit != before_components[component_id].unit
                or part.source != before_components[component_id].source
                for component_id, part in after_components.items()
                if component_id in before_components
            ):
                raise ApprovalError("a correction cannot rewrite compound component provenance")
            if any(
                part.source != after_cell.source
                for component_id, part in after_components.items()
                if component_id not in before_components
            ):
                raise ApprovalError("a correction cannot invent compound component provenance")
            if any(candidate.source != after_cell.source for candidate in after_cell.formula_candidates):
                raise ApprovalError("a correction cannot rewrite formula candidate provenance")
            for component_id in {
                candidate.component_id
                for candidate in (
                    *before_cell.formula_candidates,
                    *after_cell.formula_candidates,
                )
            }:
                before_candidates = tuple(
                    candidate
                    for candidate in before_cell.formula_candidates
                    if candidate.component_id == component_id
                )
                after_candidates = tuple(
                    candidate
                    for candidate in after_cell.formula_candidates
                    if candidate.component_id == component_id
                )
                if before_candidates == after_candidates:
                    continue
                concrete_ids = {
                    candidate.formula_id
                    for candidate in before_candidates
                    if candidate.formula_id is not None
                }
                exact = (
                    len(after_candidates) == 1
                    and after_candidates[0].formula_id is not None
                    and (
                        after_candidates[0].formula_id in concrete_ids
                        or (
                            not concrete_ids
                            and after_candidates[0].formula_id in known_formula_ids
                        )
                    )
                )
                if not exact:
                    raise ApprovalError(
                        "a correction must select one exact formula candidate"
                    )


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


def _sync_semantic_proposals(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
) -> tuple[SemanticProposal, ...]:
    from insulation_coordination.rules.importer.extract import (
        canonical_model_sha256,
    )
    from insulation_coordination.rules.importer.review import (
        _current_source_artifact_sha256,
        _required_review_items,
        _rule_entries,
    )

    before_rules = {(kind, rule.id): rule for kind, rule in _rule_entries(original)}
    after_rules = {(kind, rule.id): rule for kind, rule in _rule_entries(changed)}
    if len(before_rules) != len(_rule_entries(original)) or len(after_rules) != len(
        _rule_entries(changed)
    ):
        raise ApprovalError("rule semantic IDs must be unique within each rule kind")
    before = {(item.rule_kind, item.semantic_id): item for item in original.semantic_proposals}
    supplied = {(item.rule_kind, item.semantic_id): item for item in changed.semantic_proposals}
    if len(before) != len(original.semantic_proposals) or len(supplied) != len(
        changed.semantic_proposals
    ):
        raise ApprovalError("semantic proposals must be unique by rule kind and ID")
    if set(supplied) - set(after_rules) - set(before_rules):
        raise ApprovalError("semantic proposal has no matching typed rule")

    proposals: list[SemanticProposal] = []
    for key, rule in after_rules.items():
        kind, semantic_id = key
        prior = before.get(key)
        candidate = supplied.get(key)
        if prior is not None and before_rules.get(key) == rule and candidate != prior:
            raise ApprovalError("a correction cannot rewrite an unchanged semantic proposal")
        probe = SemanticProposal(
            semantic_id=semantic_id,
            rule_kind=kind,
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256="0" * 64,
            review_item_sha256s=(),
        )
        review_hashes = tuple(
            item.sha256 for item in _required_review_items(changed, probe)
        )
        probe = probe.model_copy(update={"review_item_sha256s": review_hashes})
        source_sha256 = _current_source_artifact_sha256(changed, probe)
        unchanged = (
            prior is not None
            and before_rules.get(key) == rule
            and prior.rule_sha256 == probe.rule_sha256
            and prior.source_artifact_sha256 == source_sha256
            and prior.review_item_sha256s == review_hashes
        )
        if unchanged:
            assert prior is not None
            proposals.append(prior)
        else:
            proposals.append(probe.model_copy(update={"source_artifact_sha256": source_sha256}))
    return tuple(proposals)


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
        changed.decisions,
        changed.procedures,
        changed.guidance,
        changed.curves,
        changed.extracted_equations,
    ) != (
        original.tables,
        original.formulas,
        original.mappings,
        original.decisions,
        original.procedures,
        original.guidance,
        original.curves,
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
    semantic_proposals = _sync_semantic_proposals(original, changed)
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
        decisions=original.decisions,
        procedures=original.procedures,
        guidance=original.guidance,
        curves=original.curves,
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
        decisions=changed.decisions,
        procedures=changed.procedures,
        guidance=changed.guidance,
        curves=changed.curves,
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
        decisions=changed.decisions,
        procedures=changed.procedures,
        guidance=changed.guidance,
        curves=changed.curves,
        review_items=changed.review_items,
        review_resolutions=resolutions,
        raw_grids=changed.raw_grids,
        extracted_equations=changed.extracted_equations,
        semantic_proposals=semantic_proposals,
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
    required.update(f"decision:{rule.id}" for rule in draft.decisions)
    required.update(f"procedure:{rule.id}" for rule in draft.procedures)
    required.update(f"guidance:{rule.id}" for rule in draft.guidance)
    required.update(f"curve:{rule.id}" for rule in draft.curves)
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
        decisions=draft.decisions,
        procedures=draft.procedures,
        guidance=draft.guidance,
        curves=draft.curves,
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
                document_id=identity.recipe_id,
                standard=identity.standard,
                edition=identity.edition,
                page=grid.segments[0].page_number,
                clause=spec.clause,
                table=spec.source_table,
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
                data_columns = tuple(column for column in spec.columns if column.role == "data")
                logical = {
                    (cell.logical_row, cell.logical_column): cell
                    for cell in grid.cells
                    if cell.logical_row is not None and cell.logical_column is not None
                }
                previous = {}
                raw_value_list = []
                for logical_row in sorted({row for row, _ in logical}):
                    for column in data_columns:
                        raw = logical.get((logical_row, column.semantic_id))
                        selected = (
                            next(
                                (
                                    component
                                    for component in raw.components
                                    if component.component_id == column.projected_component_id
                                ),
                                None,
                            )
                            if raw is not None and column.projected_component_id is not None
                            else raw
                        )
                        if selected is not None and selected.value is not None:
                            previous[column.semantic_id] = raw
                        elif column.fill_down:
                            raw = previous.get(column.semantic_id)
                            selected = (
                                next(
                                    (
                                        component
                                        for component in raw.components
                                        if component.component_id
                                        == column.projected_component_id
                                    ),
                                    None,
                                )
                                if raw is not None
                                and column.projected_component_id is not None
                                else raw
                            )
                        if selected is not None and selected.value is not None:
                            raw_value_list.append(selected)
                raw_values = tuple(raw_value_list)
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
                document_id=identity.recipe_id,
                standard=identity.standard,
                edition=identity.edition,
                page=formula_spec.page_number,
                clause=formula_spec.clause,
                table=formula_spec.table,
                figure=formula_spec.figure,
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
                document_id=identity.recipe_id,
                standard=identity.standard,
                edition=identity.edition,
                page=mapping_spec.page_number,
                clause=mapping_spec.clause,
                table=mapping_spec.table,
                figure=mapping_spec.figure,
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
        if op == "power":
            return f"power:{node['numerator']}/{node['denominator']}({shape(node['base'])})"  # type: ignore[arg-type]
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


def _require_consistent_shared_source_cells(draft: ImportedRuleDraft) -> None:
    """Two grids that both cover one physical source cell must agree on its value.

    Some recipes extract the same physical PDF cell into more than one raw grid --
    e.g. the four IEC 62477-1 Table 7 AC/DC specs each re-extract a shared axis or
    data column. ``RawGridCell.source`` (page, table, and its own grid row/column,
    see ``_source`` in ``extract.py``) identifies the physical cell a value came
    from; two cells with an equal ``source`` are two copies of the same cell. A
    reviewer correcting one copy and not the other must not approve.
    """
    first_seen: dict[SourceReference, tuple[str, object]] = {}
    for grid in draft.raw_grids:
        for cell in grid.cells:
            values: object = (
                (
                    tuple(
                        (component.component_id, component.value, component.unit)
                        for component in cell.components
                        if component.value is not None
                    ),
                    tuple(
                        (candidate.component_id, candidate.formula_id)
                        for candidate in cell.formula_candidates
                    ),
                )
                if cell.components
                else cell.value
            )
            if values is None or values == ((), ()):
                continue
            seen = first_seen.get(cell.source)
            if seen is None:
                first_seen[cell.source] = (grid.id, values)
                continue
            other_grid_id, other_value = seen
            if other_value != values:
                raise ApprovalError(
                    f"{other_grid_id} and {grid.id} disagree on the value of the shared "
                    f"source cell at table {cell.source.table} page {cell.source.page} "
                    f"row {cell.source.row} column {cell.source.column}"
                )


def _require_source_genesis(draft: ImportedRuleDraft) -> None:
    source_documents = tuple(
        (source.id, source.standard, source.edition, source.sha256)
        for source in draft.manifest.source_documents
    )
    identities = tuple(
        (identity.recipe_id, identity.standard, identity.edition, identity.sha256)
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
            or identity.page_count
            not in (recipe.expected_page_count, *recipe.accepted_page_counts)
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
        decisions=draft.decisions,
        procedures=draft.procedures,
        guidance=draft.guidance,
        curves=draft.curves,
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


def _semantic_blocker(
    draft: ImportedRuleDraft,
    *,
    code: str,
    semantic_id: str,
    message: str,
) -> ImportReviewItem:
    from insulation_coordination.rules.importer.review import _rule_entries

    source = next(
        (rule.source for _, rule in _rule_entries(draft) if rule.id == semantic_id),
        None,
    )
    if source is None:
        document = draft.manifest.source_documents[0]
        source = SourceReference(
            document_id=document.id,
            standard=document.standard,
            edition=document.edition,
        )
    return ImportReviewItem(
        code=code,
        semantic_id=semantic_id,
        kind="semantic",
        source=source,
        expected_contract=message,
    )


def approval_blockers(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    """Return the one authoritative manual and semantic approval gate."""
    from insulation_coordination.rules.importer.review import (
        _require_current_proposal,
        _rule_entries,
    )

    inventory_hashes = tuple(item.sha256 for item in draft.review_items)
    resolution_hashes = tuple(
        resolution.review_item_sha256 for resolution in draft.review_resolutions
    )
    resolved = set(resolution_hashes)
    blockers: list[ImportReviewItem] = []
    if (
        len(inventory_hashes) != len(set(inventory_hashes))
        or len(resolution_hashes) != len(resolved)
        or not resolved <= set(inventory_hashes)
    ):
        semantic_id = draft.review_items[0].semantic_id if draft.review_items else draft.manifest.version
        blockers.append(
            _semantic_blocker(
                draft,
                code="REVIEW_RESOLUTION_INVALID",
                semantic_id=semantic_id,
                message="manual review resolution inventory is duplicate or stale",
            )
        )
    blockers.extend(item for item in draft.review_items if item.sha256 not in resolved)
    rules = _rule_entries(draft)
    proposals = draft.semantic_proposals
    for kind, rule in rules:
        matches = tuple(
            proposal
            for proposal in proposals
            if proposal.rule_kind == kind and proposal.semantic_id == rule.id
        )
        if not matches:
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="SEMANTIC_PROPOSAL_MISSING",
                    semantic_id=rule.id,
                    message=f"missing required semantic proposal for {rule.id}",
                )
            )
            continue
        if len(matches) != 1:
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="SEMANTIC_PROPOSAL_DUPLICATE",
                    semantic_id=rule.id,
                    message=f"duplicate semantic proposal for {rule.id}",
                )
            )
            continue
        proposal = matches[0]
        if proposal.state != "reviewed":
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="SEMANTIC_PROPOSAL_PROPOSED",
                    semantic_id=rule.id,
                    message=f"semantic proposal {rule.id} is still proposed",
                )
            )
            continue
        try:
            _require_current_proposal(draft, proposal, require_resolved_members=True)
        except ApprovalError as error:
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="SEMANTIC_PROPOSAL_STALE",
                    semantic_id=rule.id,
                    message=str(error),
                )
            )
    rule_keys = {(kind, rule.id) for kind, rule in rules}
    for proposal in proposals:
        if (proposal.rule_kind, proposal.semantic_id) not in rule_keys:
            blockers.append(
                _semantic_blocker(
                    draft,
                    code="SEMANTIC_PROPOSAL_STALE",
                    semantic_id=proposal.semantic_id,
                    message=f"stale semantic proposal {proposal.semantic_id} has no current rule",
                )
            )
    return tuple(blockers)


def is_fully_resolved(draft: ImportedRuleDraft) -> bool:
    """True when the single manual and semantic approval gate is empty."""
    return not approval_blockers(draft)


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
    blockers = approval_blockers(draft)
    if blockers:
        resolved = {item.review_item_sha256 for item in draft.review_resolutions}
        manual = any(item.sha256 not in resolved for item in draft.review_items)
        raise ApprovalError(
            "draft approval blockers: "
            + ("unresolved manual review items; " if manual else "")
            + "; ".join(item.expected_contract for item in blockers)
        )
    _require_source_genesis(draft)
    _require_complete_audit(draft)
    _require_compatibility_mapping(draft)
    _require_resolved_recipe_semantics(draft)
    _require_consistent_shared_source_cells(draft)
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
        decisions=draft.decisions,
        procedures=draft.procedures,
        guidance=draft.guidance,
        curves=draft.curves,
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
