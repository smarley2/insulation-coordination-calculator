from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    MAX_APPLICABILITY_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    MAX_LATEX_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_REFERENCE_TEXT_LENGTH,
    RULE_SCHEMA_VERSION,
    DraftRulePackage,
    RulePackage,
    RulePackageError,
    SourceReference,
)
from insulation_coordination.rules.archive import (
    MAX_ARCHIVE_BYTES,
    load_rule_package,
    migrate_rule_package,
    write_rule_package,
)
from insulation_coordination.rules.evaluator import evaluate_piecewise_curve
from insulation_coordination.rules.importer.extract import IMPORTER_VERSION


def test_approved_package_loads_without_source_pdfs(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "company.icrules"

    digest = write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)

    assert loaded.manifest.approved is True
    assert loaded.package_sha256 == digest
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.curves == synthetic_package.curves
    variant = loaded.curves[0].variants[0]
    result = evaluate_piecewise_curve(loaded.curves[0], variant.selector, variant.points[0].x)
    assert result.value is not None
    assert result.value == variant.points[0].y


def test_unknown_formula_operator_is_rejected(package_dict: dict[str, object]) -> None:
    formulas = package_dict["formulas"]
    assert isinstance(formulas, list)
    formulas[0]["expression"] = {"op": "python", "code": "open('x')"}

    with pytest.raises(RulePackageError, match="unknown operator"):
        RulePackage.model_validate(package_dict)


def test_formula_nodes_reject_extra_fields(package_dict: dict[str, object]) -> None:
    formulas = package_dict["formulas"]
    assert isinstance(formulas, list)
    formulas[0]["expression"]["script"] = "open('x')"

    with pytest.raises(RulePackageError, match="script"):
        RulePackage.model_validate(package_dict)


def test_extra_fields_cannot_be_caller_enabled(package_dict: dict[str, object]) -> None:
    package_dict["payload"] = "must never be ignored"

    with pytest.raises(RulePackageError, match="payload"):
        RulePackage.model_validate(package_dict, extra="ignore")


