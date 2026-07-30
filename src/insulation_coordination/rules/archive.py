from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    DraftRulePackage,
    RulePackage,
    RulePackageError,
)

CORE_MEMBERS = ("manifest.json", "tables.json", "formulas.json", "mappings.json")
ARCHIVE_MEMBERS = (*CORE_MEMBERS, "checksums.json")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _core_member_payloads(package: RulePackage) -> dict[str, bytes]:
    return {
        "manifest.json": _canonical_json(package.manifest.model_dump(mode="json")),
        "tables.json": _canonical_json(
            [table.model_dump(mode="json") for table in package.tables]
        ),
        "formulas.json": _canonical_json(
            [formula.model_dump(mode="json") for formula in package.formulas]
        ),
        "mappings.json": _canonical_json(
            [mapping.model_dump(mode="json") for mapping in package.mappings]
        ),
    }


def _member_checksums(payloads: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(payloads[name]).hexdigest() for name in CORE_MEMBERS}


def _require_usable_metadata(package: RulePackage) -> None:
    if package.manifest.schema_version != RULE_SCHEMA_VERSION:
        raise RulePackageError(
            f"unsupported schema {package.manifest.schema_version}; expected {RULE_SCHEMA_VERSION}"
        )
    if not package.manifest.approved:
        raise RulePackageError("rule package must be approved")
    if not package.manifest.compatible or any(
        not mapping.approved for mapping in package.mappings
    ):
        raise RulePackageError("rule package must have approved compatibility mappings")
    if not any(record.action == "approval" for record in package.manifest.approval_records):
        raise RulePackageError("approved rule package requires an approval record")


def _archive_bytes(package: RulePackage) -> tuple[bytes, dict[str, str]]:
    payloads = _core_member_payloads(package)
    checksums = _member_checksums(payloads)
    payloads["checksums.json"] = _canonical_json(checksums)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in ARCHIVE_MEMBERS:
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, payloads[name])
    return buffer.getvalue(), checksums


def _require_valid(package: RulePackage) -> None:
    from insulation_coordination.rules.validation import validate_rule_package

    report = validate_rule_package(package)
    if not report.is_valid:
        failures = ", ".join(result.code for result in report.results if not result.passed)
        raise RulePackageError(f"rule package validation failed: {failures}")


def _revalidate(package: RulePackage) -> RulePackage:
    return RulePackage.model_validate(
        {
            "manifest": package.manifest.model_dump(mode="json", warnings=False),
            "tables": [
                table.model_dump(mode="json", warnings=False)
                for table in package.tables
            ],
            "formulas": [
                formula.model_dump(mode="json", warnings=False)
                for formula in package.formulas
            ],
            "mappings": [
                mapping.model_dump(mode="json", warnings=False)
                for mapping in package.mappings
            ],
            "checksums": package.checksums,
            "package_sha256": package.package_sha256,
        }
    )


def write_rule_package(path: Path, package: RulePackage) -> str:
    package = _revalidate(package)
    _require_usable_metadata(package)
    content, checksums = _archive_bytes(package)
    digest = hashlib.sha256(content).hexdigest()
    _require_valid(
        package.model_copy(
            update={"checksums": checksums, "package_sha256": digest}
        )
    )
    if package.package_sha256 is not None and package.package_sha256 != digest:
        raise RulePackageError("inconsistent package digest")
    path.write_bytes(content)
    return digest


def _read_members(path: Path) -> tuple[dict[str, bytes], bytes]:
    try:
        content = path.read_bytes()
        if len(content) > MAX_ARCHIVE_BYTES:
            raise RulePackageError("rules archive exceeds the size limit")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(ARCHIVE_MEMBERS):
                raise RulePackageError("rules archive has missing, duplicate, or extra members")
            if any(
                member.is_dir() or member.file_size > MAX_MEMBER_BYTES
                for member in archive.infolist()
            ) or sum(member.file_size for member in archive.infolist()) > MAX_ARCHIVE_BYTES:
                raise RulePackageError("rules archive member exceeds the size limit")
            return {name: archive.read(name) for name in ARCHIVE_MEMBERS}, content
    except RulePackageError:
        raise
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise RulePackageError(f"could not read rules archive: {error}") from error


def _decode_json(payload: bytes, member: str) -> Any:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RulePackageError(f"invalid JSON in {member}: {error}") from error
    try:
        if payload != _canonical_json(value):
            raise RulePackageError(f"{member} is not canonical JSON")
    except (TypeError, ValueError) as error:
        raise RulePackageError(f"invalid JSON value in {member}: {error}") from error
    return value


def load_rule_package(path: Path) -> RulePackage:
    members, content = _read_members(path)
    checksums = _decode_json(members["checksums.json"], "checksums.json")
    if not isinstance(checksums, dict) or set(checksums) != set(CORE_MEMBERS):
        raise RulePackageError("checksums.json must cover exactly the canonical members")
    for name in CORE_MEMBERS:
        claimed = checksums[name]
        if not isinstance(claimed, str) or _SHA256.fullmatch(claimed) is None:
            raise RulePackageError(f"invalid checksum for {name}")
        if hashlib.sha256(members[name]).hexdigest() != claimed:
            raise RulePackageError(f"checksum mismatch for {name}")

    manifest = _decode_json(members["manifest.json"], "manifest.json")
    if not isinstance(manifest, dict):
        raise RulePackageError("manifest.json root must be an object")
    schema = manifest.get("schema_version")
    if schema != RULE_SCHEMA_VERSION:
        raise RulePackageError(f"unsupported schema {schema}")
    package = RulePackage.model_validate(
        {
            "manifest": manifest,
            "tables": _decode_json(members["tables.json"], "tables.json"),
            "formulas": _decode_json(members["formulas.json"], "formulas.json"),
            "mappings": _decode_json(members["mappings.json"], "mappings.json"),
            "checksums": checksums,
            "package_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    _require_usable_metadata(package)
    _require_valid(package)
    expected_content, _ = _archive_bytes(package)
    if expected_content != content:
        raise RulePackageError("inconsistent package digest or archive metadata")
    return package


def migrate_rule_package(
    package: RulePackage, target_schema: int
) -> DraftRulePackage:
    if isinstance(target_schema, bool) or target_schema < 1:
        raise RulePackageError("target schema must be a positive integer")
    manifest = package.manifest.model_copy(
        update={
            "schema_version": target_schema,
            "package_id": uuid4(),
            "approved": False,
            "compatible": False,
            "approval_records": (),
        }
    )
    return DraftRulePackage(
        manifest=manifest,
        tables=package.tables,
        formulas=package.formulas,
        mappings=tuple(
            mapping.model_copy(update={"approved": False}) for mapping in package.mappings
        ),
    )
