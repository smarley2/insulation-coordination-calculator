from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from insulation_coordination.domain.rules import DraftRulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approve_draft,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    ExtractionError,
    ImportedRuleDraft,
    ImportReviewItem,
    _content_digest,
    _largest_numeric_rectangle,
    extract_draft,
)
from insulation_coordination.rules.importer.identify import (
    AmbiguousStandardError,
    UnsupportedStandardError,
    identify_standard,
)
from tests.fixtures.synthetic_rules import (
    synthetic_hf_rule_package,
    synthetic_part1_rule_package,
)


def _pdf_string(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode(
        "latin-1"
    )


def create_pdf(
    path: Path,
    *,
    title: str,
    lines: tuple[str, ...],
    payload: dict[str, object] | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    commands = [b"BT /F1 10 Tf 72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append(b"0 -16 Td")
        commands.append(b"(" + _pdf_string(line) + b") Tj")
    if payload is not None:
        encoded = base64.b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        commands.extend(
            (
                b"0 -16 Td",
                b"(ICC-SYNTHETIC-RULES-BEGIN) Tj",
                b"0 -16 Td",
                b"(" + encoded.encode() + b") Tj",
                b"0 -16 Td",
                b"(ICC-SYNTHETIC-RULES-END) Tj",
            )
        )
    commands.append(b"ET")
    stream.set_data(b"\n".join(commands))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {"/Title": title, "/ICC-Synthetic": "true", **(metadata or {})}
    )
    with path.open("wb") as target:
        writer.write(target)


@pytest.fixture
def synthetic_part1_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "part1.pdf"
    create_pdf(
        path,
        title="IEC 60664-1:2020 synthetic extraction fixture",
        lines=(
            "IEC 60664-1",
            "Edition 3.0 2020-05",
            "low-voltage supply systems",
        ),
    )
    return path


def _replace_source_identity(
    value: object, *, standard: str, edition: str
) -> object:
    if isinstance(value, dict):
        changed = {
            key: _replace_source_identity(item, standard=standard, edition=edition)
            for key, item in value.items()
        }
        if "standard" in changed and "edition" in changed:
            changed["standard"] = standard
            changed["edition"] = edition
        return changed
    if isinstance(value, list):
        return [
            _replace_source_identity(item, standard=standard, edition=edition)
            for item in value
        ]
    return value


def _payload(
    *,
    tables: object,
    formulas: object,
    mappings: object,
    standard: str,
    edition: str,
) -> dict[str, object]:
    return _replace_source_identity(
        {"tables": tables, "formulas": formulas, "mappings": mappings},
        standard=standard,
        edition=edition,
    )


@pytest.fixture
def supported_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    part1_package = synthetic_part1_rule_package()
    complete_package = synthetic_hf_rule_package()
    part1_table_count = len(part1_package.tables)
    part1_formula_count = len(part1_package.formulas)
    part1_mapping_count = len(part1_package.mappings)
    part1 = tmp_path / "part1.pdf"
    part4 = tmp_path / "part4.pdf"
    create_pdf(
        part1,
        title="IEC 60664-1:2020 synthetic extraction fixture",
        lines=(
            "IEC 60664-1",
            "Edition 3.0 2020-05",
            "low-voltage supply systems",
        ),
        payload=_payload(
            tables=[
                item.model_dump(mode="json") for item in part1_package.tables
            ],
            formulas=[
                item.model_dump(mode="json") for item in part1_package.formulas
            ],
            mappings=[
                item.model_dump(mode="json") for item in part1_package.mappings
            ],
            standard="IEC 60664-1",
            edition="2020",
        ),
    )
    create_pdf(
        part4,
        title="IEC 60664-4:2005 synthetic extraction fixture",
        lines=(
            "IEC 60664-4",
            "first edition 2005",
            "high-frequency voltage stress",
        ),
        payload=_payload(
            tables=[
                item.model_dump(mode="json")
                for item in complete_package.tables[part1_table_count:]
            ],
            formulas=[
                item.model_dump(mode="json")
                for item in complete_package.formulas[part1_formula_count:]
            ],
            mappings=[
                item.model_dump(mode="json")
                for item in complete_package.mappings[part1_mapping_count:]
            ],
            standard="IEC 60664-4",
            edition="2005",
        ),
    )
    return part1, part4


def test_identifies_supported_synthetic_document(synthetic_part1_pdf: Path) -> None:
    identity = identify_standard(synthetic_part1_pdf)

    assert identity.standard == "IEC 60664-1"
    assert identity.edition == "2020"
    assert len(identity.sha256) == 64


def test_unknown_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unknown.pdf"
    create_pdf(path, title="Unrelated", lines=("Unrelated document",))

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_metadata_and_all_independent_anchors_are_required(tmp_path: Path) -> None:
    missing_anchor = tmp_path / "missing-anchor.pdf"
    create_pdf(
        missing_anchor,
        title="IEC 60664-1:2020 synthetic extraction fixture",
        lines=("IEC 60664-1", "Edition 3.0 2020-05"),
    )
    unsupported_edition = tmp_path / "unsupported-edition.pdf"
    create_pdf(
        unsupported_edition,
        title="IEC 60664-1:2007 synthetic extraction fixture",
        lines=(
            "IEC 60664-1",
            "Edition 2.0 2007",
            "low-voltage supply systems",
        ),
    )

    with pytest.raises(UnsupportedStandardError):
        identify_standard(missing_anchor)
    with pytest.raises(UnsupportedStandardError):
        identify_standard(unsupported_edition)


def test_document_matching_two_recipes_is_rejected_as_ambiguous(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.pdf"
    create_pdf(
        path,
        title="IEC 60664-1:2020 IEC 60664-4:2005 synthetic fixture",
        lines=(
            "IEC 60664-1",
            "Edition 3.0 2020-05",
            "low-voltage supply systems",
            "IEC 60664-4",
            "first edition",
            "high-frequency voltage stress",
        ),
    )

    with pytest.raises(AmbiguousStandardError):
        identify_standard(path)


def test_contradictory_standard_metadata_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "contradictory.pdf"
    create_pdf(
        path,
        title="IEC 60664-1:2020 synthetic extraction fixture",
        lines=(
            "IEC 60664-1",
            "Edition 3.0 2020-05",
            "low-voltage supply systems",
        ),
        metadata={"/Subject": "IEC 60664-4:2005"},
    )

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_metadata_claiming_an_unsupported_edition_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "contradictory-edition.pdf"
    create_pdf(
        path,
        title="Synthetic extraction fixture",
        lines=(
            "IEC 60664-1",
            "Edition 3.0 2020-05",
            "low-voltage supply systems",
        ),
        metadata={
            "/Subject": "IEC 60664-1:2019",
            "/CreationDate": "D:20260731",
            "/Producer": "Synthetic fixture",
        },
    )

    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)


def test_equally_plausible_numeric_grid_regions_are_rejected() -> None:
    raw = [
        ["1", None, "2"],
        ["3", None, "4"],
    ]

    with pytest.raises(ExtractionError, match="ambiguous"):
        _largest_numeric_rectangle(raw)


def test_extracts_combined_content_into_an_unusable_audited_draft(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)

    assert draft.manifest.approved is False
    assert draft.manifest.compatible is False
    assert draft.review_items == ()
    assert {source.standard for source in draft.manifest.source_documents} == {
        "IEC 60664-1",
        "IEC 60664-4",
    }
    assert len(draft.tables) == 16
    assert len(draft.formulas) == 18
    assert len(draft.mappings) > 20
    assert all(mapping.approved is False for mapping in draft.mappings)
    extraction_notes = {
        record.notes
        for record in draft.manifest.approval_records
        if record.action == "extraction"
    }
    assert {f"table:{table.id}" for table in draft.tables} <= extraction_notes
    assert {f"formula:{formula.id}" for formula in draft.formulas} <= extraction_notes
    assert {f"mapping:{mapping.id}" for mapping in draft.mappings} <= extraction_notes
    serialized = draft.model_dump_json().encode()
    assert b"%PDF" not in serialized
    assert b"ICC-SYNTHETIC-RULES-BEGIN" not in serialized


def test_pending_manual_review_item_blocks_approval(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    content = draft.model_dump(mode="python")
    content.pop("review_items")
    pending = ImportedRuleDraft(
        **content,
        review_items=(
            ImportReviewItem(
                code="MANUAL_RULE_DEFINITION_REQUIRED",
                semantic_id="synthetic-pending-rule",
                kind="formula",
                source=draft.formulas[0].source,
            ),
        ),
    )

    with pytest.raises(ApprovalError, match="manual review"):
        approve_draft(pending, approver="Reviewer", notes="Cannot bypass review")


def test_import_review_cannot_be_erased_by_plain_draft_conversion(
    supported_pdfs: tuple[Path, Path],
) -> None:
    imported = extract_draft(supported_pdfs)
    plain = DraftRulePackage(
        manifest=imported.manifest,
        tables=imported.tables,
        formulas=imported.formulas,
        mappings=imported.mappings,
    )

    with pytest.raises(ApprovalError, match="imported draft"):
        approve_draft(plain, approver="Reviewer", notes="Cannot erase review state")
    with pytest.raises(ApprovalError, match="imported draft"):
        record_correction(
            imported,
            plain,
            actor="Reviewer",
            notes="Cannot erase review state",
        )


def test_review_item_requires_matching_typed_content_before_resolution(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    pending = draft.model_copy(
        update={
            "review_items": (
                ImportReviewItem(
                    code="MANUAL_RULE_DEFINITION_REQUIRED",
                    semantic_id="required-formula-id",
                    kind="formula",
                    source=draft.formulas[0].source,
                ),
            )
        }
    )
    pending_digest = _content_digest(
        pending.tables,
        pending.formulas,
        pending.mappings,
        pending.review_items,
    )
    pending = pending.model_copy(
        update={
            "manifest": pending.manifest.model_copy(
                update={
                    "approval_records": tuple(
                        record.model_copy(update={"notes": f"content:{pending_digest}"})
                        if record.notes.startswith("content:")
                        else record
                        for record in pending.manifest.approval_records
                    )
                }
            )
        }
    )
    table = pending.tables[0]
    unrelated = pending.model_copy(
        update={
            "review_items": (),
            "tables": (
                table.model_copy(
                    update={
                        "cells": (
                            table.cells[0].model_copy(
                                update={"value": table.cells[0].value + 1}
                            ),
                            *table.cells[1:],
                        )
                    }
                ),
                *pending.tables[1:],
            ),
        }
    )

    with pytest.raises(ApprovalError, match="review resolution"):
        record_correction(
            pending,
            unrelated,
            actor="Reviewer",
            notes="Unrelated content must not resolve a formula review",
        )


def test_missing_or_duplicate_supported_part_is_rejected(
    supported_pdfs: tuple[Path, Path],
) -> None:
    part1, part4 = supported_pdfs

    with pytest.raises(ExtractionError, match="exactly one"):
        extract_draft((part1,))
    with pytest.raises(ExtractionError, match="duplicate"):
        extract_draft((part1, part1, part4))


def test_manual_correction_returns_new_draft_and_appends_immutable_audit(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    table = draft.tables[0]
    corrected_table = table.model_copy(
        update={
            "cells": (
                table.cells[0].model_copy(update={"value": table.cells[0].value + 1}),
                *table.cells[1:],
            )
        }
    )
    corrected_content = draft.model_copy(
        update={"tables": (corrected_table, *draft.tables[1:])}
    )

    corrected = record_correction(
        draft,
        corrected_content,
        actor="Synthetic Reviewer",
        notes=f"table:{table.id}:cell:0:0",
    )

    assert draft.tables[0].cells[0].value != corrected.tables[0].cells[0].value
    assert (
        corrected.manifest.approval_records[:-2]
        == draft.manifest.approval_records
    )
    assert corrected.manifest.approval_records[-2].notes == f"table:{table.id}"
    assert corrected.manifest.approval_records[-1].action == "correction"


def test_deleted_content_receives_an_item_level_correction_audit(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    removed = draft.tables[0]
    changed = draft.model_copy(update={"tables": draft.tables[1:]})

    corrected = record_correction(
        draft,
        changed,
        actor="Synthetic Reviewer",
        notes="Remove a reviewed synthetic table",
    )

    assert corrected.manifest.approval_records[-2].notes == f"table:{removed.id}"


def test_unlogged_content_change_cannot_be_approved(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    table = draft.tables[0]
    changed = draft.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "cells": (
                            table.cells[0].model_copy(
                                update={"value": table.cells[0].value + 1}
                            ),
                            *table.cells[1:],
                        )
                    }
                ),
                *draft.tables[1:],
            )
        }
    )
    corrected = record_correction(
        draft,
        changed,
        actor="Synthetic Reviewer",
        notes=f"table:{table.id}:cell:0:0",
    )

    with pytest.raises(ApprovalError, match="unlogged"):
        approve_draft(changed, approver="Reviewer", notes="Must reject")
    assert approve_draft(
        corrected,
        approver="Reviewer",
        notes="Logged synthetic correction reviewed.",
    ).manifest.approved


def test_approval_runs_full_validation_and_archive_no_longer_needs_pdfs(
    supported_pdfs: tuple[Path, Path], tmp_path: Path
) -> None:
    draft = extract_draft(supported_pdfs)

    approved = approve_draft(
        draft,
        approver="Synthetic Reviewer",
        notes="All synthetic extraction checks reviewed.",
    )
    archive = tmp_path / "approved.icrules"
    write_rule_package(archive, approved)
    for source_pdf in supported_pdfs:
        source_pdf.unlink()

    loaded = load_rule_package(archive)
    assert loaded.manifest.approved is True
    assert loaded.manifest.compatible is True
    assert all(mapping.approved for mapping in loaded.mappings)
    assert loaded.manifest.approval_records[-1].action == "approval"


def test_approval_cannot_bypass_failed_table_audit(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    incomplete = draft.model_copy(
        update={
            "tables": (
                draft.tables[0].model_copy(
                    update={"cells": draft.tables[0].cells[:-1]}
                ),
                *draft.tables[1:],
            )
        }
    )

    with pytest.raises(ApprovalError, match="table_cells"):
        approve_draft(incomplete, approver="Reviewer", notes="Must not bypass")


def test_approval_rejects_deleted_audit_and_missing_part4_mapping(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    missing_audit = draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={
                    "approval_records": draft.manifest.approval_records[1:]
                }
            )
        }
    )
    missing_mapping = draft.model_copy(
        update={
            "mappings": tuple(
                mapping
                for mapping in draft.mappings
                if not mapping.source_rule_id.startswith("iec60664-4:")
            )
        }
    )

    with pytest.raises(ApprovalError, match="incomplete"):
        approve_draft(missing_audit, approver="Reviewer", notes="No bypass")
    with pytest.raises(ApprovalError, match="exact compatibility"):
        approve_draft(missing_mapping, approver="Reviewer", notes="No bypass")


def test_approval_requires_every_declared_compatibility_route(
    supported_pdfs: tuple[Path, Path],
) -> None:
    draft = extract_draft(supported_pdfs)
    incomplete = draft.model_copy(update={"mappings": draft.mappings[:-1]})

    with pytest.raises(ApprovalError, match="exact compatibility"):
        approve_draft(incomplete, approver="Reviewer", notes="No partial family")
