from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    DraftRulePackage,
    RulePackage,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.archive import _archive_bytes
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    _content_digest,
)
from insulation_coordination.rules.validation import validate_rule_package

_EXPECTED_SOURCES = {
    ("IEC 60664-1", "2020"),
    ("IEC 60664-4", "2005"),
}
_EXPECTED_DRAFT_FAILURES = {
    "approval",
    "approval_record",
    "compatibility",
    "checksums",
    "package_digest",
}


class ApprovalError(RulePackageError):
    """A draft has not satisfied every non-bypassable approval gate."""


def _review_key(item: ImportReviewItem) -> tuple[str, str, str]:
    return (item.code, item.semantic_id, item.kind)


def _source_matches(actual: SourceReference, expected: SourceReference) -> bool:
    return all(
        getattr(actual, field) == getattr(expected, field)
        for field in ("standard", "edition", "clause", "table", "figure")
    )


def _review_resolution_exists(
    item: ImportReviewItem, changed: ImportedRuleDraft
) -> bool:
    if item.kind == "table":
        return any(
            table.id == item.semantic_id
            and _source_matches(table.source, item.source)
            for table in changed.tables
        )
    if item.kind == "formula":
        return any(
            formula.id == item.semantic_id
            and _source_matches(formula.source, item.source)
            for formula in changed.formulas
        )
    return any(
        mapping.source_rule_id == item.semantic_id
        and _source_matches(mapping.source, item.source)
        for mapping in changed.mappings
    )


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
    return tuple(tokens)


def _require_valid_review_resolutions(
    original: ImportedRuleDraft,
    changed: ImportedRuleDraft,
) -> tuple[ImportReviewItem, ...]:
    original_by_key = {_review_key(item): item for item in original.review_items}
    changed_keys = {_review_key(item) for item in changed.review_items}
    if not changed_keys <= set(original_by_key):
        raise ApprovalError("a correction cannot add or rewrite manual review items")
    removed = tuple(
        item
        for key, item in original_by_key.items()
        if key not in changed_keys
    )
    if any(not _review_resolution_exists(item, changed) for item in removed):
        raise ApprovalError("manual review resolution lacks matching typed content")
    return removed


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
) -> ImportedRuleDraft:
    """Return corrected content with immutable item and content audits appended."""

    original = _validated_draft(draft)
    changed = _validated_draft(corrected)
    if not actor.strip() or not notes.strip():
        raise ApprovalError("correction actor and notes are required")
    if changed.manifest.source_documents != original.manifest.source_documents:
        raise ApprovalError("a correction cannot change recognized source documents")
    if changed.manifest.approval_records != original.manifest.approval_records:
        raise ApprovalError("a correction cannot rewrite prior audit records")
    if changed.raw_grids != original.raw_grids:
        raise ApprovalError("a correction cannot rewrite extracted raw grids")
    if (
        changed.tables,
        changed.formulas,
        changed.mappings,
    ) == (
        original.tables,
        original.formulas,
        original.mappings,
    ):
        raise ApprovalError("a correction must change rule content")
    _require_logged_content(original)
    _require_valid_review_resolutions(original, changed)
    original_reviews = original.review_items
    changed_reviews = changed.review_items
    corrected_mappings = tuple(
        mapping.model_copy(update={"approved": False})
        for mapping in changed.mappings
    )
    before = _content_digest(
        original.tables,
        original.formulas,
        original.mappings,
        original_reviews,
        original.raw_grids,
    )
    after = _content_digest(
        changed.tables,
        changed.formulas,
        corrected_mappings,
        changed_reviews,
        changed.raw_grids,
    )
    recorded_at = datetime.now(UTC)
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
        raw_grids=changed.raw_grids,
    )


def _require_complete_audit(draft: DraftRulePackage) -> None:
    audited = {
        record.notes
        for record in draft.manifest.approval_records
        if (
            record.action == "extraction"
            and record.actor == f"icc-importer/{IMPORTER_VERSION}"
        )
        or record.action == "correction"
    }
    required = {
        "identity:iec60664-1-2020",
        "layout:iec60664-1-2020",
        "identity:iec60664-4-2005",
        "layout:iec60664-4-2005",
    }
    required.update(f"table:{table.id}" for table in draft.tables)
    required.update(f"formula:{formula.id}" for formula in draft.formulas)
    required.update(f"mapping:{mapping.id}" for mapping in draft.mappings)
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
    )
    if actual != expected:
        raise ApprovalError("draft contains an unlogged content change")


def _require_compatibility_mapping(draft: DraftRulePackage) -> None:
    routes = tuple(mapping.source_rule_id for mapping in draft.mappings)
    if len(routes) != len(set(routes)):
        raise ApprovalError("compatibility mappings are ambiguous")
    from insulation_coordination.rules.importer.recipes import RECIPES

    required = {
        spec.semantic_route
        for recipe in RECIPES
        for spec in recipe.mappings
    }
    missing = required - set(routes)
    if missing:
        raise ApprovalError("exact compatibility mapping family is incomplete")


def _require_resolved_recipe_semantics(draft: ImportedRuleDraft) -> None:
    if not any(
        record.action == "extraction" and record.notes.startswith("review:")
        for record in draft.manifest.approval_records
    ):
        return
    from insulation_coordination.rules.importer.recipes import RECIPES

    table_specs = tuple(spec for recipe in RECIPES for spec in recipe.tables)
    formula_specs = tuple(spec for recipe in RECIPES for spec in recipe.formulas)
    tables = {table.id: table for table in draft.tables}
    formulas = {formula.id: formula for formula in draft.formulas}
    grids = {grid.id: grid for grid in draft.raw_grids}
    tables_valid = all(
        (table := tables.get(spec.semantic_id)) is not None
        and table.unit == spec.target_unit
        and table.source.clause == spec.clause
        and table.source.table == spec.source_table
        and (grid := grids.get(f"raw-{spec.semantic_id}")) is not None
        and (grid.rows, grid.columns)
        == (spec.expected_raw_rows, spec.expected_raw_columns)
        and grid.target_unit == spec.target_unit
        for spec in table_specs
    )
    formulas_valid = all(
        (formula := formulas.get(spec.semantic_id)) is not None
        and formula.unit == spec.unit
        and formula.source.clause == spec.clause
        and formula.source.table == spec.table
        and formula.source.figure == spec.figure
        for spec in formula_specs
    )
    if not tables_valid or not formulas_valid:
        raise ApprovalError(
            "reviewed tables and formulas do not satisfy exact recipe semantics"
        )


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
    source_keys = {
        (source.standard, source.edition)
        for source in draft.manifest.source_documents
    }
    if source_keys != _EXPECTED_SOURCES or len(draft.manifest.source_documents) != 2:
        raise ApprovalError("exact supported Part 1 and Part 4 sources are required")
    if isinstance(draft, ImportedRuleDraft) and draft.review_items:
        raise ApprovalError("draft has unresolved manual review items")
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
        mappings=tuple(
            mapping.model_copy(update={"approved": True})
            for mapping in draft.mappings
        ),
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
        failures = ", ".join(
            result.code for result in report.results if not result.passed
        )
        raise ApprovalError(f"approval validation failed: {failures}")
    return candidate
