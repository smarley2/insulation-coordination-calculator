from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import DraftRulePackage, RulePackage, RulePackageError
from insulation_coordination.rules.archive import (
    load_rule_package,
    migrate_rule_package,
    write_rule_package,
)


def test_approved_package_loads_without_source_pdfs(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "company.icrules"

    digest = write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)

    assert loaded.manifest.approved is True
    assert loaded.package_sha256 == digest
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


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
            "checksums.json",
        ]
        assert {member.date_time for member in archive.infolist()} == {
            (1980, 1, 1, 0, 0, 0)
        }
        checksums = json.loads(archive.read("checksums.json"))
        assert set(checksums) == {
            "manifest.json",
            "tables.json",
            "formulas.json",
            "mappings.json",
        }


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


def test_load_rejects_extra_archive_members(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    path = tmp_path / "extra.icrules"
    write_rule_package(path, synthetic_package)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("payload.py", "open('x')")

    with pytest.raises(RulePackageError, match="members"):
        load_rule_package(path)


def test_migration_creates_new_unapproved_identity(
    synthetic_package: RulePackage,
) -> None:
    migrated = migrate_rule_package(synthetic_package, target_schema=2)

    assert isinstance(migrated, DraftRulePackage)
    assert migrated.manifest.schema_version == 2
    assert migrated.manifest.package_id != synthetic_package.manifest.package_id
    assert migrated.manifest.approved is False
    assert migrated.manifest.approval_records == ()
    assert migrated.package_sha256 is None


def test_draft_package_cannot_be_written_or_loaded(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    draft = migrate_rule_package(synthetic_package, target_schema=1)

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


def test_structurally_invalid_package_cannot_become_usable(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    table = synthetic_package.tables[0]
    incomplete = synthetic_package.model_copy(
        update={
            "tables": (
                table.model_copy(update={"cells": table.cells[:-1]}),
            )
        }
    )

    with pytest.raises(RulePackageError, match="validation"):
        write_rule_package(tmp_path / "incomplete.icrules", incomplete)


def test_archive_boundary_revalidates_model_copy_updates(
    synthetic_package: RulePackage, tmp_path: Path
) -> None:
    formula = synthetic_package.formulas[0].model_copy(
        update={"expression": {"op": "python", "code": "open('x')"}}
    )
    bypass_attempt = synthetic_package.model_copy(update={"formulas": (formula,)})

    with pytest.raises(RulePackageError, match="unknown operator"):
        write_rule_package(tmp_path / "bypass.icrules", bypass_attempt)
