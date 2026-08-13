from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    DraftRulePackage,
    Expression,
    FaultTimeVoltageVariant,
    PiecewiseCurveRule,
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
    canonical_model_sha256,
    draft_content_digest,
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


def _manual_curve_review_is_current(
    draft: ImportedRuleDraft,
    variant: FaultTimeVoltageVariant,
) -> bool:
    figures = tuple(
        figure for figure in draft.raw_figures if _source_matches(figure.source, variant.source)
    )
    if len(figures) != 1:
        return False
    figure = figures[0]
    calibrations = tuple(
        calibration
        for calibration in draft.curve_calibrations
        if calibration.figure_artifact_sha256 == figure.artifact_sha256
        and calibration.calibration.figure_artifact_sha256 == figure.artifact_sha256
        and calibration.calibration_sha256 == canonical_model_sha256(calibration.calibration)
    )
    if len(calibrations) != 1:
        return False
    calibration = calibrations[0]
    from insulation_coordination.rules.importer.review import (
        _manual_reviewed_artifact_sha256,
    )

    if variant.reviewed_artifact_sha256 != _manual_reviewed_artifact_sha256(
        figure, calibration.calibration_sha256
    ):
        return False
    return (
        len(
            tuple(
                review
                for review in draft.curve_variant_reviews
                if review.variant_id == variant.id
                and review.variant_sha256 == canonical_model_sha256(variant)
                and review.source_artifact_sha256 == variant.reviewed_artifact_sha256
                and review.calibration_sha256 == calibration.calibration_sha256
            )
        )
        == 1
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
    if item.kind == "clause":
        return any(
            fragment.id == f"raw-{item.semantic_id}"
            and _source_matches(fragment.source, item.source)
            for fragment in changed.raw_clause_fragments
        )
    if item.kind == "curve":
        variants = tuple(
            variant
            for curve in changed.curves
            for variant in curve.variants
            if variant.id == item.semantic_id
        )
        return len(variants) == 1 and _manual_curve_review_is_current(changed, variants[0])
    if item.code in {"AMBIGUOUS_COMPOUND_CELL", "AMBIGUOUS_COMPONENT_FORMULA"}:
        grid_id, row_text, column_text, source_index_text = item.semantic_id.rsplit(":", 3)
        cell = next(
            (
                cell
                for grid in changed.raw_grids
                if grid.id == grid_id
                for cell in grid.cells
                if (cell.row, cell.column) == (int(row_text), int(column_text))
                and _source_matches(cell.source, item.source)
            ),
            None,
        )
        if cell is None:
            return False
        source_index = int(source_index_text)
        component = next(
            (component for component in cell.components if component.source_index == source_index),
            None,
        )
        if component is None or component.component_id is None:
            return False
        if item.code == "AMBIGUOUS_COMPOUND_CELL":
            return (
                cell.parse_status == "compound"
                and len(cell.components) == len(cell.compound_component_ids)
                and {part.component_id for part in cell.components}
                == set(cell.compound_component_ids)
                and all(part.value is not None for part in cell.components)
            )
        candidates = tuple(
            candidate
            for candidate in cell.formula_candidates
            if candidate.source_index == source_index
        )
        allowed = {
            formula_id
            for component_id, formula_id in cell.allowed_component_formula_ids
            if component_id == component.component_id
        }
        return (
            len(candidates) == 1
            and candidates[0].component_id == component.component_id
            and candidates[0].formula_id in allowed
        )
    cells = tuple(
        cell
        for grid in changed.raw_grids
        for cell in grid.cells
        if f"{grid.id}:{cell.row}:{cell.column}" == item.semantic_id
        and _source_matches(cell.source, item.source)
    )
    return any(cell.value is not None and cell.parse_status == "numeric" for cell in cells)


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
    before_fragments = {item.id: item for item in original.raw_clause_fragments}
    after_fragments = {item.id: item for item in changed.raw_clause_fragments}
    tokens.extend(
        f"raw-clause:{fragment_id}"
        for fragment_id in sorted(set(before_fragments) | set(after_fragments))
        if before_fragments.get(fragment_id) != after_fragments.get(fragment_id)
    )
    before_equations = {item.id: item for item in original.extracted_equations}
    after_equations = {item.id: item for item in changed.extracted_equations}
    tokens.extend(
        f"equation:{equation_id}"
        for equation_id in sorted(set(before_equations) | set(after_equations))
        if before_equations.get(equation_id) != after_equations.get(equation_id)
    )
    before_calibrations = {
        item.figure_artifact_sha256: item for item in original.curve_calibrations
    }
    after_calibrations = {item.figure_artifact_sha256: item for item in changed.curve_calibrations}
    tokens.extend(
        f"curve-calibration:{artifact_sha256}"
        for artifact_sha256 in sorted(set(before_calibrations) | set(after_calibrations))
        if before_calibrations.get(artifact_sha256) != after_calibrations.get(artifact_sha256)
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
        for key, before_cell in before_cells.items():
            after_cell = after_cells[key]
            if before_cell.compound_component_ids != after_cell.compound_component_ids:
                raise ApprovalError("a correction cannot rewrite declared compound components")
            if (
                before_cell.allowed_component_formula_ids
                != after_cell.allowed_component_formula_ids
            ):
                raise ApprovalError("a correction cannot rewrite component formula routes")
            before_components = {part.source_index: part for part in before_cell.components}
            after_components = {part.source_index: part for part in after_cell.components}
            if (
                len(before_components) != len(before_cell.components)
                or len(after_components) != len(after_cell.components)
                or set(before_components) != set(after_components)
                or any(
                    after_components[source_index].raw_text != part.raw_text
                    or after_components[source_index].unit != part.unit
                    or after_components[source_index].source != part.source
                    for source_index, part in before_components.items()
                )
            ):
                raise ApprovalError("a correction cannot rewrite compound component provenance")
            if any(
                candidate.source_index not in after_components
                or candidate.source != after_components[candidate.source_index].source
                for candidate in after_cell.formula_candidates
            ):
                raise ApprovalError("a correction cannot rewrite formula candidate provenance")
            for source_index, component in after_components.items():
                before_candidates = tuple(
                    candidate
                    for candidate in before_cell.formula_candidates
                    if candidate.source_index == source_index
                )
                after_candidates = tuple(
                    candidate
                    for candidate in after_cell.formula_candidates
                    if candidate.source_index == source_index
                )
                association_changed = (
                    before_components[source_index].component_id != component.component_id
                )
                if before_candidates == after_candidates and not association_changed:
                    continue
                allowed = {
                    formula_id
                    for component_id, formula_id in (after_cell.allowed_component_formula_ids)
                    if component_id == component.component_id
                }
                exact = (
                    (
                        len(after_candidates) == 1
                        and component.component_id is not None
                        and after_candidates[0].component_id == component.component_id
                        and after_candidates[0].formula_id in allowed
                    )
                    if allowed
                    else not after_candidates
                )
                if not exact:
                    raise ApprovalError("a correction must select one exact formula candidate")


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


def _curve_reopen_evidence(
    draft: ImportedRuleDraft,
    variant_id: str,
) -> tuple[object, ...]:
    variants = tuple(
        variant for curve in draft.curves for variant in curve.variants if variant.id == variant_id
    )
    if len(variants) != 1:
        raise ApprovalError("curve review reopening requires one exact curve variant")
    variant = variants[0]
    figures = tuple(
        figure for figure in draft.raw_figures if _source_matches(figure.source, variant.source)
    )
    if len(figures) != 1:
        raise ApprovalError("curve review reopening requires one exact source figure")
    artifact_sha256 = figures[0].artifact_sha256
    return (
        variant,
        tuple(
            calibration
            for calibration in draft.curve_calibrations
            if calibration.figure_artifact_sha256 == artifact_sha256
        ),
        tuple(
            input for input in draft.manual_curve_variant_inputs if input.variant_id == variant_id
        ),
    )


def _require_valid_review_resolutions(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
    resolve: tuple[ImportReviewItem, ...],
    reopen: tuple[ImportReviewItem, ...],
    *,
    actor: str,
    notes: str,
    recorded_at: datetime,
) -> tuple[ImportReviewResolution, ...]:
    inventory = {item.sha256: item for item in original.review_items}
    reopened = {item.sha256 for item in reopen}
    existing = {resolution.review_item_sha256 for resolution in original.review_resolutions}
    requested = {item.sha256 for item in resolve}
    if (
        len(inventory) != len(original.review_items)
        or len(requested) != len(resolve)
        or len(reopened) != len(reopen)
        or not requested <= set(inventory)
        or not reopened <= set(inventory)
        or any(inventory.get(item.sha256) != item for item in resolve)
        or any(inventory.get(item.sha256) != item for item in reopen)
        or not reopened <= existing
    ):
        raise ApprovalError("manual review resolution does not match original inventory")
    if requested & (existing - reopened):
        raise ApprovalError("manual review item is already resolved")
    if any(item.kind != "curve" for item in reopen):
        raise ApprovalError("only changed curve review evidence can be reopened")
    if any(
        _curve_reopen_evidence(original, item.semantic_id)
        == _curve_reopen_evidence(changed, item.semantic_id)
        for item in reopen
    ):
        raise ApprovalError("curve review reopening requires changed curve evidence")
    if any(not _review_resolution_exists(item, changed) for item in resolve):
        raise ApprovalError("manual review resolution lacks matching typed content")
    return (
        *(
            resolution
            for resolution in original.review_resolutions
            if resolution.review_item_sha256 not in reopened
        ),
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
        review_hashes = tuple(item.sha256 for item in _required_review_items(changed, probe))
        probe = probe.model_copy(update={"review_item_sha256s": review_hashes})
        source_sha256 = _current_source_artifact_sha256(changed, probe)
        unchanged = (
            prior is not None
            and before_rules.get(key) == rule
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
    reopen: tuple[ImportReviewItem, ...] = (),
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
    if changed.raw_figures != original.raw_figures:
        raise ApprovalError("a correction cannot rewrite extracted raw figure evidence")
    # The chain this record extends is the one ``_require_logged_content`` verifies, so the
    # link it writes has to be that same function of that same draft.
    before = draft_content_digest(original)
    # Also what "changed" means here: every content collection, read through the one function,
    # so a collection nobody remembered to compare cannot pass as unchanged.
    if before == draft_content_digest(changed) and not resolve and not reopen:
        raise ApprovalError("a correction must change rule content")
    corrected_mappings = tuple(
        mapping.model_copy(update={"approved": False}) for mapping in changed.mappings
    )
    semantic_proposals = _sync_semantic_proposals(original, changed)
    _require_logged_content(original)
    recorded_at = datetime.now(UTC)
    resolutions = _require_valid_review_resolutions(
        original,
        changed,
        resolve,
        reopen,
        actor=actor.strip(),
        notes=notes.strip(),
        recorded_at=recorded_at,
    )
    corrected = changed.model_copy(
        update={
            "mappings": corrected_mappings,
            "review_resolutions": resolutions,
            "semantic_proposals": semantic_proposals,
        }
    )
    # The same chicken-and-egg ``extract_draft`` solves: the link this record writes must be
    # the digest of the draft that carries the record. So digest the corrected content while
    # the manifest is still the original's -- ``draft_content_digest`` reads only its source
    # documents, which a correction cannot change -- then copy the new manifest in below.
    after = draft_content_digest(corrected)
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
    return corrected.model_copy(update={"manifest": manifest})


def _require_complete_inventory(draft: DraftRulePackage) -> None:
    """Refuse a package that does not carry every required source item.

    Completeness comes from the required source inventory rather than from counting
    extracted tables, so a package cannot look finished while an item a consumer feature
    depends on is missing. Items whose recipes are not written yet are declared deferred
    and reported as such instead of blocking here.
    """
    from insulation_coordination.rules.importer.review import missing_inventory_items

    if not isinstance(draft, ImportedRuleDraft):
        return
    missing = missing_inventory_items(draft)
    if missing:
        named = ", ".join(status.semantic_id for status in missing[:3])
        suffix = "" if len(missing) <= 3 else f", and {len(missing) - 3} more"
        raise ApprovalError(
            f"draft is missing {len(missing)} required inventory item(s): {named}{suffix}"
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
        required.update(f"raw-clause:{fragment.id}" for fragment in draft.raw_clause_fragments)
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
        if record.action != "correction" or not re.match(
            r"content:[0-9a-f]{64}->[0-9a-f]{64};", record.notes
        ):
            continue
        match = re.match(
            r"content:([0-9a-f]{64})->([0-9a-f]{64});\s+\S",
            record.notes,
        )
        assert match is not None
        if match.group(1) != expected:
            raise ApprovalError("draft has a broken correction audit chain")
        expected = match.group(2)
    if draft_content_digest(draft) != expected:
        raise ApprovalError("draft contains an unlogged content change")


def _require_compatibility_mapping(draft: DraftRulePackage) -> None:
    routes = tuple(mapping.source_rule_id for mapping in draft.mappings)
    if len(routes) != len(set(routes)):
        raise ApprovalError("compatibility mappings are ambiguous")
    from insulation_coordination.rules.importer.expectations import package_expectations
    from insulation_coordination.rules.importer.recipes import RECIPES

    # Two kinds of mapping reach a package. A declared mapping states a route the recipe
    # asserts up front, and that family must be exactly complete. A cross-standard mapping
    # exists only where a comparison proved two grids equal, so it is permitted rather than
    # required here: a divergent comparison already refuses during review, and the inventory
    # gate is what reports content a draft never carried.
    expectations = package_expectations(RECIPES)
    required = expectations.declared_mapping_routes
    declared = set(routes) - expectations.proven_mapping_routes
    if declared != required or len(declared) != len(required):
        raise ApprovalError("exact compatibility mapping family is incomplete")


def _require_resolved_recipe_semantics(draft: ImportedRuleDraft) -> None:
    from insulation_coordination.rules.importer.expectations import package_expectations
    from insulation_coordination.rules.importer.recipes import RECIPES

    # A spec yields a ``Table`` only when nothing else claims its grid: a spec with a
    # registered projector yields rules of another kind, and a comparison-only spec yields
    # evidence for a cross-standard check and no rule at all. That classification lives in
    # ``package_expectations``, which the inventory and validation gates read as well.
    expectations = package_expectations(RECIPES)
    tables = {table.id: table for table in draft.tables}
    formulas = {formula.id: formula for formula in draft.formulas}
    mappings = {mapping.id: mapping for mapping in draft.mappings}
    grids = {grid.id: grid for grid in draft.raw_grids}
    if (
        set(tables) != expectations.table_rule_ids
        or set(formulas) != expectations.formula_ids
        # A proven cross-standard mapping is permitted beside the declared family, exactly as
        # ``_require_compatibility_mapping`` permits it.
        or set(mappings) - expectations.proven_mapping_ids != expectations.declared_mapping_ids
        or set(grids) != expectations.raw_grid_ids
    ):
        raise ApprovalError("reviewed content sets do not match exact recipe semantics")
    recipes_by_id = {recipe.id: recipe for recipe in RECIPES}
    identities_by_recipe = {identity.recipe_id: identity for identity in draft.source_identities}
    for recipe_id, recipe in recipes_by_id.items():
        identity = identities_by_recipe[recipe_id]
        for spec in recipe.tables:
            grid = grids[f"raw-{spec.semantic_id}"]
            if spec.comparison_only:
                # Evidence for a cross-standard check. The grid must exist, which the set
                # comparison above already required, and it becomes no rule to re-derive.
                continue
            projector = recipe.grid_projectors.get(spec.semantic_id)
            if projector is not None:
                # Re-project from the reviewed grid and require the draft to hold exactly
                # that, so a rule cannot drift from the grid it claims to come from. The
                # projector comes from the recipe, so this stays free of any one standard's
                # identifiers.
                from insulation_coordination.rules.importer.review import (
                    resolve_confirmed_axis_selectors,
                )

                expected, _proposals = projector(
                    grid, identity, resolve_confirmed_axis_selectors(spec, grid, draft)
                )
                # Compared by identifier, not by position: one projection may return several
                # kinds, and the draft keeps each kind in its own collection, so the order a
                # rule appears in says nothing about whether it matches.
                expected_by_id = {rule.id: rule for rule in expected}
                actual_by_id: dict[str, object] = {}
                for decision in draft.decisions:
                    if decision.id in expected_by_id:
                        actual_by_id[decision.id] = decision
                for procedure in draft.procedures:
                    if procedure.id in expected_by_id:
                        actual_by_id[procedure.id] = procedure
                for guidance_rule in draft.guidance:
                    if guidance_rule.id in expected_by_id:
                        actual_by_id[guidance_rule.id] = guidance_rule
                if actual_by_id != expected_by_id:
                    raise ApprovalError("reviewed rule does not correspond to its raw recipe grid")
                continue
            table = tables[spec.semantic_id]
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
                                        if component.component_id == column.projected_component_id
                                    ),
                                    None,
                                )
                                if raw is not None and column.projected_component_id is not None
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
    first_seen: dict[tuple[object, ...], tuple[str, object]] = {}
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
            physical_source = tuple(
                getattr(cell.source, field)
                for field in (
                    "document_id",
                    "standard",
                    "edition",
                    "page",
                    "clause",
                    "table",
                    "figure",
                    "row",
                    "column",
                )
            )
            seen = first_seen.get(physical_source)
            if seen is None:
                first_seen[physical_source] = (grid.id, values)
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
            or identity.page_count not in (recipe.expected_page_count, *recipe.accepted_page_counts)
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
        documents = draft.manifest.source_documents
        if documents:
            document = documents[0]
            source = SourceReference(
                document_id=document.id,
                standard=document.standard,
                edition=document.edition,
            )
        else:
            source = SourceReference(
                document_id="importer",
                standard="internal",
                edition="internal",
            )
    return ImportReviewItem(
        code=code,
        semantic_id=semantic_id,
        kind="semantic",
        source=source,
        expected_contract=message,
    )


def _clause_fact_blockers(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]:
    """Refuse a route whose clause facts are absent, not its own, incomplete or stale.

    Gated per fragment the draft actually carries: a draft that never extracted a supply
    clause gives the maintainer nothing to author from, so it must not be blocked for facts
    about a clause it does not hold. The legacy routes keep their branch authority in the
    recipe and are skipped here.
    """
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        LEGACY_BRANCH_AUTHORITY_RULE_IDS,
        SUPPLY_CLAUSES,
    )
    from insulation_coordination.rules.importer.review import (
        clause_fact_defect,
        fact_set_sha256,
        live_evidence_sha256,
    )

    fragments = {fragment.id: fragment for fragment in draft.raw_clause_fragments}
    blockers: list[ImportReviewItem] = []
    for spec in SUPPLY_CLAUSES:
        route = spec.semantic_id
        fragment = fragments.get(f"raw-{route}")
        if fragment is None or route in LEGACY_BRANCH_AUTHORITY_RULE_IDS:
            continue
        reviews = tuple(item for item in draft.clause_fact_reviews if item.rule_route == route)
        completions = tuple(
            item for item in draft.clause_fact_completions if item.rule_route == route
        )
        # Identity before evidence, the order ``axis_review_is_current`` keeps: a fact of the
        # wrong family, or one resting on someone else's clause, has perfectly current digests.
        defects = tuple(
            defect
            for item in reviews
            if (defect := clause_fact_defect(route, item.fact)) is not None
        )
        if not reviews:
            reason = "carries no authored clause fact"
        elif defects:
            reason = f"has a fact that {defects[0]}"
        elif len(completions) != 1:
            reason = "lacks one exact fact-set completion record"
        elif (
            completions[0].fragment_id != fragment.id
            or completions[0].fragment_sha256 != fragment.raw_sha256
        ):
            reason = "was completed against a superseded or foreign fragment"
        elif completions[0].fact_set_sha256 != fact_set_sha256(
            tuple(item.fact for item in reviews)
        ):
            reason = "was completed against a different fact set"
        elif any(
            item.evidence_sha256 != live_evidence_sha256(draft, item.fact.node_references)
            for item in reviews
        ):
            reason = "has a fact whose cited evidence has moved"
        else:
            continue
        blockers.append(
            _semantic_blocker(
                draft,
                code="CLAUSE_FACT_REVIEW_REQUIRED",
                semantic_id=route,
                message=f"clause fact review required: {route} {reason}",
            )
        )
    return tuple(blockers)


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
        semantic_id = (
            draft.review_items[0].semantic_id if draft.review_items else draft.manifest.version
        )
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
    for semantic_id in missing_required_curves(draft):
        blockers.append(
            _semantic_blocker(
                draft,
                code="CURVE_REQUIRED",
                semantic_id=semantic_id,
                message=(f"required curve {semantic_id} has no reviewed variants in the draft"),
            )
        )
    for semantic_id in incomplete_required_curve_variants(draft):
        blockers.append(
            _semantic_blocker(
                draft,
                code="CURVE_VARIANT_INVENTORY_REQUIRED",
                semantic_id=semantic_id,
                message=(
                    f"required curve {semantic_id} does not contain exactly the "
                    "recipe-declared source figures and selectors"
                ),
            )
        )
    from insulation_coordination.rules.importer.recipes import RECIPES

    required_curve_ids = {
        semantic_id for recipe in RECIPES for semantic_id in recipe.required_curves
    }
    for curve in (curve for curve in draft.curves if curve.id in required_curve_ids):
        for variant in curve.variants:
            if not _manual_curve_review_is_current(draft, variant):
                blockers.append(
                    _semantic_blocker(
                        draft,
                        code="CURVE_VARIANT_REVIEW_REQUIRED",
                        semantic_id=variant.id,
                        message=(
                            f"curve variant {variant.id} lacks one exact current manual review"
                        ),
                    )
                )
    blockers.extend(_clause_fact_blockers(draft))
    from insulation_coordination.rules.importer.review import axis_review_is_current

    for spec in (spec for recipe in RECIPES for spec in recipe.tables if spec.axis_selectors):
        grid_id = f"raw-{spec.semantic_id}"
        for axis_proposal in (
            item for item in draft.axis_selector_proposals if item.grid_id == grid_id
        ):
            # The same comparison the resolver uses, against the same live grid, so this gate
            # and ``resolve_confirmed_axis_selectors`` can never disagree about what counts as
            # a current review. A grid this draft no longer carries resolves no live evidence,
            # so every review of it reads as stale and the position blocks.
            exact = tuple(
                review
                for review in draft.axis_selector_reviews
                if axis_review_is_current(review, axis_proposal, draft)
            )
            if len(exact) != 1:
                blockers.append(
                    _semantic_blocker(
                        draft,
                        code="AXIS_SELECTOR_REVIEW_REQUIRED",
                        semantic_id=spec.semantic_id,
                        message=(
                            f"{spec.semantic_id} {axis_proposal.axis} position "
                            f"{axis_proposal.index} lacks one exact axis selector review"
                        ),
                    )
                )
    return tuple(blockers)


def incomplete_required_curve_variants(draft: ImportedRuleDraft) -> tuple[str, ...]:
    """Required curves whose current variants differ from the recipe inventory."""

    incomplete: set[str] = set()
    curves_by_id: dict[str, list[PiecewiseCurveRule]] = {}
    for curve in draft.curves:
        curves_by_id.setdefault(curve.id, []).append(curve)
    for recipe in _recipes():
        for semantic_id in recipe.required_curves:
            specs = tuple(spec for spec in recipe.curves if spec.semantic_id == semantic_id)
            if not specs or semantic_id not in curves_by_id:
                continue
            curves = curves_by_id[semantic_id]
            expected = Counter(
                (
                    recipe.standard,
                    recipe.edition,
                    spec.figure,
                    selector,
                )
                for spec in specs
                for selector in spec.variant_slots
            )
            actual = Counter(
                (
                    variant.source.standard,
                    variant.source.edition,
                    variant.source.figure,
                    variant.selector,
                )
                for curve in curves
                for variant in curve.variants
            )
            if len(curves) != 1 or actual != expected:
                incomplete.add(semantic_id)
    return tuple(sorted(incomplete))


def missing_required_curves(draft: ImportedRuleDraft) -> tuple[str, ...]:
    """Recipe-declared curve semantics with no reviewed curve rule in the draft."""

    from insulation_coordination.rules.importer.recipes import RECIPES

    present = {curve.id for curve in draft.curves}
    required = {semantic_id for recipe in RECIPES for semantic_id in recipe.required_curves}
    return tuple(semantic_id for semantic_id in sorted(required) if semantic_id not in present)


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
    _require_complete_inventory(draft)
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
