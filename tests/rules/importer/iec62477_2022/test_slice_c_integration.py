"""Public synthetic Slice C reference, archive, and evaluation integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    SourceGeometryReference,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.evaluator import evaluate_piecewise_curve
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    approve_draft,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    _content_digest,
    extract_draft,
)
from insulation_coordination.rules.importer.review import mark_proposal_reviewed
from insulation_coordination.rules.validation import validate_rule_package
from tests.fixtures.synthetic_pdf import create_geometry_pdf
from tests.fixtures.synthetic_rules import synthetic_rule_package
from tests.rules.test_importer import _review_all, _test_recipes


def _result(package, code: str):
    return next(item for item in validate_rule_package(package).results if item.code == code)


def _reference_decision(curve_id, source):
    return DecisionRule(
        id="synthetic-slice-c-reference",
        inputs=(
            DecisionInput(
                name="synthetic_case",
                kind="categorical",
                allowed_values=("curve",),
            ),
        ),
        outputs=(DecisionOutput(name="target", kind="reference"),),
        rows=(
            DecisionRow(
                matchers=(Matcher(input="synthetic_case", op="equals", values=("curve",)),),
                values=(DecisionValue(name="target", reference=curve_id),),
                source=source,
            ),
        ),
        exhaustive=True,
        source=source,
    )


def _referencing_package():
    package = synthetic_rule_package()
    curve = package.curves[0]
    reference = _reference_decision(curve.id, package.decisions[0].source)
    return package.model_copy(
        update={
            "decisions": (*package.decisions, reference),
            "checksums": {},
            "package_sha256": None,
        }
    )


def _synthetic_import_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    documents = (
        (
            "part1.pdf",
            "IEC 60664-1",
            "2020",
            "Edition 3.0 2020-05",
            "synthetic low-voltage geometry",
            "Table S1",
        ),
        (
            "part4.pdf",
            "IEC 60664-4",
            "2005",
            "first edition 2005",
            "synthetic high-frequency geometry",
            "Table S4",
        ),
        (
            "part62477.pdf",
            "IEC 62477-1",
            "2022",
            "Edition 2.0 2022-05",
            "synthetic power conversion geometry",
            "Table S9",
        ),
    )
    paths: list[Path] = []
    for filename, standard, edition, edition_anchor, topic_anchor, table_anchor in documents:
        path = tmp_path / filename
        create_geometry_pdf(
            path,
            standard=standard,
            edition=edition,
            edition_anchor=edition_anchor,
            topic_anchor=topic_anchor,
            table_anchor=table_anchor,
        )
        paths.append(path)
    return paths[0], paths[1], paths[2]


def _with_slice_c_review_inventory(imported: ImportedRuleDraft) -> ImportedRuleDraft:
    source = imported.review_items[0].source
    items = tuple(
        ImportReviewItem(
            code=code,
            semantic_id=semantic_id,
            kind="semantic",
            source=source.model_copy(
                update={"geometry": SourceGeometryReference(artifact_sha256=artifact_sha256)}
            ),
            expected_contract=f"synthetic:{semantic_id}",
        )
        for code, semantic_id, artifact_sha256 in (
            ("SYNTHETIC_SLICE_C_REFERENCE", "synthetic-slice-c-reference", "a" * 64),
            (
                "SYNTHETIC_SLICE_C_CURVE",
                "synthetic-fault-time-voltage",
                "b" * 64,
            ),
        )
    )
    resolutions = tuple(
        ImportReviewResolution(
            review_item_sha256=item.sha256,
            actor="Synthetic Reviewer",
            recorded_at=datetime(2026, 8, 9, tzinfo=UTC),
            notes="Reviewed synthetic Slice C source artifact.",
        )
        for item in items
    )
    changed = imported.model_copy(
        update={
            "review_items": (*imported.review_items, *items),
            "review_resolutions": (*imported.review_resolutions, *resolutions),
        }
    )
    digest = _content_digest(
        changed.tables,
        changed.formulas,
        changed.mappings,
        changed.review_items,
        changed.raw_grids,
        changed.raw_clause_fragments,
        changed.manifest.source_documents,
        changed.source_identities,
        changed.review_resolutions,
        changed.extracted_equations,
    )
    return changed.model_copy(
        update={
            "manifest": changed.manifest.model_copy(
                update={
                    "approval_records": tuple(
                        record.model_copy(update={"notes": f"content:{digest}"})
                        if record.action == "extraction" and record.notes.startswith("content:")
                        else record
                        for record in changed.manifest.approval_records
                    )
                }
            )
        }
    )


def test_curve_reference_resolves_round_trips_and_evaluates(tmp_path) -> None:
    package = _referencing_package()
    curve_reference = next(
        value.reference
        for decision in package.decisions
        for row in decision.rows
        for value in row.values
        if value.reference == package.curves[0].id
    )
    curve_by_id = {curve.id: curve for curve in package.curves}

    assert curve_by_id[curve_reference] is package.curves[0]
    assert _result(package, "SEMANTIC_REFERENCES_RESOLVE").passed is True

    path = tmp_path / "synthetic-slice-c.icrules"
    write_rule_package(path, package)
    reloaded = load_rule_package(path)
    assert reloaded.curves == package.curves
    variant = reloaded.curves[0].variants[0]
    result = evaluate_piecewise_curve(reloaded.curves[0], variant.selector, Decimal(27))
    assert result.status == "matched"


def test_reviewed_synthetic_draft_approves_reference_and_curve_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipes = _test_recipes()
    monkeypatch.setattr(recipe_registry, "RECIPES", recipes)
    imported = extract_draft(_synthetic_import_paths(tmp_path))
    reviewed = _review_all(_with_slice_c_review_inventory(imported), recipes)
    source = reviewed.tables[0].source
    fixture_curve = synthetic_rule_package().curves[0]
    variant = fixture_curve.variants[0].model_copy(update={"source": source})
    curve = fixture_curve.model_copy(update={"source": source, "variants": (variant,)})
    decision = _reference_decision(curve.id, source)
    changed = reviewed.model_copy(
        update={
            "decisions": (*reviewed.decisions, decision),
            "curves": (*reviewed.curves, curve),
        }
    )
    reviewed = record_correction(
        reviewed,
        changed,
        actor="Synthetic Reviewer",
        notes="Add synthetic Slice C reference and curve.",
    )
    for proposal in reviewed.semantic_proposals:
        if proposal.state == "proposed":
            reviewed = mark_proposal_reviewed(
                reviewed,
                proposal.semantic_id,
                actor="Synthetic Reviewer",
                notes="Review synthetic Slice C semantic rule.",
            )

    approved = approve_draft(
        reviewed,
        approver="Synthetic Reviewer",
        notes="Approve synthetic Slice C integration.",
    )
    archive = tmp_path / "approved-synthetic-slice-c.icrules"
    write_rule_package(archive, approved)
    reloaded = load_rule_package(archive)

    assert (
        next(value.reference for row in reloaded.decisions[-1].rows for value in row.values)
        == curve.id
    )
    assert reloaded.curves[-1] == approved.curves[-1]
    result = evaluate_piecewise_curve(reloaded.curves[-1], variant.selector, Decimal(27))
    assert result.status == "matched"


def test_missing_or_ambiguous_semantic_reference_fails_exact_resolution() -> None:
    package = _referencing_package()
    decision = package.decisions[-1]
    dangling = decision.model_copy(
        update={
            "rows": (
                decision.rows[0].model_copy(
                    update={
                        "values": (
                            decision.rows[0]
                            .values[0]
                            .model_copy(update={"reference": "synthetic-missing"}),
                        )
                    }
                ),
            )
        }
    )
    duplicate_formula = package.formulas[0].model_copy(update={"id": package.curves[0].id})
    ambiguous = package.model_copy(update={"formulas": (*package.formulas, duplicate_formula)})

    assert (
        _result(
            package.model_copy(update={"decisions": (*package.decisions[:-1], dangling)}),
            "SEMANTIC_REFERENCES_RESOLVE",
        ).passed
        is False
    )
    assert _result(ambiguous, "SEMANTIC_REFERENCES_RESOLVE").passed is False
