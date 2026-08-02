from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.prepare_tectonic import (
    TectonicPreparationError,
    extract_declared_member,
    prepare_tectonic,
)


def _write_tar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _fake_manifest(tmp_path: Path, archive_bytes: bytes, claimed_sha: str) -> Path:
    archive = tmp_path / "tectonic.tar.gz"
    archive.write_bytes(archive_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tectonic_version": "0.16.9",
                "licence": "MIT",
                "default_bundle_url": "https://example.test/bundle.tar",
                "default_bundle_sha256": "0" * 64,
                "platforms": {
                    "linux-x86_64": {
                        "archive_url": archive.as_uri(),
                        "archive_sha256": claimed_sha,
                        "archive_member": "tectonic",
                        "executable_path": "tectonic/tectonic",
                        "cache_path": "tectonic/cache",
                        "lock_path": "tectonic-locks/linux-x86_64.json",
                        "offline_flag": "--only-cached",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_prepare_tectonic_rejects_archive_hash_mismatch(tmp_path: Path) -> None:
    manifest = _fake_manifest(tmp_path, b"archive", "0" * 64)

    with pytest.raises(TectonicPreparationError, match="archive SHA-256"):
        prepare_tectonic("linux-x86_64", tmp_path / "stage", manifest_path=manifest)


def test_safe_extract_rejects_parent_member(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    _write_tar(archive, {"../tectonic": b"binary"})

    with pytest.raises(TectonicPreparationError, match="archive member"):
        extract_declared_member(archive, "../tectonic", tmp_path / "out")


def test_prepare_tectonic_extracts_declared_member(tmp_path: Path) -> None:
    payload = b"not-an-executable"
    archive = tmp_path / "tectonic.tar.gz"
    _write_tar(archive, {"tectonic": payload})
    manifest = _fake_manifest(tmp_path, archive.read_bytes(), hashlib.sha256(archive.read_bytes()).hexdigest())

    with pytest.raises(TectonicPreparationError, match="version"):
        prepare_tectonic("linux-x86_64", tmp_path / "stage", manifest_path=manifest)