def test_archive_is_byte_deterministic_and_has_only_canonical_members(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    first = tmp_path / "first.icrules"
    second = tmp_path / "second.icrules"

    assert write_rule_package(first, synthetic_package) == write_rule_package(
        second, synthetic_package
    )
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "tables.json",
            "formulas.json",
            "mappings.json",
            "decisions.json",
            "procedures.json",
            "guidance.json",
            "curves.json",
            "checksums.json",
        ]
        assert {member.date_time for member in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        checksums = json.loads(archive.read("checksums.json"))
        assert set(checksums) == {
            "manifest.json",
            "tables.json",
            "formulas.json",
            "mappings.json",
            "decisions.json",
            "procedures.json",
            "guidance.json",
            "curves.json",
        }


def test_curves_survive_round_trip_as_typed_final_rules(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "curves.icrules"

    write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)

    assert loaded.curves == synthetic_package.curves
    with zipfile.ZipFile(path) as archive:
        checksums = json.loads(archive.read("checksums.json"))
        payload = json.loads(archive.read("curves.json"))
    assert "curves.json" in checksums
    assert set(payload[0]) == {"id", "source", "variants"}
    assert set(payload[0]["variants"][0]) == {
        "applicability",
        "id",
        "points",
        "reviewed_artifact_sha256",
        "segments",
        "selector",
        "source",
        "x_axis",
        "y_axis",
    }
    assert all(set(point) == {"x", "y"} for point in payload[0]["variants"][0]["points"])
    assert "semantic_proposals" not in payload[0]
    assert "raw_grids" not in payload[0]


def test_load_rejects_curve_payload_changed_without_checksum_update(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "tampered-curve.icrules"
    write_rule_package(path, synthetic_package)
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    curves = json.loads(members["curves.json"])
    curves[0]["id"] = "tampered-curve"
    members["curves.json"] = _canonical_json(curves)
    _write_members(path, members)

    with pytest.raises(RulePackageError, match="checksum mismatch for curves.json"):
        load_rule_package(path)


def test_load_rejects_changed_member_even_when_zip_is_readable(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "changed.icrules"
    write_rule_package(path, synthetic_package)
    with zipfile.ZipFile(path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["version"] = "tampered"
    members["manifest.json"] = json.dumps(manifest).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as changed:
        for name, content in members.items():
            changed.writestr(name, content)
    path.write_bytes(buffer.getvalue())

    with pytest.raises(RulePackageError, match="checksum"):
        load_rule_package(path)


def test_load_rejects_extra_archive_members(synthetic_package: RulePackage, tmp_path: Path) -> None:
    path = tmp_path / "extra.icrules"
    write_rule_package(path, synthetic_package)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("payload.py", "open('x')")

    with pytest.raises(RulePackageError, match="members"):
        load_rule_package(path)


def test_load_rejects_missing_and_duplicate_archive_members(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    original = tmp_path / "original.icrules"
    write_rule_package(original, synthetic_package)
    with zipfile.ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}

    missing = tmp_path / "missing.icrules"
    with zipfile.ZipFile(missing, "w") as archive:
        for name, content in members.items():
            if name != "tables.json":
                archive.writestr(name, content)
    with pytest.raises(RulePackageError, match="members"):
        load_rule_package(missing)

    duplicate = tmp_path / "duplicate.icrules"
    duplicate.write_bytes(original.read_bytes())
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(duplicate, "a") as archive,
    ):
        archive.writestr("tables.json", members["tables.json"])
    with pytest.raises(RulePackageError, match="members"):
        load_rule_package(duplicate)


def test_load_rejects_malformed_checksum_set_and_unsupported_schema(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    original = tmp_path / "original.icrules"
    write_rule_package(original, synthetic_package)
    with zipfile.ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}

    checksums = json.loads(members["checksums.json"])
    checksums.pop("tables.json")
    members["checksums.json"] = _canonical_json(checksums)
    malformed = tmp_path / "malformed-checksums.icrules"
    _write_members(malformed, members)
    with pytest.raises(RulePackageError, match="exactly"):
        load_rule_package(malformed)

    with zipfile.ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = RULE_SCHEMA_VERSION + 1
    members["manifest.json"] = _canonical_json(manifest)
    checksums = json.loads(members["checksums.json"])
    checksums["manifest.json"] = hashlib.sha256(members["manifest.json"]).hexdigest()
    members["checksums.json"] = _canonical_json(checksums)
    future = tmp_path / "future.icrules"
    _write_members(future, members)
    with pytest.raises(RulePackageError, match="unsupported schema"):
        load_rule_package(future)


def test_current_rule_trust_versions_require_semantic_pcb_packages() -> None:
    assert RULE_SCHEMA_VERSION == 4
    assert IMPORTER_VERSION == "iec-pdf-7"


def test_legacy_schema_tells_maintainer_to_regenerate_from_pdfs(
    synthetic_package: RulePackage,
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.icrules"
    write_rule_package(current, synthetic_package)
    with zipfile.ZipFile(current) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = 1
    members["manifest.json"] = _canonical_json(manifest)
    checksums = json.loads(members["checksums.json"])
    checksums["manifest.json"] = hashlib.sha256(members["manifest.json"]).hexdigest()
    members["checksums.json"] = _canonical_json(checksums)
    legacy = tmp_path / "legacy.icrules"
    _write_members(legacy, members)

    with pytest.raises(RulePackageError, match="re-import.*licensed IEC PDFs"):
        load_rule_package(legacy)


def test_migration_creates_new_unapproved_identity(
    synthetic_package: RulePackage,
) -> None:
    migrated = migrate_rule_package(synthetic_package, target_schema=2)

    assert isinstance(migrated, DraftRulePackage)
    assert migrated.manifest.schema_version == 2
    assert migrated.manifest.package_id != synthetic_package.manifest.package_id
    assert migrated.manifest.approved is False
    assert migrated.manifest.compatible is False
    assert migrated.manifest.approval_records == ()
    assert all(mapping.approved is False for mapping in migrated.mappings)
    assert migrated.curves == synthetic_package.curves
    assert migrated.package_sha256 is None


def test_migration_preserves_decisions_procedures_and_guidance(
    synthetic_package: RulePackage,
) -> None:
    migrated = migrate_rule_package(synthetic_package, target_schema=2)

    assert migrated.decisions == synthetic_package.decisions
    assert migrated.procedures == synthetic_package.procedures
    assert migrated.guidance == synthetic_package.guidance
    assert migrated.decisions != ()
    assert migrated.procedures != ()
    assert migrated.guidance != ()


def test_draft_package_cannot_be_written_or_loaded(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    draft = migrate_rule_package(synthetic_package, target_schema=RULE_SCHEMA_VERSION)

    with pytest.raises(RulePackageError, match="approved"):
        write_rule_package(tmp_path / "draft.icrules", draft)


def test_existing_package_digest_must_match_rewritten_archive(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "original.icrules"
    write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)
    inconsistent = loaded.model_copy(update={"package_sha256": "b" * 64})

    with pytest.raises(RulePackageError, match="package digest"):
        write_rule_package(tmp_path / "other.icrules", inconsistent)


def test_duplicate_table_cell_cannot_become_usable(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    table = synthetic_package.tables[0]
    duplicate = synthetic_package.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "cells": (
                            *table.cells[:-1],
                            table.cells[-1].model_copy(update={"row": 0, "column": 0}),
                        )
                    }
                ),
            )
        }
    )

    with pytest.raises(RulePackageError, match="invalid rule package"):
        write_rule_package(tmp_path / "duplicate.icrules", duplicate)


def test_archive_boundary_revalidates_model_copy_updates(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    formula = synthetic_package.formulas[0].model_copy(
        update={"expression": {"op": "python", "code": "open('x')"}}
    )
    bypass_attempt = synthetic_package.model_copy(update={"formulas": (formula,)})

    with pytest.raises(RulePackageError, match="unknown operator"):
        write_rule_package(tmp_path / "bypass.icrules", bypass_attempt)


def test_archive_boundary_translates_raw_top_level_model_copy_updates(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    bypass_attempt = synthetic_package.model_copy(update={"tables": ({"id": "raw"},)})

    with pytest.raises(RulePackageError, match="invalid rule package"):
        write_rule_package(tmp_path / "raw-table.icrules", bypass_attempt)


def test_archive_size_is_rejected_before_unbounded_read(tmp_path: Path) -> None:
    path = tmp_path / "oversized.icrules"
    with path.open("wb") as stream:
        stream.truncate(MAX_ARCHIVE_BYTES + 1)

    with pytest.raises(RulePackageError, match="size limit"):
        load_rule_package(path)


def test_high_compression_ratio_is_rejected_before_member_read(tmp_path: Path) -> None:
    path = tmp_path / "compressed.icrules"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in (
            "manifest.json",
            "tables.json",
            "formulas.json",
            "mappings.json",
            "decisions.json",
            "procedures.json",
            "guidance.json",
            "curves.json",
            "checksums.json",
        ):
            archive.writestr(name, b"a" * 1_000_000)

    with pytest.raises(RulePackageError, match="compression ratio"):
        load_rule_package(path)


def test_deep_json_is_translated_to_rule_package_error(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    original = tmp_path / "original.icrules"
    write_rule_package(original, synthetic_package)
    with zipfile.ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    deep: object = "leaf"
    for _ in range(80):
        deep = [deep]
    members["tables.json"] = _canonical_json(deep)
    checksums = json.loads(members["checksums.json"])
    checksums["tables.json"] = hashlib.sha256(members["tables.json"]).hexdigest()
    members["checksums.json"] = _canonical_json(checksums)
    path = tmp_path / "deep.icrules"
    _write_members(path, members)

    with pytest.raises(RulePackageError, match="depth"):
        load_rule_package(path)


@pytest.mark.parametrize(
    ("location", "limit"),
    [
        ("manifest_notes", MAX_NOTES_LENGTH),
        ("approval_actor", MAX_IDENTIFIER_LENGTH),
        ("formula_latex", MAX_LATEX_LENGTH),
        ("formula_applicability", MAX_APPLICABILITY_LENGTH),
        ("mapping_notes", MAX_NOTES_LENGTH),
        ("reference_note", MAX_REFERENCE_TEXT_LENGTH),
        ("table_id", MAX_IDENTIFIER_LENGTH),
    ],
)
def test_free_text_and_identifiers_are_bounded(
    package_dict: dict[str, object], location: str, limit: int
) -> None:
    value = "x" * (limit + 1)
    if location == "manifest_notes":
        package_dict["manifest"]["notes"] = value
    elif location == "approval_actor":
        package_dict["manifest"]["approval_records"][0]["actor"] = value
    elif location == "formula_latex":
        package_dict["formulas"][0]["latex"] = value
    elif location == "formula_applicability":
        package_dict["formulas"][0]["applicability"] = value
    elif location == "mapping_notes":
        package_dict["mappings"][0]["notes"] = value
    elif location == "reference_note":
        package_dict["tables"][0]["source"]["note"] = value
    else:
        package_dict["tables"][0]["id"] = value

    with pytest.raises(RulePackageError, match="at most"):
        RulePackage.model_validate(package_dict)


def test_reference_identifiers_reject_whitespace_and_overlong_values() -> None:
    with pytest.raises(ValidationError):
        SourceReference(document_id="synthetic-source", standard=" ", edition="1")
    with pytest.raises(ValidationError):
        SourceReference(
            document_id="synthetic-source",
            standard="x" * (MAX_IDENTIFIER_LENGTH + 1),
            edition="1",
        )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def _write_members(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_schema_version_three_package_is_rejected_with_a_rebuild_message(
    tmp_path: Path,
    synthetic_package: RulePackage,
) -> None:
    path = tmp_path / "legacy.icrules"
    write_rule_package(path, synthetic_package)
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = 3
    members["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    checksums = json.loads(members["checksums.json"])
    checksums["manifest.json"] = hashlib.sha256(members["manifest.json"]).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    with pytest.raises(RulePackageError, match="re-import the licensed IEC PDFs"):
        load_rule_package(path)


def test_decisions_procedures_and_guidance_survive_a_round_trip(
    tmp_path: Path,
    synthetic_package: RulePackage,
) -> None:
    path = tmp_path / "round-trip.icrules"
    write_rule_package(path, synthetic_package)
    restored = load_rule_package(path)
    assert restored.decisions == synthetic_package.decisions
    assert restored.procedures == synthetic_package.procedures
    assert restored.guidance == synthetic_package.guidance
    assert restored.decisions != ()
